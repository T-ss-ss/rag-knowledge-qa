import uuid

from fastapi import APIRouter, Depends, Request

from app.db.database import DEFAULT_KB_ID
from app.models.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.repositories.kb_repo import KBRepo
from app.repositories.doc_repo import DocRepo
from app.services.vector_store import VectorStoreService
from app.utils.exceptions import (
    KnowledgeBaseNotFoundError,
    KnowledgeBaseAlreadyExistsError,
    DefaultKnowledgeBaseDeleteError,
)

router = APIRouter(prefix="/api/knowledge-bases", tags=["知识库管理"])


def get_vector_store(request: Request) -> VectorStoreService:
    return request.app.state.vector_store


def get_kb_repo() -> KBRepo:
    return KBRepo()


def get_doc_repo() -> DocRepo:
    return DocRepo()


@router.post("", summary="创建知识库")
def create_knowledge_base(
    body: KnowledgeBaseCreate,
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    existing = kb_repo.get_by_name(body.name)
    if existing:
        raise KnowledgeBaseAlreadyExistsError(body.name)
    kb = kb_repo.create(uuid.uuid4().hex, body.name, body.description)
    return kb


@router.get("", summary="获取知识库列表")
def list_knowledge_bases(
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    kbs = kb_repo.list_all()
    return {"knowledge_bases": kbs, "total_count": len(kbs)}


@router.get("/{kb_id}", summary="获取知识库详情")
def get_knowledge_base(
    kb_id: str,
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)
    return kb


@router.put("/{kb_id}", summary="更新知识库")
def update_knowledge_base(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)
    if body.name is not None:
        existing = kb_repo.get_by_name(body.name)
        if existing and existing["id"] != kb_id:
            raise KnowledgeBaseAlreadyExistsError(body.name)
    kb = kb_repo.update(kb_id, body.name, body.description)
    return kb


@router.delete("/{kb_id}", summary="删除知识库")
def delete_knowledge_base(
    kb_id: str,
    vector_store: VectorStoreService = Depends(get_vector_store),
    kb_repo: KBRepo = Depends(get_kb_repo),
    doc_repo: DocRepo = Depends(get_doc_repo),
):
    if kb_id == DEFAULT_KB_ID:
        raise DefaultKnowledgeBaseDeleteError()

    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    vector_store.delete_collection(kb["collection_name"])
    doc_repo.list_by_kb(kb_id)  # CASCADE delete is handled by SQLite FK
    kb_repo.delete(kb_id)

    return {"kb_id": kb_id, "status": "deleted"}
