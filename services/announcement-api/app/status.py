from __future__ import annotations

from datetime import date, datetime

from .models import ApplicationStatus


def normalize_date(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) < 8:
        return ""
    candidate = digits[:8]
    try:
        return datetime.strptime(candidate, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def calculate_status(
    apply_start: str,
    apply_end: str,
    today: date | None = None,
) -> ApplicationStatus:
    start = normalize_date(apply_start)
    end = normalize_date(apply_end)
    if not start or not end:
        return "unknown"

    current = (today or date.today()).isoformat()
    if current < start:
        return "planned"
    if current > end:
        return "closed"
    return "open"
