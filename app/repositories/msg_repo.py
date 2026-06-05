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

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        if d.get("sources"):
            try:
                d["sources"] = json.loads(d["sources"])
            except (json.JSONDecodeError, TypeError):
                d["sources"] = None
        return d
