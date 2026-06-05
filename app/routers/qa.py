from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.models.schemas import QuestionRequest, AnswerResponse
from app.repositories.kb_repo import KBRepo
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.rag_service import RAGService
from app.utils.exceptions import KnowledgeBaseNotFoundError

router = APIRouter(prefix="/api/qa", tags=["智能问答"])


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def get_vector_store(request: Request) -> VectorStoreService:
    return request.app.state.vector_store


def get_kb_repo() -> KBRepo:
    return KBRepo()


@router.post("", summary="提交问题", response_model=AnswerResponse)
async def ask_question(
    body: QuestionRequest,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStoreService = Depends(get_vector_store),
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    kb = kb_repo.get(body.kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(body.kb_id)

    collection_name = kb["collection_name"]
    vector_store.get_or_create_collection(collection_name)

    if vector_store.count(collection_name) == 0:
        return JSONResponse(
            content={
                "question": body.question,
                "kb_id": body.kb_id,
                "summary": "",
                "answer": "该知识库中还没有文档，请先上传 PDF。",
                "sources": [],
                "model_used": "",
            }
        )

    rag_service = RAGService(vector_store, embedding_service, collection_name)
    result = rag_service.ask(
        question=body.question,
        top_k=body.top_k,
        temperature=body.temperature,
        rerank=body.rerank,
        retrieval_top_k=body.retrieval_top_k,
    )
    return result
