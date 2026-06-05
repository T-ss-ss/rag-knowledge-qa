from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


class ChunkingService:
    def __init__(self):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )

    def split(self, text: str) -> list[str]:
        chunks = self.splitter.split_text(text)
        return [c for c in chunks if c.strip()]
