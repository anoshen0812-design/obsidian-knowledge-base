#!/usr/bin/env python3
"""Mirror PDF attachments from one Zotero collection into an Obsidian vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote, unquote, urlparse
from urllib.request import ProxyHandler, Request, build_opener


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"
OPENER = build_opener(ProxyHandler({}))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"[{now_iso()}] {message}", flush=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_bytes(path, (content + "\n").encode("utf-8"))


def api_get(api_base: str, path: str, accept: str = "application/json") -> bytes:
    request = Request(
        f"{api_base.rstrip('/')}/{path.lstrip('/')}",
        headers={
            "Accept": accept,
            "Connection": "close",
            "Zotero-API-Version": "3",
        },
    )
    with OPENER.open(request, timeout=15) as response:
        return response.read()


def api_json(api_base: str, path: str) -> Any:
    return json.loads(api_get(api_base, path).decode("utf-8"))


def resolve_collection(api_base: str, configured_name: str, configured_key: str) -> str:
    collections = api_json(api_base, "users/0/collections?format=json")
    for collection in collections:
        if collection.get("key") == configured_key and collection.get("data", {}).get("name") == configured_name:
            return configured_key

    matches = [
        collection.get("key")
        for collection in collections
        if collection.get("data", {}).get("name") == configured_name
    ]
    matches = [key for key in matches if key]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one Zotero collection named {configured_name!r}; found {len(matches)}"
        )
    return matches[0]


def safe_filename(source_name: str, attachment_key: str) -> str:
    stem = Path(source_name).stem or "document"
    stem = re.sub(r"[\\/:*?\"<>|\[\]\x00-\x1f]", "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._")
    stem = stem or "document"
    suffix = f" ({attachment_key}).pdf"
    while len((stem + suffix).encode("utf-8")) > 220 and stem:
        stem = stem[:-1]
    return stem.rstrip(" ._") + suffix


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path_for_attachment(api_base: str, attachment_key: str) -> Path:
    payload = api_get(
        api_base,
        f"users/0/items/{quote(attachment_key)}/file/view/url",
        accept="text/plain",
    ).decode("utf-8").strip()
    parsed = urlparse(payload)
    if parsed.scheme != "file":
        raise RuntimeError(f"Attachment {attachment_key} did not resolve to a local file")
    return Path(unquote(parsed.path))


def parent_title(parent: Dict[str, Any]) -> str:
    return str(parent.get("data", {}).get("title") or "Untitled")


def parent_year(parent: Dict[str, Any]) -> str:
    date = str(parent.get("data", {}).get("date") or "")
    match = re.search(r"\b(19|20)\d{2}\b", date)
    return match.group(0) if match else ""


def creator_names(parent: Dict[str, Any]) -> List[str]:
    result: List[str] = []
    for creator in parent.get("data", {}).get("creators", []):
        name = creator.get("name") or " ".join(
            part for part in [creator.get("firstName", ""), creator.get("lastName", "")] if part
        )
        if name:
            result.append(name)
    return result


def archive_previous(destination: Path, history_dir: Path, previous_sha: str) -> None:
    if not destination.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archived = history_dir / f"{destination.stem}__{stamp}__{previous_sha[:8] or 'unknown'}.pdf"
    history_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, archived)


def copy_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    os.close(fd)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_index(entries: Iterable[Dict[str, Any]], synced_at: str) -> str:
    lines = [
        "# Zotero Doc 文献索引",
        "",
        "> 此文件由同步程序自动生成，请勿手工编辑。",
        "",
        f"最后同步：`{synced_at}`",
        "",
        "| 文献 | 年份 | 作者 | PDF | Zotero |",
        "|---|---:|---|---|---|",
    ]
    for entry in sorted(entries, key=lambda item: (item.get("year", ""), item.get("title", "")), reverse=True):
        title = markdown_escape(entry.get("title", "Untitled"))
        year = markdown_escape(entry.get("year", ""))
        authors = markdown_escape("、".join(entry.get("creators", [])[:3]))
        relative_pdf = entry["destination"]
        pdf_link = f"[[{relative_pdf}|PDF]]"
        zotero_link = f"[打开](zotero://select/library/items/{entry['parent_key']})"
        lines.append(f"| {title} | {year} | {authors} | {pdf_link} | {zotero_link} |")
    lines.append("")
    return "\n".join(lines)


def scan_knowledge_queue(vault: Path) -> None:
    runner = vault / "system" / "knowledge" / "run_pipeline.py"
    if not runner.is_file():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(runner), "scan"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(vault),
        )
        if result.stdout.strip():
            log(result.stdout.strip())
        if result.returncode != 0:
            log(f"knowledge queue scan failed: {result.stderr.strip() or result.returncode}")
    except Exception as error:
        log(f"knowledge queue scan skipped: {error}")


def sync(config_path: Path) -> int:
    config = read_json(config_path, None)
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid config: {config_path}")

    api_base = str(config["api_base"])
    collection_name = str(config["collection_name"])
    collection_key = resolve_collection(api_base, collection_name, str(config["collection_key"]))
    vault = Path(config["vault_path"]).expanduser().resolve()
    literature_dir = vault / config["literature_dir"]
    pdf_dir = literature_dir / "pdf"
    history_dir = literature_dir / "history"
    manifest_path = literature_dir / "manifests" / "zotero-doc.json"
    state_path = SCRIPT_DIR / "state.json"
    index_path = literature_dir / "index.md"
    bib_path = literature_dir / "references.bib"

    state = read_json(state_path, {"attachments": {}})
    state.setdefault("attachments", {})
    items = api_json(
        api_base,
        f"users/0/collections/{quote(collection_key)}/items?format=json&include=data",
    )
    parents = {
        item["key"]: item
        for item in items
        if item.get("data", {}).get("itemType") != "attachment"
    }
    attachments = [
        item
        for item in items
        if item.get("data", {}).get("itemType") == "attachment"
        and item.get("data", {}).get("contentType") == "application/pdf"
    ]

    synced_at = now_iso()
    active_entries: List[Dict[str, Any]] = []
    copied = 0
    unchanged = 0
    failed = 0
    changed = not state_path.exists() or not manifest_path.exists() or not index_path.exists() or not bib_path.exists()
    active_keys = set()

    for attachment in attachments:
        attachment_key = attachment["key"]
        active_keys.add(attachment_key)
        data = attachment.get("data", {})
        parent_key = data.get("parentItem", "")
        parent = parents.get(parent_key, {})
        previous = state["attachments"].get(attachment_key, {})
        try:
            source = source_path_for_attachment(api_base, attachment_key)
            if not source.is_file():
                raise FileNotFoundError(source)

            destination_name = previous.get("destination_name") or safe_filename(
                data.get("filename") or source.name,
                attachment_key,
            )
            destination = pdf_dir / destination_name
            source_fingerprint = data.get("md5") or f"{source.stat().st_size}:{source.stat().st_mtime_ns}"
            needs_copy = not destination.exists() or previous.get("source_fingerprint") != source_fingerprint

            if needs_copy:
                if destination.exists():
                    archive_previous(destination, history_dir, previous.get("sha256", ""))
                copy_atomically(source, destination)
                sha256 = file_sha256(destination)
                copied += 1
                log(f"copied {attachment_key}: {destination.name}")
            else:
                sha256 = previous.get("sha256") or file_sha256(destination)
                unchanged += 1

            entry = {
                "active": True,
                "attachment_key": attachment_key,
                "attachment_version": attachment.get("version"),
                "content_type": data.get("contentType"),
                "creators": creator_names(parent),
                "destination": str(destination.relative_to(vault)),
                "destination_name": destination_name,
                "doi": parent.get("data", {}).get("DOI", ""),
                "parent_key": parent_key,
                "sha256": sha256,
                "source_filename": data.get("filename") or source.name,
                "source_fingerprint": source_fingerprint,
                "synced_at": previous.get("synced_at", synced_at),
                "title": parent_title(parent),
                "url": parent.get("data", {}).get("url", ""),
                "year": parent_year(parent),
                "zotero_select": f"zotero://select/library/items/{parent_key}",
            }
            comparable_keys = [key for key in entry if key != "synced_at"]
            entry_changed = needs_copy or any(previous.get(key) != entry.get(key) for key in comparable_keys)
            if entry_changed:
                entry["synced_at"] = synced_at
                changed = True
            state["attachments"][attachment_key] = entry
            active_entries.append(entry)
        except Exception as error:
            failed += 1
            log(f"failed {attachment_key}: {error}")

    for key, entry in state["attachments"].items():
        if key not in active_keys:
            if entry.get("active", True):
                changed = True
            entry["active"] = False

    state.update(
        {
            "collection_key": collection_key,
            "collection_name": collection_name,
            "last_sync": synced_at,
            "schema_version": 1,
        }
    )
    manifest = {
        "collection_key": collection_key,
        "collection_name": collection_name,
        "generated_at": synced_at,
        "items": sorted(state["attachments"].values(), key=lambda item: item.get("attachment_key", "")),
        "schema_version": 1,
    }

    bibliography = api_get(
        api_base,
        f"users/0/collections/{quote(collection_key)}/items?format=bibtex",
        accept="application/x-bibtex",
    )
    if not bib_path.exists() or bib_path.read_bytes() != bibliography:
        changed = True

    if changed:
        atomic_write_bytes(bib_path, bibliography)
        atomic_write_bytes(index_path, build_index(active_entries, synced_at).encode("utf-8"))
        atomic_write_json(manifest_path, manifest)
        atomic_write_json(state_path, state)
    scan_knowledge_queue(vault)
    log(
        f"complete collection={collection_name!r} PDFs={len(attachments)} "
        f"copied={copied} unchanged={unchanged} failed={failed} wrote={str(changed).lower()}"
    )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        return sync(args.config.resolve())
    except Exception as error:
        log(f"sync skipped: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
