import sqlite3
import threading
from pathlib import Path

from app.config import settings

_local = threading.local()

DEFAULT_KB_ID = "default"
DEFAULT_KB_NAME = "默认知识库"


def get_db() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = Path(settings.sqlite_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def _migrate_messages_schema(conn: sqlite3.Connection):
    """Recreate messages table if CHECK constraint is outdated (missing 'tool' role)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if row and "role IN ('user', 'assistant')" in row[0]:
        conn.executescript("""
            CREATE TABLE messages_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool', 'function')),
                content TEXT NOT NULL,
                sources TEXT DEFAULT NULL,
                model TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO messages_new SELECT * FROM messages;
            DROP TABLE messages;
            ALTER TABLE messages_new RENAME TO messages;
            CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id);
        """)


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            collection_name TEXT NOT NULL UNIQUE,
            document_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            kb_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_documents_kb_id ON documents(kb_id);

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            kb_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            title TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_kb_id ON conversations(kb_id);

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool', 'function')),
            content TEXT NOT NULL,
            sources TEXT DEFAULT NULL,
            model TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id);
    """)

    # Migrate old messages table whose CHECK constraint only allows ('user','assistant')
    _migrate_messages_schema(conn)

    # Seed default knowledge base
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO knowledge_bases (id, name, description, collection_name, document_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?)",
        (DEFAULT_KB_ID, DEFAULT_KB_NAME, "系统默认知识库", f"kb_{DEFAULT_KB_ID}", now, now),
    )
    conn.commit()
