from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import Response

from .service import build_source, filter_announcements
from .repository import UserRepository
from .settings import load_settings
from .sources import SourceError
from .upstream import KAptAlertClient

settings = load_settings()
source = build_source(settings)
repository = UserRepository(settings.database_path)
upstream = (
    KAptAlertClient(settings.k_apt_alert_api_base_url, settings.timeout_seconds)
    if settings.k_apt_alert_api_base_url
    else None
)

app = FastAPI(
    title="청년주거나침반 Announcement API",
    version="0.1.0",
    description="공고 소스와 청나주 웹앱 사이의 수집·정규화 경계",
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "source": source.name,
        "upstream_features": upstream is not None,
    }


def require_upstream() -> KAptAlertClient:
    if upstream is None:
        raise HTTPException(
            status_code=503,
            detail="K_APT_ALERT_API_BASE_URL이 설정되지 않아 확장 기능을 사용할 수 없습니다.",
        )
    return upstream


def upstream_call(callback):
    try:
        return callback(require_upstream())
    except SourceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.get("/v1/announcements")
def announcements(
    region: str = Query(default=""),
    status: str = Query(default=""),
    category: str = Query(default=""),
    months_back: int = Query(default=2, ge=1, le=12),
) -> dict:
    try:
        items = source.fetch(months_back=months_back)
    except SourceError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    filtered = filter_announcements(items, region, status, category)
    return {
        "count": len(filtered),
        "source": source.name,
        "announcements": [item.to_dict() for item in filtered],
    }


@app.post("/v1/eligibility/score")
def eligibility_score(payload: dict[str, Any] = Body(...)) -> dict:
    return upstream_call(lambda client: client.score(payload))


@app.post("/v1/announcements/match")
def announcement_match(payload: dict[str, Any] = Body(...)) -> dict:
    return upstream_call(lambda client: client.match(payload))


@app.get("/v1/notices/{notice_id}/raw")
def notice_raw(notice_id: str, force_refresh: bool = Query(default=False)) -> dict:
    return upstream_call(lambda client: client.notice_raw(notice_id, force_refresh))


@app.get("/v1/announcements/{announcement_id}/competition")
def competition(
    announcement_id: str,
    history: bool = Query(default=True),
) -> dict:
    return upstream_call(lambda client: client.competition(announcement_id, history))


@app.get("/v1/announcements/{announcement_id}/calendar.ics")
def calendar(announcement_id: str) -> Response:
    result = upstream_call(lambda client: client.calendar(announcement_id))
    return Response(
        content=result.content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="{announcement_id}.ics"'
        },
    )


@app.get("/v1/changes")
def changes(
    since: str = Query(default=""),
    change_type: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return upstream_call(
        lambda client: client.changes(since, change_type, limit)
    )


@app.get("/v1/users/{user_id}/profile")
def get_profile(user_id: str) -> dict:
    result = repository.get_profile(user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="저장된 프로필이 없습니다.")
    return result


@app.put("/v1/users/{user_id}/profile")
def save_profile(user_id: str, profile: dict[str, Any] = Body(...)) -> dict:
    return repository.save_profile(user_id, profile)


@app.delete("/v1/users/{user_id}/profile")
def delete_profile(user_id: str) -> dict:
    return {"deleted": repository.delete_profile(user_id)}


@app.get("/v1/users/{user_id}/favorites")
def list_favorites(user_id: str) -> dict:
    items = repository.list_favorites(user_id)
    return {"count": len(items), "favorites": items}


@app.put("/v1/users/{user_id}/favorites/{announcement_id}")
def save_favorite(
    user_id: str,
    announcement_id: str,
    announcement: dict[str, Any] = Body(...),
) -> dict:
    return repository.save_favorite(user_id, announcement_id, announcement)


@app.delete("/v1/users/{user_id}/favorites/{announcement_id}")
def delete_favorite(user_id: str, announcement_id: str) -> dict:
    return {"deleted": repository.delete_favorite(user_id, announcement_id)}

