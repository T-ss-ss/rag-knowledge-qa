import pymupdf


class PDFService:
    def extract_text(self, file_bytes: bytes) -> tuple[str, int]:
        """Extract text from PDF bytes. Returns (full_text, page_count)."""
        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            from app.utils.exceptions import CorruptPDFError
            raise CorruptPDFError() from e

        pages_text: list[str] = []
        for page in doc:
            text = page.get_text()
            pages_text.append(text)

        page_count = len(pages_text)
        full_text = "\n\n".join(pages_text)
        doc.close()
        return full_text, page_count
