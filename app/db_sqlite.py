import re
import json
import secrets
import time
from typing import Any, Dict, List, Optional
import aiosqlite


def normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class SQLiteDB:
    def __init__(self, path: str = "files.db"):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS search_sessions (
                    token TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    file_ids TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )

            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_title ON files(title)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_files_keywords ON files(keywords)")
            await db.commit()

    async def add_file(
        self,
        source_chat_id: int,
        source_message_id: int,
        title: str,
        file_type: str,
        keywords: str = "",
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO files (source_chat_id, source_message_id, title, file_type, keywords)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_chat_id, source_message_id, normalize(title), file_type, normalize(keywords)),
            )
            await db.commit()
            if cur.lastrowid is None:
                raise RuntimeError("Insert failed")
            return int(cur.lastrowid)

    async def search_file_ids(self, query: str) -> List[int]:
        q = normalize(query)
        like = f"%{q}%"

        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT id
                FROM files
                WHERE title LIKE ? OR keywords LIKE ?
                ORDER BY
                    CASE
                        WHEN title = ? THEN 0
                        WHEN title LIKE ? THEN 1
                        WHEN keywords LIKE ? THEN 2
                        ELSE 3
                    END,
                    id ASC
                """,
                (like, like, q, like, like),
            )
        return [int(r["id"]) for r in rows]

    async def get_files_by_ids(self, file_ids: List[int]) -> List[Dict[str, Any]]:
        if not file_ids:
            return []
        placeholders = ",".join(["?"] * len(file_ids))

        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                f"SELECT * FROM files WHERE id IN ({placeholders})",
                file_ids,
            )
        row_map = {int(r["id"]): dict(r) for r in rows}
        return [row_map[i] for i in file_ids if i in row_map]

    async def get_file(self, file_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM files WHERE id = ?", (file_id,))
            row = await cur.fetchone()
            await cur.close()
        return dict(row) if row else None

    # ---- Sessions (replaces Redis) ----

    async def create_search_session(self, query: str, file_ids: List[int], ttl_seconds: int = 3600) -> str:
        token = secrets.token_hex(8)
        now = int(time.time())
        payload = json.dumps(file_ids)

        async with aiosqlite.connect(self.path) as db:
            # prune old sessions
            cutoff = now - ttl_seconds
            await db.execute("DELETE FROM search_sessions WHERE created_at < ?", (cutoff,))

            await db.execute(
                "INSERT INTO search_sessions (token, query, file_ids, created_at) VALUES (?, ?, ?, ?)",
                (token, normalize(query), payload, now),
            )
            await db.commit()

        return token

    async def get_search_session(self, token: str, ttl_seconds: int = 3600) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        cutoff = now - ttl_seconds

        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            # prune old sessions
            await db.execute("DELETE FROM search_sessions WHERE created_at < ?", (cutoff,))
            await db.commit()

            cur = await db.execute(
                "SELECT token, query, file_ids, created_at FROM search_sessions WHERE token = ?",
                (token,),
            )
            row = await cur.fetchone()
            await cur.close()

        if not row:
            return None

        try:
            ids = json.loads(row["file_ids"])
            ids = [int(x) for x in ids]
        except Exception:
            return None

        return {"token": row["token"], "query": row["query"], "file_ids": ids}