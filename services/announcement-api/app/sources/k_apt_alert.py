from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import Announcement
from ..status import calculate_status, normalize_date
from .base import SourceError


def _organization(item: dict) -> str:
    category = str(item.get("house_category", ""))
    item_id = str(item.get("id", ""))
    if item_id.startswith("lh_") or category.startswith("LH"):
        return "LH"
    if item_id.startswith("sh_") or category.startswith("SH"):
        return "SH"
    if item_id.startswith("gh_") or category.startswith("GH"):
        return "GH"
    return "청약홈"


def _period_start(period: object) -> str:
    text = str(period or "")
    first = text.split("~", 1)[0]
    return normalize_date(first)


def _integer(value: object) -> int | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return int(digits) if digits else None


def normalize_announcement(item: dict, fetched_at: str) -> Announcement:
    source_id = str(item.get("id", ""))
    start = _period_start(item.get("period"))
    end = normalize_date(item.get("rcept_end"))
    status = calculate_status(start, end)
    category = str(item.get("house_category", ""))
    schedule_confirmed = status != "unknown"

    return Announcement(
        id=f"kapt:{source_id}",
        title=str(item.get("name", "")),
        organization=_organization(item),
        source_id=source_id,
        source_type="k_apt_alert_proxy",
        category=category,
        region=str(item.get("region", "")),
        district=str(item.get("district", "")),
        housing_type=str(item.get("house_type", "")) or category,
        target=(),
        apply_start=start,
        apply_end=end,
        status=status,
        announcement_url=str(item.get("url", "")),
        summary="수집된 실공고입니다. 상세 내용은 원문을 확인해야 합니다.",
        eligibility_summary="자격요건 원문 분석 전으로 확인이 필요합니다.",
        benefit_summary="",
        required_documents=(),
        total_units=_integer(item.get("total_units")),
        fetched_at=fetched_at,
        schedule_confirmed=schedule_confirmed,
        metadata={
            "d_day": item.get("d_day"),
            "d_day_label": item.get("d_day_label"),
            "constructor": item.get("constructor"),
            "schedule_source": item.get("schedule_source"),
        },
    )


class KAptAlertSource:
    name = "k_apt_alert"

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        include_private_housing: bool = False,
    ):
        if not base_url:
            raise ValueError("K_APT_ALERT_API_BASE_URL이 필요합니다.")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.include_private_housing = include_private_housing

    def fetch(self, months_back: int = 2) -> list[Announcement]:
        query = urlencode(
            {
                "category": "all",
                "active_only": "false",
                "months_back": max(1, min(months_back, 12)),
            }
        )
        url = f"{self.base_url}/v1/apt/announcements?{query}"
        request = Request(url, headers={"User-Agent": "youth-housing-compass/0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SourceError(f"k-apt-alert 공고 조회에 실패했습니다: {error}") from error

        items = payload.get("announcements")
        if not isinstance(items, list):
            raise SourceError("k-apt-alert 응답에 announcements 배열이 없습니다.")

        fetched_at = str(payload.get("fetched_at") or datetime.now(timezone.utc).isoformat())
        normalized = [
            normalize_announcement(item, fetched_at) for item in items if item.get("id")
        ]
        if self.include_private_housing:
            return normalized
        return [item for item in normalized if item.organization in {"LH", "SH", "GH"}]
