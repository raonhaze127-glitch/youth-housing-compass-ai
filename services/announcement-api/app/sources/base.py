from __future__ import annotations

from typing import Protocol

from ..models import Announcement


class SourceError(RuntimeError):
    """공고 소스 호출 또는 정규화 실패."""


class AnnouncementSource(Protocol):
    name: str

    def fetch(self, months_back: int = 2) -> list[Announcement]: ...
