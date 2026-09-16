import logging
from datetime import datetime, timezone

import chromadb

from app.config import settings

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    def _get_collection(self, collection_name: str):
        try:
            return self.client.get_collection(name=collection_name)
        except Exception:
            return None

    def _require_collection(self, collection_name: str):
        """Get collection or create it if missing (recovers from race-condition delete)."""
        col = self._get_collection(collection_name)
        if col is not None:
            return col
        return self.client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def get_or_create_collection(self, collection_name: str):
        try:
            return self.client.get_collection(name=collection_name)
        except Exception:
            return self.client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    def add_chunks(
        self,
        collection_name: str,
        chunks: list[str],
        embeddings: list[list[float]],
        filename: str,
        document_id: str,
        pages: list[int],
    ) -> int:
        collection = self._require_collection(collection_name)
        ids = [f"{document_id}_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "document_id": document_id,
                "filename": filename,
                "page": pages[i],
                "chunk_index": i,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(len(chunks))
        ]
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        return len(chunks)

    def query(
        self, collection_name: str, query_embedding: list[float], top_k: int
    ) -> tuple[list[str], list[dict]]:
        collection = self._get_collection(collection_name)
        if collection is None:
            return [], []
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, d in enumerate(distances):
            if metadatas and i < len(metadatas):
                metadatas[i]["relevance_score"] = round(1.0 - d, 4)
                metadatas[i]["score_type"] = "cosine"

        return documents, metadatas

    def list_documents(self, collection_name: str) -> list[dict]:
        """【当前未接入任何端点，属死代码；且 page_count 反推逻辑不可靠】

        page_count 用 max(chunk.page) + 1 反推是错的：chunk 页码本身是按位置
        线性折算的估算值，最大页码必然小于真实页数（4 个 chunk 永远算不出 100 页）。
        文档级元数据（含真实 page_count）请一律以 SQLite 的 documents 表为准，
        见 app/routers/documents.py 与 app/repositories/doc_repo.py。
        """
        collection = self._get_collection(collection_name)
        if collection is None:
            return []
        if collection.count() == 0:
            return []

        results = collection.get(include=["metadatas"])
        metadatas = results.get("metadatas", [])

        docs_map: dict[str, dict] = {}
        for m in metadatas:
            did = m["document_id"]
            if did not in docs_map:
                docs_map[did] = {
                    "document_id": did,
                    "filename": m["filename"],
                    "page_count": 0,
                    "chunk_count": 0,
                    "uploaded_at": m["uploaded_at"],
                }
            docs_map[did]["chunk_count"] += 1
            docs_map[did]["page_count"] = max(
                docs_map[did]["page_count"], m["page"] + 1
            )

        return sorted(docs_map.values(), key=lambda d: d["uploaded_at"], reverse=True)

    def delete_document(self, collection_name: str, document_id: str) -> bool:
        if not self.check_document_exists(collection_name, document_id):
            return False
        collection = self._get_collection(collection_name)
        if collection is None:
            return False
        collection.delete(where={"document_id": document_id})
        return True

    def count(self, collection_name: str) -> int:
        collection = self._get_collection(collection_name)
        if collection is None:
            return 0
        return collection.count()

    def check_document_exists(self, collection_name: str, document_id: str) -> bool:
        collection = self._get_collection(collection_name)
        if collection is None:
            return False
        results = collection.get(where={"document_id": document_id})
        return len(results["ids"]) > 0

    def delete_collection(self, collection_name: str):
        try:
            self.client.delete_collection(name=collection_name)
        except Exception as exc:
            logger.warning("delete_collection('%s') failed: %s", collection_name, exc)
