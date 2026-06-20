from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any


class ChangeTracker:
    def __init__(self) -> None:
        self._previous: dict[str, dict[str, Any]] | None = None
        self._changes: list[dict[str, Any]] = []
        self._lock = Lock()

    def observe(self, announcements: list[dict[str, Any]]) -> None:
        current = {str(item.get("source_id") or item.get("id")): item for item in announcements}
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if self._previous is None:
                self._previous = current
                return
            previous = self._previous
            for item_id, item in current.items():
                if item_id not in previous:
                    self._changes.insert(0, {"id": item_id, "type": "new", "name": item.get("title"), "region": item.get("region"), "detected_at": now})
                    continue
                fields = {}
                for key in ("title", "apply_start", "apply_end", "status", "announcement_url", "total_units"):
                    if previous[item_id].get(key) != item.get(key):
                        fields[key] = {"before": previous[item_id].get(key), "after": item.get(key)}
                if fields:
                    self._changes.insert(0, {"id": item_id, "type": "updated", "name": item.get("title"), "region": item.get("region"), "detected_at": now, "field_changes": fields})
            for item_id, item in previous.items():
                if item_id not in current:
                    self._changes.insert(0, {"id": item_id, "type": "removed", "name": item.get("title"), "region": item.get("region"), "detected_at": now})
            self._changes = self._changes[:500]
            self._previous = current

    def query(self, since: str = "", change_type: str = "", limit: int = 50) -> dict[str, Any]:
        with self._lock:
            items = list(self._changes)
            initialized = self._previous is not None
        if since:
            items = [item for item in items if str(item.get("detected_at", "")) >= since]
        if change_type:
            items = [item for item in items if item.get("type") == change_type]
        return {
            "changes": items[: max(1, min(limit, 200))],
            "count": min(len(items), max(1, min(limit, 200))),
            "tracking_status": "ready" if items else "bootstrap_no_diff_yet" if initialized else "not_initialized",
            "source": "direct_memory_snapshot",
        }
