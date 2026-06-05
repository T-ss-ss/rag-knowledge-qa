from openai import OpenAI

from app.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService
from app.services.rag_pipeline import retrieve_context, extract_summary, build_source_list


SYSTEM_PROMPT = """\
You are a precise question-answering assistant. Answer the user's question \
using ONLY the provided context below. Reply in Chinese. \
Start with a one-sentence concise summary, then provide detailed explanation. \
If the context does not contain enough information to answer the question, \
say "根据已有文档无法回答此问题。" Do not make up information.\
"""


class RAGService:
    def __init__(
        self,
        vector_store: VectorStoreService,
        embedding_service: EmbeddingService,
        collection_name: str,
    ):
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.collection_name = collection_name
        self.llm_client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = settings.chat_model

    def ask(
        self, question: str, top_k: int, temperature: float,
        rerank: bool = True, retrieval_top_k: int = 0,
    ) -> dict:
        context, sources = retrieve_context(
            self.embedding_service, self.vector_store, self.collection_name,
            question, top_k, rerank_enabled=rerank, retrieval_k=retrieval_top_k,
        )
        user_message = f"Context:\n\n{context}\n\nQuestion: {question}"

        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
        )

        answer = response.choices[0].message.content or ""

        return {
            "question": question,
            "summary": extract_summary(answer),
            "answer": answer,
            "sources": sources,
            "model_used": self.model,
        }
