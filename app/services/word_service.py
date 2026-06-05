from docx import Document
from io import BytesIO


class WordService:
    def extract_text(self, file_bytes: bytes) -> tuple[str, int]:
        """Extract text from DOCX bytes. Returns (full_text, paragraph_count)."""
        try:
            doc = Document(BytesIO(file_bytes))
        except Exception as e:
            from app.utils.exceptions import CorruptPDFError
            raise CorruptPDFError() from e

        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs), len(paragraphs)
