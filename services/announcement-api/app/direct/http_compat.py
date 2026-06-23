from __future__ import annotations

import shutil
import subprocess
from typing import Any
from urllib.parse import urlencode


class CurlRequestError(RuntimeError):
    pass


def curl_bytes(
    url: str,
    timeout: int,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> bytes:
    executable = shutil.which("curl") or shutil.which("curl.exe")
    if not executable:
        raise CurlRequestError("curl executable is unavailable")
    target = f"{url}?{urlencode(params)}" if params else url
    command = [
        executable,
        "-sS",
        "-L",
        "--fail",
        "--compressed",
        "--max-time",
        str(max(5, timeout)),
        "-A",
        "Mozilla/5.0 youth-housing-compass",
    ]
    if data is not None:
        command.extend(["-X", "POST"])
        for key, value in data.items():
            command.extend(["--data-urlencode", f"{key}={value}"])
    command.append(target)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=max(10, timeout + 5),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CurlRequestError(type(error).__name__) from error
    if completed.returncode != 0:
        raise CurlRequestError(f"curl exit {completed.returncode}")
    return completed.stdout


def curl_text(
    url: str,
    timeout: int,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    return curl_bytes(url, timeout, params=params, data=data).decode("utf-8", errors="replace")
