from __future__ import annotations

from .models import Announcement
from .settings import Settings
from .sources import AnnouncementSource, KAptAlertSource, SampleSource
from .direct import DirectAnnouncementSource


def build_source(settings: Settings) -> AnnouncementSource:
    if settings.source == "sample":
        return SampleSource(settings.sample_data_path)
    if settings.source == "k_apt_alert":
        return KAptAlertSource(
            settings.k_apt_alert_api_base_url,
            settings.timeout_seconds,
            settings.include_private_housing,
        )
    if settings.source == "direct":
        return DirectAnnouncementSource(
            settings.data_go_kr_api_key,
            settings.timeout_seconds,
            settings.direct_cache_ttl_seconds,
            settings.database_path,
            settings.direct_sync_interval_seconds,
            settings.include_private_housing,
        )
    raise ValueError(f"지원하지 않는 ANNOUNCEMENT_SOURCE입니다: {settings.source}")


def filter_announcements(
    announcements: list[Announcement],
    region: str = "",
    status: str = "",
    category: str = "",
) -> list[Announcement]:
    result = announcements
    if region:
        result = [item for item in result if item.region in {region, "전국"}]
    if status:
        result = [item for item in result if item.status == status]
    if category:
        result = [item for item in result if category in {item.category, item.housing_type}]
    return result
