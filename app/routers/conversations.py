import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.models.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationQARequest,
    ConversationQAResponse,
    AgentQARequest,
    AgentQAResponse,
)
from app.repositories.conv_repo import ConvRepo
from app.repositories.msg_repo import MsgRepo
from app.repositories.kb_repo import KBRepo
from app.services.chat_service import ChatService
from app.services.agent_service import AgentService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.utils.exceptions import (
    ConversationNotFoundError,
    KnowledgeBaseNotFoundError,
)

router = APIRouter(prefix="/api/conversations", tags=["聊天历史"])


def get_vector_store(request: Request) -> VectorStoreService:
    return request.app.state.vector_store


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def get_conv_repo() -> ConvRepo:
    return ConvRepo()


def get_msg_repo() -> MsgRepo:
    return MsgRepo()


def get_kb_repo() -> KBRepo:
    return KBRepo()


@router.post("", summary="创建会话")
async def create_conversation(
    body: ConversationCreate,
    kb_repo: KBRepo = Depends(get_kb_repo),
    conv_repo: ConvRepo = Depends(get_conv_repo),
):
    kb = kb_repo.get(body.kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(body.kb_id)
    conv = conv_repo.create(uuid.uuid4().hex, body.kb_id, body.title)
    return conv


@router.get("", summary="会话列表")
async def list_conversations(
    kb_id: str = Query(default="default", description="知识库 ID"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    conv_repo: ConvRepo = Depends(get_conv_repo),
):
    convs, total = conv_repo.list_by_kb(kb_id, page, page_size)
    return {"conversations": convs, "total_count": total}


@router.get("/{conv_id}", summary="会话详情")
async def get_conversation(
    conv_id: str,
    conv_repo: ConvRepo = Depends(get_conv_repo),
    msg_repo: MsgRepo = Depends(get_msg_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)
    messages = msg_repo.list_by_conv(conv_id)
    conv["messages"] = messages
    return conv


@router.patch("/{conv_id}", summary="修改标题")
async def update_conversation(
    conv_id: str,
    body: ConversationUpdate,
    conv_repo: ConvRepo = Depends(get_conv_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)
    return conv_repo.update_title(conv_id, body.title)


@router.delete("/{conv_id}", summary="删除会话")
async def delete_conversation(
    conv_id: str,
    conv_repo: ConvRepo = Depends(get_conv_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)
    conv_repo.delete(conv_id)
    return {"conversation_id": conv_id, "status": "deleted"}


@router.post("/{conv_id}/qa", summary="会话内问答", response_model=ConversationQAResponse)
async def conversation_qa(
    conv_id: str,
    body: ConversationQARequest,
    request: Request,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStoreService = Depends(get_vector_store),
    conv_repo: ConvRepo = Depends(get_conv_repo),
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)

    kb = kb_repo.get(conv["kb_id"])
    if not kb:
        raise KnowledgeBaseNotFoundError(conv["kb_id"])

    collection_name = kb["collection_name"]
    vector_store.get_or_create_collection(collection_name)

    if vector_store.count(collection_name) == 0:
        return JSONResponse(
            content={
                "conversation_id": conv_id,
                "user_message": None,
                "assistant_message": {
                    "id": 0,
                    "role": "assistant",
                    "content": "该知识库中还没有文档，请先上传 PDF。",
                    "sources": None,
                    "model": None,
                    "created_at": "",
                },
                "answer": "该知识库中还没有文档，请先上传 PDF。",
                "summary": "",
                "sources": [],
                "model_used": "",
            }
        )

    chat_service = ChatService(vector_store, embedding_service, collection_name)
    result = chat_service.ask(
        conversation_id=conv_id,
        question=body.question,
        top_k=body.top_k,
        temperature=body.temperature,
        rerank=body.rerank,
        retrieval_top_k=body.retrieval_top_k,
    )
    return result


@router.post("/{conv_id}/agent", summary="Agent 模式问答", response_model=AgentQAResponse)
async def conversation_agent(
    conv_id: str,
    body: AgentQARequest,
    request: Request,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStoreService = Depends(get_vector_store),
    conv_repo: ConvRepo = Depends(get_conv_repo),
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)

    kb = kb_repo.get(conv["kb_id"])
    if not kb:
        raise KnowledgeBaseNotFoundError(conv["kb_id"])

    collection_name = kb["collection_name"]
    vector_store.get_or_create_collection(collection_name)

    if vector_store.count(collection_name) == 0:
        return JSONResponse(
            content={
                "conversation_id": conv_id,
                "user_message": None,
                "assistant_message": {
                    "id": 0,
                    "role": "assistant",
                    "content": "该知识库中还没有文档，请先上传 PDF。",
                    "sources": None,
                    "model": None,
                    "created_at": "",
                },
                "answer": "该知识库中还没有文档，请先上传 PDF。",
                "summary": "",
                "sources": [],
                "model_used": "",
                "reasoning_steps": [],
            }
        )

    agent_service = AgentService(vector_store, embedding_service, collection_name)
    result = agent_service.ask(
        conversation_id=conv_id,
        question=body.question,
        top_k=body.top_k,
        temperature=body.temperature,
        max_iterations=body.max_iterations,
    )
    return result


@router.post("/{conv_id}/agent/stream", summary="Agent 流式问答")
async def conversation_agent_stream(
    conv_id: str,
    body: AgentQARequest,
    request: Request,
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStoreService = Depends(get_vector_store),
    conv_repo: ConvRepo = Depends(get_conv_repo),
    kb_repo: KBRepo = Depends(get_kb_repo),
):
    conv = conv_repo.get(conv_id)
    if not conv:
        raise ConversationNotFoundError(conv_id)

    kb = kb_repo.get(conv["kb_id"])
    if not kb:
        raise KnowledgeBaseNotFoundError(conv["kb_id"])

    collection_name = kb["collection_name"]
    vector_store.get_or_create_collection(collection_name)

    if vector_store.count(collection_name) == 0:
        import json as _json
        empty_msg = "该知识库中还没有文档，请先上传 PDF。"

        def _empty_stream():
            yield f"event: token\ndata: {_json.dumps({'token': empty_msg})}\n\n"
            yield f"event: done\ndata: {_json.dumps({'conversation_id': conv_id, 'message_id': 0})}\n\n"
        return StreamingResponse(_empty_stream(), media_type="text/event-stream")

    agent_service = AgentService(vector_store, embedding_service, collection_name)
    return StreamingResponse(
        agent_service.ask_stream(
            conversation_id=conv_id,
            question=body.question,
            top_k=body.top_k,
            temperature=body.temperature,
            max_iterations=body.max_iterations,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
