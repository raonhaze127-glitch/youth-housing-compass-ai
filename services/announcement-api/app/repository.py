from __future__ import annotations

import json
import hashlib
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


class AnnouncementRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
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
                CREATE TABLE IF NOT EXISTS announcements (
                    source_id TEXT PRIMARY KEY,
                    organization TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS announcement_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    before_payload TEXT,
                    after_payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS announcement_sync_state (
                    source TEXT PRIMARY KEY,
                    last_success_at TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    item_count INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_announcements_organization
                ON announcements(organization);

                CREATE INDEX IF NOT EXISTS idx_announcement_changes_source
                ON announcement_changes(source_id, changed_at DESC);
                """
            )

    @staticmethod
    def _content_hash(payload: dict[str, Any]) -> str:
        stable = {key: value for key, value in payload.items() if key != "fetched_at"}
        encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM announcements").fetchone()
        return int(row["count"] if row else 0)

    def list_payloads(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM announcements ORDER BY last_seen_at DESC"
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def upsert(self, payloads: list[dict[str, Any]], seen_at: str | None = None) -> dict[str, int]:
        timestamp = seen_at or _now()
        created = 0
        updated = 0
        unchanged = 0
        with self._connect() as connection:
            for payload in payloads:
                source_id = str(payload.get("source_id") or payload.get("id") or "")
                if not source_id:
                    continue
                serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                content_hash = self._content_hash(payload)
                existing = connection.execute(
                    "SELECT payload, content_hash, first_seen_at FROM announcements WHERE source_id = ?",
                    (source_id,),
                ).fetchone()
                if existing is None:
                    created += 1
                    connection.execute(
                        """
                        INSERT INTO announcements(
                            source_id, organization, payload, content_hash,
                            first_seen_at, last_seen_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            str(payload.get("organization") or ""),
                            serialized,
                            content_hash,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO announcement_changes(
                            source_id, change_type, changed_at, before_payload, after_payload
                        ) VALUES (?, 'new', ?, NULL, ?)
                        """,
                        (source_id, timestamp, serialized),
                    )
                elif existing["content_hash"] != content_hash:
                    updated += 1
                    connection.execute(
                        """
                        UPDATE announcements SET
                            organization = ?, payload = ?, content_hash = ?,
                            last_seen_at = ?, updated_at = ?
                        WHERE source_id = ?
                        """,
                        (
                            str(payload.get("organization") or ""),
                            serialized,
                            content_hash,
                            timestamp,
                            timestamp,
                            source_id,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO announcement_changes(
                            source_id, change_type, changed_at, before_payload, after_payload
                        ) VALUES (?, 'updated', ?, ?, ?)
                        """,
                        (source_id, timestamp, existing["payload"], serialized),
                    )
                else:
                    unchanged += 1
                    connection.execute(
                        "UPDATE announcements SET last_seen_at = ? WHERE source_id = ?",
                        (timestamp, source_id),
                    )
        return {"created": created, "updated": updated, "unchanged": unchanged}

    def record_sync(
        self,
        source: str,
        window_start: str,
        window_end: str,
        item_count: int,
        synced_at: str | None = None,
    ) -> None:
        timestamp = synced_at or _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO announcement_sync_state(
                    source, last_success_at, window_start, window_end, item_count
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_success_at = excluded.last_success_at,
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    item_count = excluded.item_count
                """,
                (source, timestamp, window_start, window_end, item_count),
            )

    def sync_state(self, source: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT last_success_at, window_start, window_end, item_count
                FROM announcement_sync_state WHERE source = ?
                """,
                (source,),
            ).fetchone()
        return dict(row) if row else None

    def list_changes(
        self, since: str = "", change_type: str = "", limit: int = 50
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, 200))
        clauses: list[str] = []
        parameters: list[Any] = []
        if since:
            clauses.append("changed_at >= ?")
            parameters.append(since)
        if change_type:
            clauses.append("change_type = ?")
            parameters.append(change_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT source_id, change_type, changed_at, before_payload, after_payload
                FROM announcement_changes {where}
                ORDER BY changed_at DESC, id DESC LIMIT ?
                """,
                (*parameters, bounded_limit),
            ).fetchall()
        changes = []
        for row in rows:
            after = json.loads(row["after_payload"])
            change = {
                "id": row["source_id"],
                "type": row["change_type"],
                "name": after.get("title"),
                "organization": after.get("organization"),
                "region": after.get("region"),
                "detected_at": row["changed_at"],
            }
            if row["change_type"] == "updated" and row["before_payload"]:
                before = json.loads(row["before_payload"])
                field_changes = {}
                for key in (
                    "title", "apply_start", "apply_end", "status",
                    "announcement_url", "total_units",
                ):
                    if before.get(key) != after.get(key):
                        field_changes[key] = {
                            "before": before.get(key), "after": after.get(key)
                        }
                if field_changes:
                    change["field_changes"] = field_changes
            changes.append(change)
        return {
            "changes": changes,
            "count": len(changes),
            "tracking_status": "ready" if changes else "bootstrap_no_diff_yet",
            "source": "direct_sqlite_history",
        }
