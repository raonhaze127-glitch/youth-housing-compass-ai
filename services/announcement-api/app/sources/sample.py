from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import Announcement
from ..status import calculate_status
from .base import SourceError


class SampleSource:
    name = "sample"

    def __init__(self, data_path: Path):
        self.data_path = data_path

    def fetch(self, months_back: int = 2) -> list[Announcement]:
        del months_back
        try:
            items = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SourceError(f"샘플 데이터를 읽지 못했습니다: {error}") from error

        fetched_at = datetime.now(timezone.utc).isoformat()
        return [self._normalize(item, fetched_at) for item in items]

    @staticmethod
    def _normalize(item: dict, fetched_at: str) -> Announcement:
        start = str(item.get("apply_start", ""))
        end = str(item.get("apply_end", ""))
        return Announcement(
            id=str(item["id"]),
            title=str(item.get("title", "")),
            organization=str(item.get("organization", "")),
            source_id=str(item["id"]),
            source_type=str(item.get("source_type", "sample")),
            category=str(item.get("housing_type", "")),
            region=str(item.get("region", "")),
            district=str(item.get("district", "")),
            housing_type=str(item.get("housing_type", "")),
            target=tuple(item.get("target", [])),
            apply_start=start,
            apply_end=end,
            status=calculate_status(start, end),
            announcement_url=str(item.get("announcement_url", "")),
            summary=str(item.get("summary", "")),
            eligibility_summary=str(item.get("eligibility_summary", "")),
            benefit_summary=str(item.get("benefit_summary", "")),
            required_documents=tuple(item.get("required_documents", [])),
            age_min=item.get("age_min"),
            age_max=item.get("age_max"),
            homeless_required=item.get("homeless_required"),
            income_condition=str(item.get("income_condition", "")),
            fetched_at=fetched_at,
            metadata={"stored_status": item.get("status")},
        )
