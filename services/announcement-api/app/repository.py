from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    user_id TEXT NOT NULL,
                    announcement_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, announcement_id)
                );

                """
            )

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, updated_at FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return {"profile": json.loads(row["payload"]), "updated_at": row["updated_at"]}

    def save_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        updated_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO profiles(user_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(profile, ensure_ascii=False), updated_at),
            )
        return {"profile": profile, "updated_at": updated_at}

    def delete_profile(self, user_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0

    def list_favorites(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT announcement_id, payload, created_at
                FROM favorites WHERE user_id = ? ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "announcement_id": row["announcement_id"],
                "announcement": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def save_favorite(
        self,
        user_id: str,
        announcement_id: str,
        announcement: dict[str, Any],
    ) -> dict[str, Any]:
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO favorites(user_id, announcement_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, announcement_id) DO UPDATE SET
                    payload = excluded.payload
                """,
                (
                    user_id,
                    announcement_id,
                    json.dumps(announcement, ensure_ascii=False),
                    created_at,
                ),
            )
        return {
            "announcement_id": announcement_id,
            "announcement": announcement,
            "created_at": created_at,
        }

    def delete_favorite(self, user_id: str, announcement_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM favorites WHERE user_id = ? AND announcement_id = ?",
                (user_id, announcement_id),
            )
        return cursor.rowcount > 0
