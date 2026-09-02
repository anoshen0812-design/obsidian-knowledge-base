"""Minimal MinerU v4 cloud client for an Obsidian knowledge vault."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict
from urllib.request import Request, urlopen


API_BASE = "https://mineru.net/api/v4"


def _request(url: str, *, data: bytes | None = None, headers: Dict[str, str] | None = None, method: str | None = None) -> Any:
    request = Request(url, data=data, headers=headers or {}, method=method)
    with urlopen(request, timeout=120) as response:
        body = response.read()
    return json.loads(body.decode("utf-8"))


def _pick_upload_url(data: Dict[str, Any]) -> str:
    candidates = data.get("file_urls") or data.get("urls") or data.get("files") or []
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not candidates:
        raise RuntimeError("MinerU did not return an upload URL")
    first = candidates[0]
    return first if isinstance(first, str) else str(first.get("url") or first.get("upload_url") or "")


def _result_url(data: Dict[str, Any]) -> str:
    for key in ("full_zip_url", "zip_url", "result_url"):
        if data.get(key):
            return str(data[key])
    raise RuntimeError("MinerU result did not include a downloadable ZIP")


def parse_pdf(source: Path, output_dir: Path, *, model: str = "vlm", language: str = "ch", rich_content: bool = True) -> Path:
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MinerU API Key is not saved")
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "files": [{"name": source.name, "data_id": source.stem}],
        "model_version": model,
        "language": language,
        "enable_formula": rich_content,
        "enable_table": rich_content,
    }
    created = _request(f"{API_BASE}/file-urls/batch", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    if created.get("code", 0) != 0:
        raise RuntimeError(created.get("msg") or "MinerU task creation failed")
    task = created.get("data") or {}
    upload_url = _pick_upload_url(task)
    upload = subprocess.run(
        ["curl.exe", "--fail", "--silent", "--show-error", "--upload-file", str(source), upload_url],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if upload.returncode != 0:
        raise RuntimeError(upload.stderr.strip() or "MinerU PDF upload failed")
    batch_id = str(task.get("batch_id") or "")
    if not batch_id:
        raise RuntimeError("MinerU did not return a batch ID")
    deadline = time.time() + 1800
    result: Dict[str, Any] = {}
    while time.time() < deadline:
        polled = _request(f"{API_BASE}/extract-results/batch/{batch_id}", headers={"Authorization": f"Bearer {token}"})
        if polled.get("code", 0) != 0:
            raise RuntimeError(polled.get("msg") or "MinerU result query failed")
        items = (polled.get("data") or {}).get("extract_result") or (polled.get("data") or {}).get("results") or []
        result = items[0] if isinstance(items, list) and items else (polled.get("data") or {})
        state = str(result.get("state") or result.get("status") or "").lower()
        if state in {"done", "success", "completed"}:
            break
        if state in {"failed", "error"}:
            raise RuntimeError(result.get("err_msg") or result.get("message") or "MinerU parsing failed")
        time.sleep(5)
    else:
        raise RuntimeError("MinerU parsing timed out")
    zip_url = _result_url(result)
    with urlopen(zip_url, timeout=300) as response:
        archive = response.read()
    with tempfile.TemporaryDirectory(prefix="mineru-") as temp:
        zip_path = Path(temp) / "result.zip"
        zip_path.write_bytes(archive)
        with zipfile.ZipFile(zip_path) as bundle:
            bundle.extractall(temp)
        markdown = next(Path(temp).rglob("full.md"), None)
        if not markdown:
            raise RuntimeError("MinerU ZIP did not contain full.md")
        for item in markdown.parent.iterdir():
            target = output_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    return output_dir / "full.md"
