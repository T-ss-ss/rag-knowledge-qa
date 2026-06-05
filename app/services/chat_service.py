from openai import OpenAI
import json
from datetime import datetime, timezone

from app.config import settings
from app.db.database import get_db
from app.repositories.conv_repo import ConvRepo
from app.repositories.msg_repo import MsgRepo
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

MAX_HISTORY_MESSAGES = 20


class ChatService:
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
        self.conv_repo = ConvRepo()
        self.msg_repo = MsgRepo()

    def ask(
        self, conversation_id: str, question: str, top_k: int, temperature: float,
        rerank: bool = True, retrieval_top_k: int = 0,
    ) -> dict:
        conv = self.conv_repo.get(conversation_id)

        history_msgs = self.msg_repo.list_recent(conversation_id, MAX_HISTORY_MESSAGES)

        context, sources = retrieve_context(
            self.embedding_service, self.vector_store, self.collection_name,
            question, top_k, rerank_enabled=rerank, retrieval_k=retrieval_top_k,
        )

        current_user_content = f"Context:\n\n{context}\n\nQuestion: {question}"

        llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history_msgs:
            role = msg["role"]
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if role == "assistant" and content and (content.startswith("[调用工具") or content.startswith("[工具返回")):
                continue
            llm_messages.append({"role": role, "content": content})
        llm_messages.append({"role": "user", "content": current_user_content})

        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=llm_messages,
            temperature=temperature,
        )
        answer = response.choices[0].message.content or ""

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "user", question, None, None, now),
        )
        user_msg_id = cursor.lastrowid

        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "assistant", answer, sources_json, self.model, now),
        )
        assistant_msg_id = cursor.lastrowid

        conn.execute(
            "UPDATE conversations SET message_count = message_count + 2, updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )

        if not conv["title"]:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (question[:30], now, conversation_id),
            )

        conn.commit()

        user_msg = self.msg_repo.get(user_msg_id)
        assistant_msg = self.msg_repo.get(assistant_msg_id)

        return {
            "conversation_id": conversation_id,
            "user_message": user_msg,
            "assistant_message": assistant_msg,
            "answer": answer,
            "summary": extract_summary(answer),
            "sources": sources,
            "model_used": self.model,
        }
