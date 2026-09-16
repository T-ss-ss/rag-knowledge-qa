import json
from datetime import datetime, timezone

from app.db.database import get_db


class MsgRepo:
    def add(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, sources_json, model, now),
        )
        conn.commit()
        return self.get(cursor.lastrowid)

    def get(self, msg_id: int) -> dict | None:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_by_conv(self, conversation_id: str) -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_recent(self, conversation_id: str, limit: int = 20) -> list[dict]:
        """Return the most recent N messages for LLM context window."""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        # Reverse to chronological order for LLM
        rows = list(reversed(rows))
        return [self._row_to_dict(r) for r in rows]

    def delete_by_conv(self, conversation_id: str) -> int:
        conn = get_db()
        cursor = conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.commit()
        return cursor.rowcount

    def count_by_conv(self, conversation_id: str) -> int:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    def save_qa_turn(
        self,
        conversation_id: str,
        question: str,
        answer: str,
        sources: list[dict] | None = None,
        model: str | None = None,
        title_hint: str = "",
        extra_message_count: int = 2,
    ) -> tuple[dict, dict]:
        """在单个事务内保存一轮问答（user + assistant），并更新会话计数与标题。

        extra_message_count 用于工具调用场景：每次工具调用额外产生 2 条占位消息。
        返回 (user_msg, assistant_msg)。
        """
        now = datetime.now(timezone.utc).isoformat()
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
        conn = get_db()

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "user", question, None, None, now),
        )
        user_msg_id = cursor.lastrowid

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "assistant", answer, sources_json, model, now),
        )
        assistant_msg_id = cursor.lastrowid

        conn.execute(
            "UPDATE conversations SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
            (extra_message_count, now, conversation_id),
        )

        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row and not row["title"] and title_hint:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title_hint, now, conversation_id),
            )

        conn.commit()
        return self.get(user_msg_id), self.get(assistant_msg_id)

    def save_assistant_turn(
        self,
        conversation_id: str,
        answer: str,
        sources: list[dict] | None = None,
        model: str | None = None,
        question: str = "",
        tool_call_count: int = 0,
    ) -> dict:
        """Agent 收尾：只写入 assistant 消息（user 消息在提问时已入库），
        并更新会话计数与标题。返回 assistant 消息。
        """
        from datetime import datetime, timezone

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        sources_json = json.dumps(sources, ensure_ascii=False) if sources else None

        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, "assistant", answer, sources_json, model, now),
        )
        msg_id = cursor.lastrowid

        # user + assistant 各 1 条，每次工具调用额外产生 2 条占位消息
        conn.execute(
            "UPDATE conversations SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
            (2 + 2 * tool_call_count, now, conversation_id),
        )

        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row and not row["title"] and question:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (question[:30], now, conversation_id),
            )

        conn.commit()
        return self.get(msg_id)

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        if d.get("sources"):
            try:
                d["sources"] = json.loads(d["sources"])
            except (json.JSONDecodeError, TypeError):
                d["sources"] = None
        return d
