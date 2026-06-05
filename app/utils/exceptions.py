from fastapi import Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, detail: str, error_code: str, status_code: int = 400):
        self.detail = detail
        self.error_code = error_code
        self.status_code = status_code


class InvalidFileTypeError(AppException):
    def __init__(self):
        super().__init__(
            detail="Only PDF and DOCX files are accepted.",
            error_code="INVALID_FILE_TYPE",
            status_code=400,
        )


class FileTooLargeError(AppException):
    def __init__(self, max_size_mb: int):
        super().__init__(
            detail=f"File exceeds {max_size_mb} MB limit.",
            error_code="FILE_TOO_LARGE",
            status_code=413,
        )


class CorruptPDFError(AppException):
    def __init__(self):
        super().__init__(
            detail="The file is not a valid PDF or is corrupted.",
            error_code="CORRUPT_PDF",
            status_code=400,
        )


class EmptyPDFError(AppException):
    def __init__(self):
        super().__init__(
            detail="No extractable text found. This PDF may be scanned/image-based.",
            error_code="EMPTY_PDF",
            status_code=400,
        )


class NoDocumentsError(AppException):
    def __init__(self):
        super().__init__(
            detail="No documents have been uploaded yet.",
            error_code="NO_DOCUMENTS",
            status_code=400,
        )


class DocumentNotFoundError(AppException):
    def __init__(self, document_id: str):
        super().__init__(
            detail=f"Document '{document_id}' not found.",
            error_code="DOCUMENT_NOT_FOUND",
            status_code=404,
        )


class KnowledgeBaseNotFoundError(AppException):
    def __init__(self, kb_id: str):
        super().__init__(
            detail=f"Knowledge base '{kb_id}' not found.",
            error_code="KB_NOT_FOUND",
            status_code=404,
        )


class KnowledgeBaseAlreadyExistsError(AppException):
    def __init__(self, name: str):
        super().__init__(
            detail=f"Knowledge base '{name}' already exists.",
            error_code="KB_ALREADY_EXISTS",
            status_code=400,
        )


class DefaultKnowledgeBaseDeleteError(AppException):
    def __init__(self):
        super().__init__(
            detail="Cannot delete the default knowledge base.",
            error_code="DEFAULT_KB_DELETE_FORBIDDEN",
            status_code=400,
        )


class RerankerNotAvailableError(AppException):
    def __init__(self):
        super().__init__(
            detail="Reranker model is not available, falling back to vector-only retrieval.",
            error_code="RERANKER_NOT_AVAILABLE",
            status_code=500,
        )


class ConversationNotFoundError(AppException):
    def __init__(self, conv_id: str):
        super().__init__(
            detail=f"Conversation '{conv_id}' not found.",
            error_code="CONVERSATION_NOT_FOUND",
            status_code=404,
        )


class EmbeddingAPIError(AppException):
    def __init__(self, detail: str = "Embedding API call failed."):
        super().__init__(
            detail=detail,
            error_code="EMBEDDING_API_ERROR",
            status_code=502,
        )


def register_exception_handlers(app):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": exc.error_code},
        )
