"""RAG Document Management API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()

CATEGORIES = ["troubleshooting", "policy", "hardware", "knowledge"]
MODELS = ["all", "Nextlink-Coax-V2", "Nextlink-Optic-V1", "Nextlink-WiFi-V3"]


_cached_store = None

def _get_store():
    global _cached_store
    if _cached_store is not None:
        return _cached_store
    from rag.config import RAGConfig
    from rag.embeddings import create_embedding_provider
    from rag.vector_store import VectorStore

    config = RAGConfig()
    embedder = create_embedding_provider(config)
    _cached_store = VectorStore(config, embedder)
    _cached_store.ensure_collection()
    return _cached_store


class DocumentCreate(BaseModel):
    doc_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    category: str = "knowledge"
    model: str = "all"
    doc_date: str = "2026-01-01"
    source_doc: str = ""


class DocumentResponse(BaseModel):
    doc_id: str
    source_doc: str
    category: str
    model: str
    doc_date: str
    chunk_count: int


class DocumentDetailResponse(DocumentResponse):
    chunks: list = []


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    total_chunks: int


@router.get("/rag/documents", response_model=DocumentListResponse)
def list_documents():
    """List all documents in the RAG system."""
    store = _get_store()
    docs = store.list_documents()
    total_chunks = sum(d["chunk_count"] for d in docs)
    return DocumentListResponse(
        documents=docs,
        total=len(docs),
        total_chunks=total_chunks,
    )


@router.get("/rag/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document(doc_id: str):
    """Get a specific document with its chunks."""
    store = _get_store()
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
    return doc


@router.post("/rag/documents", response_model=DocumentResponse, status_code=201)
def create_document(body: DocumentCreate):
    """Add a new document to the RAG system."""
    if body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {CATEGORIES}")
    if body.model not in MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model. Must be one of: {MODELS}")

    store = _get_store()
    existing = store.get_document(body.doc_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Document '{body.doc_id}' already exists")

    chunk_count = store.add_document(
        doc_id=body.doc_id,
        text=body.text,
        category=body.category,
        model=body.model,
        doc_date=body.doc_date,
        source_doc=body.source_doc,
    )
    return DocumentResponse(
        doc_id=body.doc_id,
        source_doc=body.source_doc or f"{body.doc_id}.md",
        category=body.category,
        model=body.model,
        doc_date=body.doc_date,
        chunk_count=chunk_count,
    )


@router.delete("/rag/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    """Delete a document from the RAG system."""
    store = _get_store()
    deleted = store.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")


@router.get("/rag/stats")
def get_rag_stats():
    """Get RAG system statistics."""
    store = _get_store()
    docs = store.list_documents()
    total_chunks = sum(d["chunk_count"] for d in docs)
    categories = {}
    models = {}
    for d in docs:
        cat = d["category"]
        mod = d["model"]
        categories[cat] = categories.get(cat, 0) + 1
        models[mod] = models.get(mod, 0) + 1
    return {
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "by_category": categories,
        "by_model": models,
    }
