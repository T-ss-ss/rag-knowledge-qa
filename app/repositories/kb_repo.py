from datetime import datetime, timezone

from app.db.database import get_db, DEFAULT_KB_ID, DEFAULT_KB_NAME


class KBRepo:
    def create(self, kb_id: str, name: str, description: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        collection_name = f"kb_{kb_id}"
        conn = get_db()
        conn.execute(
            "INSERT INTO knowledge_bases (id, name, description, collection_name, document_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (kb_id, name, description, collection_name, now, now),
        )
        conn.commit()
        return self.get(kb_id)

    def get(self, kb_id: str) -> dict | None:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_name(self, name: str) -> dict | None:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def list_all(self) -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM knowledge_bases ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update(self, kb_id: str, name: str | None = None, description: str | None = None) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db()
        if name is not None:
            conn.execute(
                "UPDATE knowledge_bases SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, kb_id),
            )
        if description is not None:
            conn.execute(
                "UPDATE knowledge_bases SET description = ?, updated_at = ? WHERE id = ?",
                (description, now, kb_id),
            )
        conn.commit()
        return self.get(kb_id)

    def delete(self, kb_id: str) -> bool:
        conn = get_db()
        cursor = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        conn.commit()
        return cursor.rowcount > 0

    def increment_doc_count(self, kb_id: str):
        conn = get_db()
        conn.execute(
            "UPDATE knowledge_bases SET document_count = document_count + 1, updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), kb_id),
        )
        conn.commit()

    def decrement_doc_count(self, kb_id: str):
        conn = get_db()
        conn.execute(
            "UPDATE knowledge_bases SET document_count = MAX(0, document_count - 1), updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), kb_id),
        )
        conn.commit()

    def get_or_create_default(self) -> dict:
        kb = self.get(DEFAULT_KB_ID)
        if kb:
            return kb
        return self.create(DEFAULT_KB_ID, DEFAULT_KB_NAME, "系统默认知识库")
