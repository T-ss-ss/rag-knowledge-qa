from datetime import datetime, timezone

from app.db.database import get_db


class ConvRepo:
    def create(self, conv_id: str, kb_id: str, title: str = "") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        conn.execute(
            "INSERT INTO conversations (id, kb_id, title, message_count, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (conv_id, kb_id, title, now, now),
        )
        conn.commit()
        return self.get(conv_id)

    def get(self, conv_id: str) -> dict | None:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_kb(self, kb_id: str, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        conn = get_db()
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversations WHERE kb_id = ?", (kb_id,)
        ).fetchone()["cnt"]
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT * FROM conversations WHERE kb_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (kb_id, page_size, offset),
        ).fetchall()
        return [dict(r) for r in rows], total

    def list_all(self, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        conn = get_db()
        total = conn.execute("SELECT COUNT(*) as cnt FROM conversations").fetchone()["cnt"]
        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        return [dict(r) for r in rows], total

    def update_title(self, conv_id: str, title: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, conv_id),
        )
        conn.commit()
        return self.get(conv_id)

    def delete(self, conv_id: str) -> bool:
        conn = get_db()
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        return cursor.rowcount > 0

    def increment_message_count(self, conv_id: str, delta: int = 2):
        conn = get_db()
        conn.execute(
            "UPDATE conversations SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
            (delta, datetime.now(timezone.utc).isoformat(), conv_id),
        )
        conn.commit()

    def decrement_message_count(self, conv_id: str, delta: int = 1):
        conn = get_db()
        conn.execute(
            "UPDATE conversations SET message_count = MAX(0, message_count - ?), updated_at = ? WHERE id = ?",
            (delta, datetime.now(timezone.utc).isoformat(), conv_id),
        )
        conn.commit()
