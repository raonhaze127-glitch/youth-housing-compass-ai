from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ApplicationStatus = Literal["open", "planned", "closed", "unknown"]


@dataclass(frozen=True)
class Announcement:
    id: str
    title: str
    organization: str
    source_id: str
    source_type: str
    category: str
    region: str
    district: str
    housing_type: str
    target: tuple[str, ...]
    apply_start: str
    apply_end: str
    status: ApplicationStatus
    announcement_url: str
    summary: str
    eligibility_summary: str
    benefit_summary: str
    required_documents: tuple[str, ...]
    age_min: int | None = None
    age_max: int | None = None
    homeless_required: bool | None = None
    income_condition: str = ""
    total_units: int | None = None
    fetched_at: str = ""
    schedule_confirmed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
