from docx import Document
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

# DOCX 的正文里没有分页信息 —— 分页是排版渲染的结果，不会写进 word/document.xml。
# Word 保存文档时会把当时渲染出的页数记录在 docProps/app.xml 的 <Pages> 节点，
# 这是唯一可靠的页数来源（python-docx 不暴露，只能自己解 zip）。
_APP_XML_NAME = "docProps/app.xml"
_PAGES_TAG = "Pages"

# 页数不可知时的取值：WPS / python-docx / Google Docs 等工具生成的文件
# 可能不写 <Pages> 节点，或写入 0，此时统一返回 0 表示"未知"。
PAGE_COUNT_UNKNOWN = 0


class WordService:
    def extract_text(self, file_bytes: bytes) -> tuple[str, int]:
        """Extract text from DOCX bytes. Returns (full_text, page_count).

        page_count 来自 docProps/app.xml 的 <Pages> 节点，即 Word 最后一次
        保存时的渲染页数；读不到时返回 PAGE_COUNT_UNKNOWN(0)。

        注意两个局限：
        1. 它反映的是【保存那一刻】的页数，若文档之后被其他工具改写可能失准；
        2. 它不是段落数。此前本方法返回的是段落数，被上层当成页数使用，
           导致 202 段的文档被记为 202 页（实际 5 页）。
        """
        try:
            doc = Document(BytesIO(file_bytes))
        except Exception as e:
            from app.utils.exceptions import CorruptPDFError
            raise CorruptPDFError() from e

        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs), self._read_page_count(file_bytes)

    @staticmethod
    def _read_page_count(file_bytes: bytes) -> int:
        """从 docProps/app.xml 读取 Word 记录的渲染页数；缺失或损坏返回 0。"""
        try:
            with ZipFile(BytesIO(file_bytes)) as archive:
                raw = archive.read(_APP_XML_NAME)
        except (BadZipFile, KeyError, OSError):
            return PAGE_COUNT_UNKNOWN

        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            return PAGE_COUNT_UNKNOWN

        # 节点带 OOXML 命名空间，按 localname 匹配以兼容不同命名空间写法
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] != _PAGES_TAG:
                continue
            try:
                pages = int((node.text or "").strip())
            except ValueError:
                return PAGE_COUNT_UNKNOWN
            return pages if pages > 0 else PAGE_COUNT_UNKNOWN

        return PAGE_COUNT_UNKNOWN
