from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import requests

SERVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.direct.http_compat import CurlRequestError, curl_bytes  # noqa: E402


DEFAULT_ARCHIVE_DIR = Path(
    os.getenv(
        "NOTICE_PDF_ARCHIVE_DIR",
        r"C:\Users\nahah\Documents\Housing-Journey-P\공고문",
    )
)
USER_AGENT = "Mozilla/5.0 youth-housing-compass"


def _read_snapshot(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    announcements = payload.get("announcements", []) if isinstance(payload, dict) else []
    if not isinstance(announcements, list):
        raise ValueError("snapshot announcements must be a list")
    return [item for item in announcements if isinstance(item, dict)]


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"processed_source_ids": [], "files": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("archive state must be an object")
    payload.setdefault("processed_source_ids", [])
    payload.setdefault("files", [])
    return payload


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _safe_name(value: str, limit: int = 90) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:limit].strip(" .") or "notice"


def _pdf_attachments(item: dict[str, Any]) -> list[str]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return []
    urls: list[str] = []
    for attachment in metadata.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        url = str(attachment.get("url") or "").strip()
        kind = str(attachment.get("type") or "").lower()
        if url and (kind == "pdf" or ".pdf" in url.lower()):
            urls.append(url)
    return list(dict.fromkeys(urls))


def _download(url: str, timeout: int) -> bytes:
    if "apply.gh.or.kr" in url:
        return curl_bytes(url, timeout)
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"},
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def _archive_item(
    item: dict[str, Any],
    archive_dir: Path,
    timeout: int,
) -> list[dict[str, str]]:
    source_id = str(item.get("source_id") or item.get("id") or "").strip()
    title = str(item.get("title") or source_id).strip()
    organization = str(item.get("organization") or "공고").strip()
    saved: list[dict[str, str]] = []
    urls = _pdf_attachments(item)
    if not source_id or not urls:
        return saved
    archive_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls, start=1):
        try:
            content = _download(url, timeout)
        except (CurlRequestError, requests.RequestException, OSError):
            continue
        if not content.startswith(b"%PDF"):
            continue
        suffix = "" if len(urls) == 1 else f"_{index}"
        filename = f"{_safe_name(organization, 12)}_{_safe_name(source_id, 40)}_{_safe_name(title)}{suffix}.pdf"
        target = archive_dir / filename
        target.write_bytes(content)
        saved.append({"source_id": source_id, "title": title, "url": url, "path": str(target)})
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=PROJECT_ROOT / "data" / "live_housing_programs.json",
    )
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--initialize-baseline",
        action="store_true",
        help="현재 스냅샷의 공고를 이미 처리된 것으로만 기록하고 PDF는 받지 않습니다.",
    )
    args = parser.parse_args()

    archive_dir = args.archive_dir
    state_path = args.state or archive_dir / ".notice_pdf_archive_state.json"
    announcements = _read_snapshot(args.snapshot)
    state = _read_state(state_path)
    processed = {str(value) for value in state.get("processed_source_ids", []) if value}
    current_ids = {
        str(item.get("source_id") or item.get("id") or "")
        for item in announcements
        if item.get("source_id") or item.get("id")
    }

    if args.initialize_baseline:
        processed.update(current_ids)
        state["processed_source_ids"] = sorted(processed)
        state["baseline_initialized_at"] = datetime.now(timezone.utc).isoformat()
        _write_state(state_path, state)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "initialize_baseline",
                    "processed_source_ids": len(processed),
                    "state": str(state_path),
                },
                ensure_ascii=False,
            )
        )
        return

    new_items = [
        item
        for item in announcements
        if str(item.get("source_id") or item.get("id") or "") not in processed
    ]
    saved_files: list[dict[str, str]] = []
    for item in new_items:
        saved_files.extend(_archive_item(item, archive_dir, max(5, args.timeout)))
        source_id = str(item.get("source_id") or item.get("id") or "")
        if source_id:
            processed.add(source_id)

    state["processed_source_ids"] = sorted(processed)
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["files"] = list(state.get("files", [])) + saved_files
    _write_state(state_path, state)
    print(
        json.dumps(
            {
                "status": "ok",
                "new_announcements": len(new_items),
                "saved_pdfs": len(saved_files),
                "archive_dir": str(archive_dir),
                "state": str(state_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
