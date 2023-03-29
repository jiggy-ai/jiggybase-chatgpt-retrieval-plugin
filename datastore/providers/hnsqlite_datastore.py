import os
from typing import Any, Dict, List, Optional
import hnsqlite

from datastore.datastore import DataStore
from models.models import (
    DocumentChunk,
    DocumentChunkMetadata,
    DocumentChunkWithScore,
    DocumentMetadataFilter,
    QueryResult,
    QueryWithEmbedding,
    Source,
)
from services.date import to_unix_timestamp

HNSQLITE_COLLECTION = os.environ.get("HNSQLITE_COLLECTION", 'default')
HNSQLITE_DIR        = os.environ.get("HNSQLITE_DIR")

    
class HnsqliteDataStore(DataStore):
    def __init__(self):
        if HNSQLITE_DIR:
            os.chdir(HNSQLITE_DIR)
        try:
            self.collection = hnsqlite.Collection.from_db(HNSQLITE_COLLECTION)
            print(f'loaded collection {HNSQLITE_COLLECTION} from db with {self.collection.count()} items' )
        except FileNotFoundError:
            self.collection = hnsqlite.Collection.create(HNSQLITE_COLLECTION, dim=1536)
            print(f'created collection {HNSQLITE_COLLECTION} from db' )
   
            
    async def _upsert(self, chunks: Dict[str, List[DocumentChunk]]) -> List[str]:
        """
        Takes in a dict from document id to list of document chunks and inserts them into the index.
        Return a list of document ids.
        """
        # Initialize a list of ids to return
        doc_ids: List[str] = []
        # Initialize a list of vectors to add to the index
        embeddings = []
        # Loop through the dict items
        for doc_id, chunk_list in chunks.items():
            # Append the id to the ids list
            doc_ids.append(doc_id)
            print(f"Upserting document_id: {doc_id}")
            for chunk in chunk_list:
                # Create a vector tuple of (id, embedding, metadata)
                # Convert the metadata object to a dict with unix timestamps for dates
                hnsqlite_metadata = self._get_hnsqlite_metadata(chunk.metadata)
                # Add document chunk id to the metadata dict in a way that is unlikely to conflict with other metadata
                hnsqlite_metadata['hnsqlite:doc_chunk_id']  = chunk.id                
                embeddings.append(hnsqlite.Embedding(vector = chunk.embedding, 
                                                     text = chunk.text,
                                                     doc_id = doc_id,
                                                     metadata = hnsqlite_metadata))
        self.collection.add_embeddings(embeddings)
        for e in embeddings:
            print(f'added embedding {e}')
        return doc_ids

    async def _query(
        self,
        queries: List[QueryWithEmbedding],
    ) -> List[QueryResult]:
        """
        Takes in a list of queries with embeddings and filters and returns a list of query results with matching document chunks and scores.
        """

        # Define a helper coroutine that performs a single query and returns a QueryResult
        def _single_query(query: QueryWithEmbedding) -> QueryResult:
            print(f"Query: {query.query}")

            # Convert the metadata filter object to a dict with hnsqlite filter expressions
            hnsqlite_filter = self._get_hnsqlite_filter(query.filter)
            
            try:
                # Query the index with the query embedding, filter, and top_k            
                search_responses = self.collection.search(vector=query.embedding,
                                                          k=query.top_k,
                                                          filter=hnsqlite_filter)
            except hnsqlite.NoResultError:
                return QueryResult(query=query.query, results=[])
            except Exception as e:
                print(f"Error querying index: {e}")
                raise e

            query_results: List[DocumentChunkWithScore] = []
            for search_response in search_responses:                                    
                # Create a document chunk with score object with the result data
                doc_chunk_id = search_response.metadata.pop('hnsqlite:doc_chunk_id')
                dcws = DocumentChunkWithScore(id = doc_chunk_id,
                                              score = 1 - search_response.distance,
                                              text = search_response.text,
                                              metadata = search_response.metadata)
                query_results.append(dcws)
            return QueryResult(query=query.query, results=query_results)

        return [_single_query(q) for q in queries]

    async def _chunks(self, start: int, limit: int, reverse :bool) -> List[DocumentChunk]:
        """
        Returns a list of document chunks from the datastore
        """
        embeddings = self.collection.get_embeddings(start=start, limit=limit, reverse=reverse)
        results = [DocumentChunk(id = e.metadata.pop('hnsqlite:doc_chunk_id'),
                                 text = e.text,
                                 metadata = e.metadata) for e in embeddings]
        return results
    
        
    def count(self) -> int:
        """
        Returns the number of vectors in the index.
        """
        return self.collection.count()
    
    async def delete(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[DocumentMetadataFilter] = None,
        delete_all: Optional[bool] = None,
    ) -> bool:
        """
        Removes vectors by ids, filter, or everything from the index.
        """
        # Delete all vectors from the index if delete_all is True
        if delete_all == True:
            try:
                print(f"Deleting all vectors from index")
                self.collection.delete(delete_all=True)
                print(f"Deleted all vectors successfully")
                return True
            except Exception as e:
                print(f"Error deleting all vectors: {e}")
                raise e

        # Convert the metadata filter object to a dict with hnsqlite filter expressions
        hnsqlite_filter = self._get_hnsqlite_filter(filter)
        # Delete vectors that match the filter from the index if the filter is not empty
        if hnsqlite_filter != {}:
            try:
                print(f"Deleting vectors with filter {hnsqlite_filter}")
                self.collection.delete(filter=hnsqlite_filter)
                print(f"Deleted vectors with filter successfully")
            except Exception as e:
                print(f"Error deleting vectors with filter: {e}")
                raise e

        # Delete vectors that match the document ids from the index if the ids list is not empty
        if ids != None and len(ids) > 0:
            try:
                print(f"Deleting vectors with ids {ids}")
                self.collection.delete(doc_ids=ids)
                print(f"Deleted vectors with ids successfully")
            except Exception as e:
                print(f"Error deleting vectors with ids: {e}")
                raise e

        return True

    def _get_hnsqlite_filter(
        self, filter: Optional[DocumentMetadataFilter] = None
    ) -> Dict[str, Any]:
        if filter is None:
            return {}

        hnsqlite_filter = {}

        # For each field in the MetadataFilter, check if it has a value and add the corresponding hnsqlite filter expression
        # For start_date and end_date, uses the $gte and $lte operators respectively
        # For other fields, uses the $eq operator
        for field, value in filter.dict().items():
            if value is not None:
                if field == "start_date":
                    hnsqlite_filter["created_at"] = hnsqlite_filter.get("created_at", {})
                    hnsqlite_filter["created_at"]["$gte"] = to_unix_timestamp(value)
                elif field == "end_date":
                    hnsqlite_filter["created_at"] = hnsqlite_filter.get("created_at", {})
                    hnsqlite_filter["created_at"]["$lte"] = to_unix_timestamp(value)
                else:
                    hnsqlite_filter[field] = value

        return hnsqlite_filter

    def _get_hnsqlite_metadata(
        self, metadata: Optional[DocumentChunkMetadata] = None
    ) -> Dict[str, Any]:
        if metadata is None:
            return {}

        hnsqlite_metadata = {}

        # For each field in the Metadata, check if it has a value and add it to the hnsqlite metadata dict
        # For fields that are dates, convert them to unix timestamps
        for field, value in metadata.dict().items():
            if value is not None:
                if field in ["created_at"]:
                    hnsqlite_metadata[field] = to_unix_timestamp(value)
                else:
                    hnsqlite_metadata[field] = value

        return hnsqlite_metadata
