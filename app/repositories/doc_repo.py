from datetime import datetime, timezone

from app.db.database import get_db


class DocRepo:
    def add(self, doc_id: str, kb_id: str, filename: str, page_count: int, chunk_count: int) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        conn.execute(
            "INSERT INTO documents (id, kb_id, filename, page_count, chunk_count, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, kb_id, filename, page_count, chunk_count, now),
        )
        conn.commit()
        return self.get(doc_id)

    def get(self, doc_id: str) -> dict | None:
        conn = get_db()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_by_kb(self, kb_id: str) -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM documents WHERE kb_id = ? ORDER BY uploaded_at DESC",
            (kb_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, doc_id: str, kb_id: str) -> bool:
        conn = get_db()
        cursor = conn.execute(
            "DELETE FROM documents WHERE id = ? AND kb_id = ?", (doc_id, kb_id)
        )
        conn.commit()
        return cursor.rowcount > 0

    def count_by_kb(self, kb_id: str) -> int:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE kb_id = ?", (kb_id,)
        ).fetchone()
        return row["cnt"] if row else 0
