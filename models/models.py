from pydantic import BaseModel, Field
from typing import List, Optional, Union
from enum import Enum


class Source(str, Enum):
    email = "email"
    file = "file"
    chat = "chat"
    web  = "web"


class DocumentMetadata(BaseModel):
    source: Optional[Source] = None
    source_id: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    author: Union[str, List[str]] = None
    title: Optional[str] = None
    description: Optional[str] = None
    

class DocumentChunkMetadata(DocumentMetadata):
    document_id: Optional[str] = None


class DocumentChunk(BaseModel):
    id: Optional[str] = None
    text: str
    metadata: DocumentChunkMetadata
    embedding: Optional[List[float]] = None

    def __str__(self):
        if len(self.text) > 100:
            text = self.text[:100] + '...'
        else: 
            text = self.text
        text = text.replace('\n', ' ')
        estr = "DocumentChunk("
        if self.id is not None:
            estr += f"id={self.id}, "
        if self.metadata is not None:
            estr += f"metadata={str(self.metadata)}, "
        if self.embedding is not None:
            estr += f"embedding=dim{len(self.embedding)}, "
        estr += f"text={text})"
        return estr


class DocumentChunkWithScore(DocumentChunk):
    score: float


class Document(BaseModel):
    id: Optional[str] = None
    text: str
    metadata: Optional[DocumentMetadata] = None


class DocumentWithChunks(Document):
    chunks: List[DocumentChunk]


class DocumentMetadataFilter(BaseModel):
    document_id: Optional[str] = None
    source: Optional[Source] = None
    source_id: Optional[str] = None
    author: Optional[str] = None
    start_date: Optional[str] = None  # any date string format
    end_date: Optional[str] = None  # any date string format
    title: Optional[str] = None
    url: Optional[str] = None


class Query(BaseModel):
    query: str = Field(..., min_length=1)
    filter: Optional[DocumentMetadataFilter] = None
    top_k: Optional[int] = 7

class QueryWithEmbedding(Query):
    embedding: List[float]


class QueryResult(BaseModel):
    query: str
    results: List[DocumentChunkWithScore]
