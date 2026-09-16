import uuid

from fastapi import APIRouter, Request, UploadFile, File, Form, Depends

from app.config import settings
from app.repositories.kb_repo import KBRepo
from app.repositories.doc_repo import DocRepo
from app.services.pdf_service import PDFService
from app.services.word_service import WordService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.utils.exceptions import (
    InvalidFileTypeError,
    FileTooLargeError,
    EmptyPDFError,
    KnowledgeBaseNotFoundError,
)

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

router = APIRouter(prefix="/api/upload", tags=["文档上传"])


def _estimate_chunk_pages(page_count: int, chunk_count: int) -> list[int]:
    """按 chunk 在全文中的相对位置，线性折算每个 chunk 的页码（估算值）。

    页边界在解析层就已丢失（整篇文本一次性切块），所以这里只能估算而非精确定位；
    若要精确页码，需让解析层逐页返回 (页码, 文本) 并逐页切块。

    页码从 1 开始 —— 全链路约定 page == 0 表示"页码不可知"，若此处产出 0，
    首块会被误判为未知。（例如 5 页 4 块 -> [1, 2, 3, 4]）

    page_count == 0 表示来源格式的页数不可知（例如未记录页数的 DOCX），
    此时所有 chunk 的页码统一记为 0。绝不能拿别的计数（如段落数）顶替，
    否则会编造出不存在的页码。
    """
    if page_count <= 0:
        return [0] * chunk_count
    return [
        min(page_count, int(i * page_count / chunk_count) + 1)
        for i in range(chunk_count)
    ]


def get_pdf_service() -> PDFService:
    return PDFService()


def get_word_service() -> WordService:
    return WordService()


def get_chunking_service() -> ChunkingService:
    return ChunkingService()


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def get_vector_store(request: Request) -> VectorStoreService:
    return request.app.state.vector_store


def get_kb_repo() -> KBRepo:
    return KBRepo()


def get_doc_repo() -> DocRepo:
    return DocRepo()


@router.post("", summary="上传文档（PDF / DOCX）")
async def upload_file(
    file: UploadFile = File(...),
    kb_id: str = Form(default="default", description="知识库 ID"),
    pdf_service: PDFService = Depends(get_pdf_service),
    word_service: WordService = Depends(get_word_service),
    chunking_service: ChunkingService = Depends(get_chunking_service),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    vector_store: VectorStoreService = Depends(get_vector_store),
    kb_repo: KBRepo = Depends(get_kb_repo),
    doc_repo: DocRepo = Depends(get_doc_repo),
):
    if file.content_type not in ALLOWED_TYPES:
        raise InvalidFileTypeError()

    kb = kb_repo.get(kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    contents = await file.read()
    if len(contents) > settings.max_file_size_mb * 1024 * 1024:
        raise FileTooLargeError(settings.max_file_size_mb)

    if file.content_type == "application/pdf":
        full_text, page_count = pdf_service.extract_text(contents)
    else:
        full_text, page_count = word_service.extract_text(contents)
    if not full_text.strip():
        raise EmptyPDFError()

    chunks = chunking_service.split(full_text)
    chunk_count = len(chunks)
    if chunk_count == 0:
        raise EmptyPDFError()

    # 页码估算：解析层返回整篇文本 + 总页数，页边界信息已在切块前丢失。
    # page_count == 0 时（页数不可知）所有 chunk 页码为 0，不编造。
    pages = _estimate_chunk_pages(page_count, chunk_count)

    embeddings = embedding_service.embed_texts(chunks)
    document_id = uuid.uuid4().hex
    collection_name = kb["collection_name"]

    vector_store.get_or_create_collection(collection_name)
    vector_store.add_chunks(
        collection_name=collection_name,
        chunks=chunks,
        embeddings=embeddings,
        filename=file.filename or "unknown.pdf",
        document_id=document_id,
        pages=pages,
    )

    doc_repo.add(document_id, kb_id, file.filename or "unknown.pdf", page_count, chunk_count)
    kb_repo.increment_doc_count(kb_id)

    return {
        "document_id": document_id,
        "kb_id": kb_id,
        "filename": file.filename,
        "page_count": page_count,
        "chunk_count": chunk_count,
        "status": "success",
    }
