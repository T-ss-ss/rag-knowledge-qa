from fastapi import APIRouter, Depends, Query, Request

from app.repositories.kb_repo import KBRepo
from app.repositories.doc_repo import DocRepo
from app.services.vector_store import VectorStoreService
from app.utils.exceptions import (
    DocumentNotFoundError,
    KnowledgeBaseNotFoundError,
)

router = APIRouter(prefix="/api/documents", tags=["文档管理"])


def get_vector_store(request: Request) -> VectorStoreService:
    return request.app.state.vector_store


def get_kb_repo() -> KBRepo:
    return KBRepo()


def get_doc_repo() -> DocRepo:
    return DocRepo()


@router.get("", summary="文档列表")
def list_documents(
    kb_id: str = Query(default="default", description="知识库 ID"),
    kb_repo: KBRepo = Depends(get_kb_repo),
    doc_repo: DocRepo = Depends(get_doc_repo),
):
    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)
    docs = doc_repo.list_by_kb(kb_id)
    return {"documents": docs, "total_count": len(docs)}


@router.delete("/{document_id}", summary="删除文档")
def delete_document(
    document_id: str,
    kb_id: str = Query(default="default", description="知识库 ID"),
    vector_store: VectorStoreService = Depends(get_vector_store),
    kb_repo: KBRepo = Depends(get_kb_repo),
    doc_repo: DocRepo = Depends(get_doc_repo),
):
    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    doc = doc_repo.get(document_id)
    if not doc or doc["kb_id"] != kb_id:
        raise DocumentNotFoundError(document_id)

    vector_store.delete_document(kb["collection_name"], document_id)
    doc_repo.delete(document_id, kb_id)
    kb_repo.decrement_doc_count(kb_id)

    return {"document_id": document_id, "status": "deleted"}
