#!/usr/bin/env python3
"""Queue, extract, draft, integrate, and lint the Obsidian knowledge base."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
PAPER_IMAGES_ROOT = Path("wiki") / "papers" / "images"
PAPER_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


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


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_text(path, content + "\n")


def append_log(path: Path, heading: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## [{now_iso()}] {heading}\n\n{body.strip()}\n")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(value: str, max_bytes: int = 160) -> str:
    value = re.sub(r"[\\/:*?\"<>|\[\]\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._") or "Untitled"
    while len(value.encode("utf-8")) > max_bytes:
        value = value[:-1]
    return value


SUBSCRIPT_TRANSLATION = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
SUPERSCRIPT_TRANSLATION = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")


def plain_title(value: Any) -> str:
    """Convert common Zotero title markup into filename- and heading-safe text."""

    text = str(value or "Untitled")
    text = re.sub(
        r"(?is)<sub>(.*?)</sub>",
        lambda match: re.sub(r"<[^>]+>", "", match.group(1)).translate(SUBSCRIPT_TRANSLATION),
        text,
    )
    text = re.sub(
        r"(?is)<sup>(.*?)</sup>",
        lambda match: re.sub(r"<[^>]+>", "", match.group(1)).translate(SUPERSCRIPT_TRANSLATION),
        text,
    )
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip() or "Untitled"


def local_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def paper_note_identity(metadata: Dict[str, Any], generated_date: str) -> Dict[str, str]:
    creators = metadata.get("creators") or []
    first_author = str(creators[0]).strip() if creators else "Unknown author"
    title = plain_title(metadata.get("title"))
    display_title = f"{generated_date} - {first_author} - {title}"
    note_stem = safe_stem(display_title, max_bytes=220)
    image_asset_subdir = (Path("images") / note_stem).as_posix()
    return {
        "display_title": display_title,
        "first_author": first_author,
        "note_path": f"wiki/papers/{note_stem}.md",
        "images_dir": (Path("wiki") / "papers" / image_asset_subdir).as_posix(),
        "image_asset_subdir": image_asset_subdir,
    }


def paper_image_identity(note_path: str) -> Dict[str, str]:
    relative_note = Path(str(note_path))
    if relative_note.parent != Path("wiki") / "papers" or relative_note.suffix.casefold() != ".md":
        raise RuntimeError(f"Paper note_path is outside wiki/papers: {note_path}")
    note_stem = relative_note.stem
    image_asset_subdir = (Path("images") / note_stem).as_posix()
    return {
        "images_dir": (relative_note.parent / image_asset_subdir).as_posix(),
        "image_asset_subdir": image_asset_subdir,
    }


def load_config() -> Dict[str, Any]:
    config = read_json(CONFIG_PATH, None)
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid pipeline config: {CONFIG_PATH}")
    config["vault"] = Path(config["vault_path"]).expanduser().resolve()
    return config


def required_paper_skills(config: Dict[str, Any]) -> List[str]:
    values = config.get("paper_reading_skills", ["forge-paper-note"])
    if not isinstance(values, list):
        raise RuntimeError("paper_reading_skills must be a JSON array")
    if not values:
        raise RuntimeError("paper_reading_skills cannot be empty")
    skills: List[str] = []
    for value in values:
        name = str(value).strip()
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise RuntimeError(f"Invalid paper-reading skill name: {name!r}")
        skills.append(name)
    return skills


def ensure_paper_skills(config: Dict[str, Any]) -> List[str]:
    skills = required_paper_skills(config)
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    missing = [name for name in skills if not (codex_home / "skills" / name / "SKILL.md").is_file()]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Missing required paper-reading skills: {joined}. "
            "Install the local Forge Paper Note skill at "
            "$CODEX_HOME/skills/forge-paper-note/SKILL.md."
        )
    return skills


def ensure_forge_python(config: Dict[str, Any]) -> str:
    configured = str(config.get("forge_python_path") or sys.executable).strip()
    interpreter = Path(configured).expanduser().resolve()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise RuntimeError(f"Forge Paper Note Python is not executable: {interpreter}")
    result = subprocess.run(
        [str(interpreter), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not inspect Forge Paper Note Python")
    match = re.fullmatch(r"(\d+)\.(\d+)", result.stdout.strip())
    if not match or (int(match.group(1)), int(match.group(2))) < (3, 10):
        raise RuntimeError(
            f"Forge Paper Note requires Python 3.10 or newer; configured interpreter is {result.stdout.strip()}"
        )
    return str(interpreter)


def paper_images_dir(config: Dict[str, Any], task: Dict[str, Any], create: bool = False) -> Path:
    """Resolve the one paper-specific image directory admitted by the task."""

    vault = config["vault"].resolve()
    raw_images_dir = str(task.get("images_dir") or "").strip()
    raw_asset_subdir = str(task.get("image_asset_subdir") or "").strip()
    note_path = Path(str(task.get("note_path") or ""))
    if not raw_images_dir or not raw_asset_subdir or not note_path.name:
        raise RuntimeError("Paper task is missing images_dir, image_asset_subdir, or note_path")

    relative = Path(raw_images_dir)
    asset_subdir = Path(raw_asset_subdir)
    if (
        relative.is_absolute()
        or asset_subdir.is_absolute()
        or ".." in relative.parts
        or ".." in asset_subdir.parts
    ):
        raise RuntimeError("Paper image paths must be safe relative paths inside the vault")

    expected_relative = note_path.parent / asset_subdir
    if relative != expected_relative:
        raise RuntimeError(
            f"Paper images_dir must equal note parent plus image_asset_subdir: {expected_relative.as_posix()}"
        )
    if relative.parent != PAPER_IMAGES_ROOT or relative.name != note_path.stem:
        raise RuntimeError(
            "Paper images must use wiki/papers/images/<exact-note-stem>/"
        )

    root = (vault / PAPER_IMAGES_ROOT).resolve()
    destination = (vault / relative).resolve()
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise RuntimeError("Paper images_dir escaped wiki/papers/images") from error
    if create:
        destination.mkdir(parents=True, exist_ok=True)
    return destination


def note_image_targets(note_text: str) -> List[str]:
    markdown = re.findall(r"!\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))", note_text)
    obsidian = re.findall(r"!\[\[([^\]|#]+)", note_text)
    targets = [left or right for left, right in markdown]
    targets.extend(obsidian)
    return [unquote(target.strip()) for target in targets if target.strip()]


def validate_paper_image_contract(config: Dict[str, Any], task: Dict[str, Any], note_text: str) -> None:
    values = yaml_frontmatter_scalars(note_text)
    expected_dir = str(task["images_dir"])
    actual_dir = unquote_yaml_scalar(values.get("images_dir", ""))
    if actual_dir != expected_dir:
        raise RuntimeError(
            f"Generated paper note images_dir does not match task metadata: {expected_dir}"
        )

    destination = paper_images_dir(config, task, create=False)
    note_parent = Path(str(task["note_path"])).parent
    expected_relative_prefix = f"{task['image_asset_subdir'].rstrip('/')}/"
    expected_vault_prefix = f"{expected_dir.rstrip('/')}/"
    managed_prefixes = ("images/", f"{PAPER_IMAGES_ROOT.as_posix()}/")
    for raw_target in note_image_targets(note_text):
        target = raw_target.split("?", 1)[0]
        if target.startswith(expected_relative_prefix):
            resolved = (config["vault"] / note_parent / target).resolve()
        elif target.startswith(expected_vault_prefix):
            resolved = (config["vault"] / target).resolve()
        elif target.startswith(managed_prefixes):
            raise RuntimeError(
                f"Paper note references another paper's managed image directory: {raw_target}"
            )
        else:
            continue
        try:
            resolved.relative_to(destination.resolve())
        except ValueError as error:
            raise RuntimeError(f"Paper image reference escaped its images_dir: {raw_target}") from error
        if not resolved.is_file():
            raise RuntimeError(f"Paper note references a missing managed image: {raw_target}")
    if not destination.exists():
        raise RuntimeError(f"Paper images_dir was not created: {expected_dir}")
    invalid = [
        path
        for path in destination.rglob("*")
        if path.is_file() and path.suffix.casefold() not in PAPER_IMAGE_EXTENSIONS
    ]
    if invalid:
        relative = invalid[0].relative_to(config["vault"]).as_posix()
        raise RuntimeError(f"Paper images_dir contains a non-image artifact: {relative}")


def queue_path(config: Dict[str, Any]) -> Path:
    return config["vault"] / "system" / "queue" / "pending.json"


def load_queue(config: Dict[str, Any]) -> Dict[str, Any]:
    queue = read_json(queue_path(config), {"schema_version": 1, "items": []})
    queue.setdefault("schema_version", 1)
    queue.setdefault("items", [])
    return queue


def save_queue(config: Dict[str, Any], queue: Dict[str, Any]) -> None:
    queue["updated_at"] = now_iso()
    atomic_write_json(queue_path(config), queue)


def existing_task_ids(queue: Dict[str, Any]) -> set:
    return {item.get("id") for item in queue["items"]}


def supersede_older(queue: Dict[str, Any], source_identity: str, current_id: str) -> None:
    for item in queue["items"]:
        if (
            item.get("source_identity") == source_identity
            and item.get("id") != current_id
            and item.get("status") in {"pending", "failed", "needs_ocr"}
        ):
            item["status"] = "superseded"
            item["updated_at"] = now_iso()


def paper_task(
    entry: Dict[str, Any],
    vault: Path,
    supporting_entry: Optional[Dict[str, Any]] = None,
    supporting_manifest_rel: str = "sources/literature/manifests/supporting-information.json",
) -> Optional[Dict[str, Any]]:
    source_rel = entry.get("destination", "")
    source = vault / source_rel
    if not source.is_file():
        return None
    sha256 = entry.get("sha256") or file_sha256(source)
    attachment_key = entry.get("attachment_key", "")
    parent_key = entry.get("parent_key", "") or attachment_key
    source_identity = f"paper:{attachment_key}"
    supporting_entry = supporting_entry or {}
    supporting_files = [
        str(item.get("destination", ""))
        for item in supporting_entry.get("files", [])
        if item.get("destination") and (vault / str(item["destination"])).is_file()
    ]
    task = {
        "active_in_zotero": bool(entry.get("active", True)),
        "attempts": 0,
        "attachment_key": attachment_key,
        "created_at": now_iso(),
        "creators": entry.get("creators", []),
        "doi": entry.get("doi", ""),
        "impact_factor": entry.get("impact_factor"),
        "impact_factor_retrieved_at": entry.get("impact_factor_retrieved_at", ""),
        "impact_factor_source": entry.get("impact_factor_source", ""),
        "impact_factor_year": entry.get("impact_factor_year", ""),
        "issn": entry.get("issn", ""),
        "journal": entry.get("journal", ""),
        "extract_path": f"extracts/papers/{attachment_key}.md",
        "id": f"{source_identity}:{sha256[:16]}",
        "kind": "paper",
        "parent_key": parent_key,
        "sha256": sha256,
        "source_identity": source_identity,
        "source_path": source_rel,
        "status": "pending",
        "supporting_information": supporting_files,
        "supporting_information_manifest": supporting_manifest_rel,
        "supporting_information_status": supporting_entry.get("status", "not_checked"),
        "title": entry.get("title", "Untitled"),
        "updated_at": now_iso(),
        "url": entry.get("url", ""),
        "year": entry.get("year", ""),
        "zotero_select": entry.get("zotero_select", ""),
    }
    # This is a planned path for queue visibility. ingest_next refreshes it with
    # the actual first generation date immediately before invoking Codex.
    task.update(paper_note_identity(task, local_date()))
    return task


def experiment_task(source: Path, vault: Path) -> Dict[str, Any]:
    source_rel = str(source.relative_to(vault))
    sha256 = file_sha256(source)
    path_key = hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:12]
    source_identity = f"experiment:{path_key}"
    return {
        "attempts": 0,
        "created_at": now_iso(),
        "id": f"{source_identity}:{sha256[:16]}",
        "kind": "experiment",
        "note_path": f"wiki/experiments/{safe_stem(source.stem)}.md",
        "sha256": sha256,
        "source_identity": source_identity,
        "source_path": source_rel,
        "status": "pending",
        "title": source.stem,
        "updated_at": now_iso(),
    }


def yaml_frontmatter_value(value: Any) -> str:
    if value is None or value == "":
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def sync_paper_metadata_frontmatter(note: Path, metadata: Dict[str, Any]) -> bool:
    """Backfill managed paper metadata without disturbing note content."""

    if not note.is_file():
        return False
    note_text = note.read_text(encoding="utf-8", errors="ignore")
    match = re.match(r"\A---\s*\n(.*?)\n---(?P<tail>\s*\n|\Z)", note_text, flags=re.DOTALL)
    if not match:
        return False
    lines = match.group(1).splitlines()
    scalar_indexes: Dict[str, int] = {}
    scalar_values: Dict[str, str] = {}
    for index, line in enumerate(lines):
        scalar = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if scalar:
            scalar_indexes[scalar.group(1)] = index
            scalar_values[scalar.group(1)] = scalar.group(2)
    if unquote_yaml_scalar(scalar_values.get("type", "")) != "paper":
        return False

    managed = (
        "images_dir",
        "journal",
        "issn",
        "impact_factor",
        "impact_factor_year",
        "impact_factor_source",
        "impact_factor_retrieved_at",
    )
    insert_at = scalar_indexes.get("year", len(lines) - 1) + 1
    changed = False
    for key in managed:
        incoming = metadata.get(key)
        has_authoritative_value = incoming is not None and incoming != ""
        if key in scalar_indexes:
            # Never erase a value merely because the current upstream record is
            # empty. This preserves a user's manually curated metadata.
            if not has_authoritative_value:
                continue
            replacement = f"{key}: {yaml_frontmatter_value(incoming)}"
            index = scalar_indexes[key]
            if lines[index] != replacement:
                lines[index] = replacement
                changed = True
            continue

        lines.insert(insert_at, f"{key}: {yaml_frontmatter_value(incoming)}")
        changed = True
        insert_at += 1
        for existing_key, index in list(scalar_indexes.items()):
            if index >= insert_at - 1:
                scalar_indexes[existing_key] = index + 1
        scalar_indexes[key] = insert_at - 1

    if not changed:
        return False
    updated_frontmatter = "\n".join(lines)
    updated = f"---\n{updated_frontmatter}\n---{match.group('tail')}{note_text[match.end():]}"
    atomic_write_text(note, updated)
    return True


def scan_sources(config: Dict[str, Any], include_inactive: bool = False) -> int:
    vault = config["vault"]
    queue = load_queue(config)
    known = existing_task_ids(queue)
    candidates: List[Dict[str, Any]] = []

    manifest_path = vault / "sources" / "literature" / "manifests" / "zotero-doc.json"
    manifest = read_json(manifest_path, {"items": []})
    supporting_manifest_rel = str(
        config.get(
            "supporting_information_manifest",
            "sources/literature/manifests/supporting-information.json",
        )
    )
    supporting_manifest_path = vault / supporting_manifest_rel
    supporting_manifest = read_json(supporting_manifest_path, {"items": []})
    supporting_by_parent = {
        str(entry.get("parent_key", "")): entry
        for entry in supporting_manifest.get("items", [])
        if entry.get("parent_key") and entry.get("active", True)
    }
    for entry in manifest.get("items", []):
        if entry.get("active", True) or include_inactive:
            task = paper_task(
                entry,
                vault,
                supporting_by_parent.get(str(entry.get("parent_key", ""))),
                supporting_manifest_rel,
            )
            if task:
                candidates.append(task)

    experiment_dir = vault / "笔记" / "实验笔记"
    if experiment_dir.exists():
        for source in sorted(experiment_dir.rglob("*.md")):
            if source.name.endswith("索引.md"):
                continue
            candidates.append(experiment_task(source, vault))

    added = 0
    refreshed = 0
    normalized = 0
    notes_refreshed = 0
    refresh_keys = (
        "impact_factor",
        "impact_factor_retrieved_at",
        "impact_factor_source",
        "impact_factor_year",
        "issn",
        "journal",
        "images_dir",
        "image_asset_subdir",
        "supporting_information",
        "supporting_information_manifest",
        "supporting_information_status",
    )
    for candidate in candidates:
        if candidate["id"] in known:
            existing = next(item for item in queue["items"] if item.get("id") == candidate["id"])
            if candidate.get("kind") == "paper":
                existing_note = vault / str(existing.get("note_path") or "")
                if existing_note.is_file():
                    candidate["note_path"] = str(existing["note_path"])
                    candidate.update(paper_image_identity(str(existing["note_path"])))
                    paper_images_dir(config, candidate, create=True)
            changed = False
            for key in refresh_keys:
                if key in candidate and existing.get(key) != candidate.get(key):
                    existing[key] = candidate[key]
                    changed = True
            if changed:
                existing["metadata_updated_at"] = now_iso()
                refreshed += 1
            if candidate.get("kind") == "paper" and existing.get("note_path"):
                note = vault / str(existing["note_path"])
                if sync_paper_metadata_frontmatter(note, candidate):
                    notes_refreshed += 1
            continue
        supersede_older(queue, candidate["source_identity"], candidate["id"])
        queue["items"].append(candidate)
        known.add(candidate["id"])
        added += 1

    # Normalize image paths for already drafted notes even when their Zotero
    # attachment is inactive and therefore absent from the current candidates.
    for existing in queue["items"]:
        if existing.get("kind") != "paper" or not existing.get("note_path"):
            continue
        note = vault / str(existing["note_path"])
        if not note.is_file():
            continue
        expected = paper_image_identity(str(existing["note_path"]))
        changed = False
        for key, value in expected.items():
            if existing.get(key) != value:
                existing[key] = value
                changed = True
        if changed:
            existing["metadata_updated_at"] = now_iso()
            normalized += 1
        paper_images_dir(config, existing, create=True)
        if sync_paper_metadata_frontmatter(note, existing):
            notes_refreshed += 1

    if added or refreshed or normalized:
        save_queue(config, queue)
    log(
        f"scan complete candidates={len(candidates)} added={added} "
        f"refreshed={refreshed} normalized={normalized} notes_refreshed={notes_refreshed}"
    )
    return added


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def pipeline_lock(config: Dict[str, Any]):
    lock_path = config["vault"] / "system" / "runtime" / "knowledge-pipeline.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            lock = read_json(lock_path, {})
            if process_exists(int(lock.get("pid", 0))):
                raise RuntimeError("knowledge pipeline is already running")
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        lock_path.unlink(missing_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started_at": now_iso()}, handle)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def configured_environment(config: Dict[str, Any]) -> Dict[str, str]:
    environment = os.environ.copy()
    proxy_url = str(config.get("proxy_url", "")).strip()
    if proxy_url:
        for key in ("all_proxy", "http_proxy", "https_proxy", "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
            environment[key] = proxy_url
        environment.setdefault("no_proxy", "localhost,127.0.0.1")
        environment.setdefault("NO_PROXY", "localhost,127.0.0.1")
    return environment


def pdf_extractor_signature(config: Dict[str, Any]) -> str:
    extractor = str(config.get("pdf_extractor", "pdftotext")).strip().casefold()
    if extractor == "mineru":
        backend = str(config.get("mineru_backend", "pipeline")).strip()
        method = str(config.get("mineru_method", "auto")).strip()
        return f"mineru:{backend}:{method}:v1"
    if extractor == "pdftotext":
        return "pdftotext:layout:v1"
    raise RuntimeError(f"Unsupported pdf_extractor: {extractor!r}")


def extracted_document(
    task: Dict[str, Any],
    pages: Iterable[tuple],
    extractor: str,
    extractor_signature: str,
) -> str:
    lines = [
        "---",
        "type: extracted-paper",
        f"source_pdf: \"[[{task['source_path']}]]\"",
        f"source_sha256: {task['sha256']}",
        f"attachment_key: {task.get('attachment_key', '')}",
        f"extractor: {extractor}",
        f"extractor_signature: {extractor_signature}",
        f"generated_at: {now_iso()}",
        "---",
        "",
        f"# {task.get('title', 'Untitled')} — 提取文本",
        "",
        "> 此文件由程序从 PDF 提取，可随时重新生成。页码标题用于知识声明溯源。",
        "",
    ]
    for page_number, page in pages:
        page = str(page).strip()
        if page:
            lines.extend([f"## Page {page_number}", "", page, ""])
    return "\n".join(lines).rstrip() + "\n"


def extract_pdf_with_pdftotext(config: Dict[str, Any], task: Dict[str, Any]) -> str:
    source = config["vault"] / task["source_path"]
    fd, temp_name = tempfile.mkstemp(prefix="knowledge-extract-", suffix=".txt")
    os.close(fd)
    try:
        result = subprocess.run(
            [config["pdftotext_path"], "-layout", "-enc", "UTF-8", str(source), temp_name],
            capture_output=True,
            text=True,
            timeout=int(config.get("pdftotext_timeout_seconds", 180)),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "pdftotext failed")
        raw = Path(temp_name).read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    finally:
        Path(temp_name).unlink(missing_ok=True)

    visible_chars = len(re.sub(r"\s+", "", raw))
    if visible_chars < int(config.get("minimum_extracted_characters", 1200)):
        raise ValueError(f"needs_ocr: pdftotext extracted only {visible_chars} non-whitespace characters")
    pages = ((page_number, page) for page_number, page in enumerate(raw.split("\f"), start=1))
    return extracted_document(task, pages, "pdftotext", "pdftotext:layout:v1")


def mineru_output_file(output_root: Path, source: Path, suffix: str) -> Path:
    preferred_name = f"{source.stem}{suffix}"
    preferred = sorted(output_root.rglob(preferred_name))
    if len(preferred) == 1:
        return preferred[0]
    candidates = sorted(output_root.rglob(f"*{suffix}"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError(f"MinerU did not produce {suffix}")
    raise RuntimeError(f"MinerU produced ambiguous {suffix} files")


def safe_mineru_asset(
    config: Dict[str, Any],
    task: Dict[str, Any],
    parse_dir: Path,
    raw_asset_path: Any,
) -> str:
    raw_value = str(raw_asset_path or "").strip()
    if not raw_value:
        return ""
    source_asset = (parse_dir / raw_value).resolve()
    parse_root = parse_dir.resolve()
    try:
        source_asset.relative_to(parse_root)
    except ValueError as error:
        raise RuntimeError(f"MinerU asset escaped its output directory: {raw_value}") from error
    if not source_asset.is_file():
        return ""

    attachment_key = safe_stem(str(task.get("attachment_key") or "paper"), max_bytes=80)
    asset_name = safe_stem(source_asset.stem, max_bytes=120) + source_asset.suffix.lower()
    relative = Path("extracts") / "papers" / "assets" / attachment_key / task["sha256"][:12] / asset_name
    destination = config["vault"] / relative
    if not destination.is_file() or file_sha256(destination) != file_sha256(source_asset):
        atomic_write_bytes(destination, source_asset.read_bytes())
    return relative.as_posix()


def mineru_caption_lines(item: Dict[str, Any], key: str) -> List[str]:
    value = item.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(entry).strip() for entry in value if str(entry).strip()]


def render_mineru_item(
    config: Dict[str, Any],
    task: Dict[str, Any],
    parse_dir: Path,
    item: Dict[str, Any],
) -> str:
    item_type = str(item.get("type", "")).casefold()
    if item_type in {"header", "footer", "page_number"}:
        return ""

    text = str(item.get("text", "")).strip()
    if item_type == "text":
        level = item.get("text_level")
        if isinstance(level, int) and level > 0:
            return f"{'#' * min(level + 2, 6)} {text}" if text else ""
        return text
    if item_type in {"equation", "interline_equation"}:
        if not text:
            return ""
        if text.startswith("$$") and text.endswith("$$"):
            return text
        return f"$$\n{text}\n$$"
    if item_type in {"list", "index"}:
        entries = item.get("list_items", [])
        if isinstance(entries, str):
            entries = [entries]
        if isinstance(entries, list):
            rendered = [f"- {str(entry).strip()}" for entry in entries if str(entry).strip()]
            return "\n".join(rendered)
        return text
    if item_type == "code":
        code = str(item.get("code_body", text)).strip()
        return f"```\n{code}\n```" if code else ""

    visual_keys = {
        "image": ("image_caption", "image_footnote"),
        "chart": ("chart_caption", "chart_footnote"),
        "table": ("table_caption", "table_footnote"),
    }
    if item_type in visual_keys:
        caption_key, footnote_key = visual_keys[item_type]
        captions = mineru_caption_lines(item, caption_key)
        footnotes = mineru_caption_lines(item, footnote_key)
        parts: List[str] = []
        if captions:
            parts.append("\n\n".join(f"**{caption}**" for caption in captions))
        if item_type == "table":
            table_body = str(item.get("table_body", "")).strip()
            if table_body:
                parts.append(table_body)
        elif item_type == "chart":
            chart_content = str(item.get("content", "")).strip()
            if chart_content:
                parts.append(chart_content)
        image_path = safe_mineru_asset(config, task, parse_dir, item.get("img_path"))
        if image_path:
            alt = captions[0].replace("[", "").replace("]", "") if captions else item_type
            parts.append(f"![{alt}]({image_path})")
        if footnotes:
            parts.append("\n".join(f"> {footnote}" for footnote in footnotes))
        return "\n\n".join(parts)

    if item_type in {"page_footnote", "aside_text"}:
        return f"> {text}" if text else ""
    return text


def extract_pdf_with_mineru(config: Dict[str, Any], task: Dict[str, Any]) -> str:
    source = config["vault"] / task["source_path"]
    backend = str(config.get("mineru_backend", "pipeline")).strip()
    method = str(config.get("mineru_method", "auto")).strip()
    command = [
        str(config["mineru_path"]),
        "-p",
        str(source),
        "-o",
        "OUTPUT_DIRECTORY",
        "-b",
        backend,
        "-m",
        method,
        "-f",
        "true" if config.get("mineru_formula", True) else "false",
        "-t",
        "true" if config.get("mineru_table", True) else "false",
    ]
    language = str(config.get("mineru_language", "")).strip()
    if language:
        command.extend(["-l", language])

    environment = configured_environment(config)
    model_source = str(config.get("mineru_model_source", "")).strip()
    if model_source:
        environment["MINERU_MODEL_SOURCE"] = model_source
    model_cache = str(config.get("mineru_model_cache", "")).strip()
    if model_cache:
        cache_root = Path(model_cache).expanduser().resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        environment["MODELSCOPE_CACHE"] = str(cache_root / "modelscope")
        environment["HF_HOME"] = str(cache_root / "huggingface")

    with tempfile.TemporaryDirectory(prefix="knowledge-mineru-") as directory:
        output_root = Path(directory) / "output"
        command[command.index("OUTPUT_DIRECTORY")] = str(output_root)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                env=environment,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=int(config.get("mineru_timeout_seconds", 1800)),
                cwd=str(config["vault"]),
            )
        except FileNotFoundError as error:
            raise RuntimeError(f"MinerU executable not found: {config['mineru_path']}") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("MinerU extraction timed out") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "MinerU failed"
            raise RuntimeError(detail[-4000:])

        content_list_path = mineru_output_file(output_root, source, "_content_list.json")
        content_list = read_json(content_list_path, None)
        if not isinstance(content_list, list):
            raise RuntimeError("MinerU content list is not a JSON array")
        parse_dir = content_list_path.parent
        pages: Dict[int, List[str]] = {}
        for item in content_list:
            if not isinstance(item, dict):
                continue
            try:
                page_number = int(item.get("page_idx")) + 1
            except (TypeError, ValueError):
                raise RuntimeError("MinerU content item is missing page_idx")
            rendered = render_mineru_item(config, task, parse_dir, item).strip()
            if rendered:
                pages.setdefault(page_number, []).append(rendered)
        page_documents = [
            (page_number, "\n\n".join(parts)) for page_number, parts in sorted(pages.items())
        ]
        markdown = extracted_document(
            task,
            page_documents,
            "mineru",
            pdf_extractor_signature(config),
        )

    visible_chars = len(re.sub(r"\s+", "", "\n".join(text for _, text in page_documents)))
    if visible_chars < int(config.get("minimum_extracted_characters", 1200)):
        raise ValueError(f"needs_ocr: MinerU extracted only {visible_chars} non-whitespace characters")
    return markdown


def extract_pdf(config: Dict[str, Any], task: Dict[str, Any]) -> Path:
    vault = config["vault"]
    destination = vault / task["extract_path"]
    marker = f"source_sha256: {task['sha256']}"
    signature = pdf_extractor_signature(config)
    signature_marker = f"extractor_signature: {signature}"
    if destination.exists():
        head = destination.read_text(encoding="utf-8", errors="ignore")[:1500]
        if marker in head and signature_marker in head:
            return destination

    extractor = str(config.get("pdf_extractor", "pdftotext")).strip().casefold()
    if extractor == "mineru":
        try:
            markdown = extract_pdf_with_mineru(config, task)
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as mineru_error:
            if not config.get("mineru_fallback_to_pdftotext", True):
                raise
            log(f"MinerU extraction failed; falling back to pdftotext: {mineru_error}")
            try:
                markdown = extract_pdf_with_pdftotext(config, task)
            except ValueError as fallback_error:
                raise ValueError(f"needs_ocr: MinerU failed ({mineru_error}); {fallback_error}") from fallback_error
    else:
        markdown = extract_pdf_with_pdftotext(config, task)
    atomic_write_text(destination, markdown)
    return destination


def codex_command(config: Dict[str, Any], prompt: str, result_name: str) -> subprocess.CompletedProcess:
    vault = config["vault"]
    schema_path = SCRIPT_DIR / "result.schema.json"
    result_path = vault / "system" / "runtime" / f"{result_name}.json"
    command = [
        config["codex_path"],
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(vault),
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-schema",
        str(schema_path),
        "-o",
        str(result_path),
        prompt,
    ]
    environment = configured_environment(config)
    return subprocess.run(
        command,
        capture_output=True,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=int(config.get("codex_timeout_seconds", 1200)),
        cwd=str(vault),
    )


def write_run_log(config: Dict[str, Any], operation: str, source_id: str, result: subprocess.CompletedProcess) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)
    path = config["vault"] / "system" / "knowledge" / "logs" / f"{stamp}-{operation}-{safe_id}.log"
    content = "\n".join(
        [
            f"operation={operation}",
            f"source_id={source_id}",
            f"returncode={result.returncode}",
            "",
            "--- stdout ---",
            result.stdout or "",
            "",
            "--- stderr ---",
            result.stderr or "",
        ]
    )
    atomic_write_text(path, content)
    return path


def set_task_failure(task: Dict[str, Any], error: str, status: str = "failed") -> None:
    task["attempts"] = int(task.get("attempts", 0)) + 1
    task["last_error"] = error[-4000:]
    task["status"] = status
    task["updated_at"] = now_iso()


def yaml_frontmatter_scalars(note_text: str) -> Dict[str, str]:
    """Read top-level scalar text without depending on a YAML package."""

    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", note_text, flags=re.DOTALL)
    if not match:
        return {}
    values: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        scalar = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if scalar:
            values[scalar.group(1)] = scalar.group(2)
    return values


def unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def validate_impact_factor_properties(note_text: str, task: Dict[str, Any]) -> None:
    values = yaml_frontmatter_scalars(note_text)
    required = (
        "impact_factor",
        "impact_factor_year",
        "impact_factor_source",
        "impact_factor_retrieved_at",
    )
    missing = [key for key in required if key not in values]
    if missing:
        raise RuntimeError(f"Generated paper note is missing properties: {', '.join(missing)}")

    expected_factor = task.get("impact_factor")
    actual_factor = unquote_yaml_scalar(values["impact_factor"])
    null_values = {"", "null", "~"}
    if expected_factor is None:
        if actual_factor.casefold() not in null_values:
            raise RuntimeError("Generated paper note invented an impact factor absent from task metadata")
    else:
        try:
            if float(actual_factor) != float(expected_factor):
                raise RuntimeError("Generated paper note impact_factor does not match task metadata")
        except ValueError as error:
            raise RuntimeError("Generated paper note impact_factor is not numeric") from error

    for key in ("impact_factor_year", "impact_factor_source", "impact_factor_retrieved_at"):
        expected = str(task.get(key) or "")
        actual = unquote_yaml_scalar(values[key])
        if expected:
            if actual != expected:
                raise RuntimeError(f"Generated paper note {key} does not match task metadata")
        elif actual.casefold() not in null_values:
            raise RuntimeError(f"Generated paper note invented {key} absent from task metadata")


def ingest_next(config: Dict[str, Any]) -> int:
    with pipeline_lock(config):
        queue = load_queue(config)
        task = next((item for item in queue["items"] if item.get("status") == "pending"), None)
        if not task:
            log("ingest: no pending task")
            return 0

        log(f"ingest start id={task['id']} kind={task['kind']}")
        try:
            if task["kind"] == "paper":
                paper_skills = ensure_paper_skills(config)
                task["forge_python_path"] = ensure_forge_python(config)
                generated_date = task.get("generated_date") or local_date()
                task["generated_date"] = generated_date
                task.update(paper_note_identity(task, generated_date))
                paper_images_dir(config, task, create=True)
                save_queue(config, queue)
                extract_path = extract_pdf(config, task)
                task["extract_path"] = str(extract_path.relative_to(config["vault"]))
            workflow = config["vault"] / "system" / "workflows" / "ingest.md"
            skill_instruction = ""
            if task["kind"] == "paper":
                invocations = " and ".join(f"${name}" for name in paper_skills)
                skill_instruction = (
                    f"\nUse {invocations} for the complete paper analysis, figure review, "
                    "quality gates, and vault-note mapping. Store every selected or cropped "
                    "note image only in TASK_JSON.images_dir, pass TASK_JSON.image_asset_subdir "
                    "to figure materialization, use TASK_JSON.forge_python_path for every bundled "
                    "Forge Python script, and embed images with vault-relative Obsidian links."
                )
            prompt = (
                "执行知识库的单一来源摄取任务。严格读取并遵守 AGENTS.md 与 "
                f"{workflow.relative_to(config['vault'])}。只处理下面 JSON 指定的一个任务；"
                "不得处理队列中的其他项目，不得修改 sources/ 或 笔记/实验笔记/，也不得修改队列文件。"
                f"{skill_instruction}\n\n"
                f"TASK_JSON:\n{json.dumps(task, ensure_ascii=False, indent=2)}"
            )
            result = codex_command(config, prompt, f"last-ingest-{safe_stem(task['id'])}")
            run_log = write_run_log(config, "ingest", task["id"], result)
            note = config["vault"] / task["note_path"]
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Codex ingest failed")
            source_after = config["vault"] / task["source_path"]
            if not source_after.is_file() or file_sha256(source_after) != task["sha256"]:
                raise RuntimeError(f"Source-of-truth file changed during ingest: {task['source_path']}")
            if not note.is_file():
                raise RuntimeError(f"Codex did not create {task['note_path']}")
            note_text = note.read_text(encoding="utf-8", errors="ignore")
            note_head = note_text[:2000]
            if not re.search(r"(?m)^status:\s*['\"]?draft['\"]?\s*$", note_head):
                raise RuntimeError(f"Generated note is not marked status: draft: {task['note_path']}")
            if task["kind"] == "paper":
                validate_impact_factor_properties(note_text, task)
                validate_paper_image_contract(config, task, note_text)
                expected_heading = f"# {task['display_title']}"
                if not re.search(rf"(?m)^{re.escape(expected_heading)}\s*$", note_text):
                    raise RuntimeError(
                        f"Generated note title does not match '{task['display_title']}': {task['note_path']}"
                    )
                index_text = (config["vault"] / "wiki" / "index.md").read_text(
                    encoding="utf-8", errors="ignore"
                )
                targets = [task["note_path"], task["note_path"].removesuffix(".md")]
                matching_links = sum(
                    index_text.count(f"[[{target}|{task['display_title']}]]") for target in targets
                )
                if matching_links != 1:
                    raise RuntimeError(
                        f"Draft index must contain exactly one matching title link: {task['note_path']}"
                    )

            task["attempts"] = int(task.get("attempts", 0)) + 1
            task["completed_at"] = now_iso()
            task["last_run_log"] = str(run_log.relative_to(config["vault"]))
            task["status"] = "drafted"
            task["updated_at"] = now_iso()
            save_queue(config, queue)
            append_log(
                config["vault"] / "system" / "ingest-log.md",
                f"draft | {task.get('title', task['id'])}",
                f"- Source: `[[{task['source_path']}]]`\n- Draft: `[[{task['note_path']}]]`\n- Task: `{task['id']}`",
            )
            log(f"ingest complete note={task['note_path']}")
            return 0
        except ValueError as error:
            status = "needs_ocr" if str(error).startswith("needs_ocr:") else "failed"
            set_task_failure(task, str(error), status=status)
            save_queue(config, queue)
            log(f"ingest stopped id={task['id']} status={status} error={error}")
            return 2
        except Exception as error:
            set_task_failure(task, str(error))
            save_queue(config, queue)
            log(f"ingest failed id={task['id']} error={error}")
            return 1


def note_status(path: Path) -> str:
    head = path.read_text(encoding="utf-8", errors="ignore")[:3000]
    match = re.search(r"(?m)^status:\s*['\"]?([^'\"\n]+)['\"]?\s*$", head)
    return match.group(1).strip() if match else ""


def integrate_note(config: Dict[str, Any], note_rel: str) -> int:
    with pipeline_lock(config):
        vault = config["vault"]
        note = (vault / note_rel).resolve()
        if not note.is_relative_to(vault.resolve()):
            raise RuntimeError("Note must be inside the vault")
        relative = str(note.relative_to(vault))
        if not (relative.startswith("wiki/papers/") or relative.startswith("wiki/experiments/")):
            raise RuntimeError("Only paper or experiment draft notes can be integrated")
        if not note.is_file() or note_status(note) != "reviewed":
            raise RuntimeError("The note must exist and have status: reviewed")

        queue = load_queue(config)
        matching = [item for item in queue["items"] if item.get("note_path") == relative]
        task = matching[-1] if matching else {"id": relative, "title": note.stem, "note_path": relative}
        workflow = vault / "system" / "workflows" / "integrate.md"
        prompt = (
            "执行已审核知识笔记的整合任务。严格读取并遵守 AGENTS.md 与 "
            f"{workflow.relative_to(vault)}。只整合指定笔记，保留来源和页码，不得修改原始资料。\n\n"
            f"NOTE_PATH: {relative}\nTASK_JSON:\n{json.dumps(task, ensure_ascii=False, indent=2)}"
        )
        result = codex_command(config, prompt, f"last-integrate-{safe_stem(task['id'])}")
        run_log = write_run_log(config, "integrate", task["id"], result)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Codex integration failed")
        if task.get("source_path") and task.get("sha256"):
            source_after = vault / task["source_path"]
            if not source_after.is_file() or file_sha256(source_after) != task["sha256"]:
                raise RuntimeError(f"Source-of-truth file changed during integration: {task['source_path']}")
        if note_status(note) != "integrated":
            raise RuntimeError("Integrated note was not marked status: integrated")

        if matching:
            task["integrated_at"] = now_iso()
            task["last_run_log"] = str(run_log.relative_to(vault))
            task["status"] = "integrated"
            task["updated_at"] = now_iso()
            save_queue(config, queue)
        append_log(
            vault / "system" / "ingest-log.md",
            f"integrate | {task.get('title', note.stem)}",
            f"- Note: `[[{relative}]]`\n- Task: `{task['id']}`",
        )
        log(f"integration complete note={relative}")
        return 0


def lint_wiki(config: Dict[str, Any]) -> int:
    with pipeline_lock(config):
        vault = config["vault"]
        report_rel = f"system/reports/{datetime.now().strftime('%Y-%m-%d')}-wiki-health.md"
        workflow = vault / "system" / "workflows" / "lint.md"
        prompt = (
            "执行知识库健康检查。严格读取并遵守 AGENTS.md 与 "
            f"{workflow.relative_to(vault)}。本次只生成或更新报告 {report_rel}；"
            "不要自动解决科学矛盾，不要修改原始资料。"
        )
        result = codex_command(config, prompt, "last-lint")
        write_run_log(config, "lint", datetime.now().strftime("%Y-%m-%d"), result)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Codex lint failed")
        if not (vault / report_rel).is_file():
            raise RuntimeError(f"Codex did not create {report_rel}")
        append_log(vault / "system" / "lint-log.md", "wiki health check", f"- Report: `[[{report_rel}]]`")
        log(f"lint complete report={report_rel}")
        return 0


def retry_failed(config: Dict[str, Any]) -> int:
    queue = load_queue(config)
    task = next((item for item in queue["items"] if item.get("status") == "failed"), None)
    if not task:
        log("retry: no failed task")
        return 0
    task["status"] = "pending"
    task["updated_at"] = now_iso()
    task.pop("last_error", None)
    save_queue(config, queue)
    log(f"retry queued id={task['id']}")
    return 0


def show_status(config: Dict[str, Any]) -> int:
    queue = load_queue(config)
    counts: Dict[str, int] = {}
    for item in queue["items"]:
        status = item.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"counts": counts, "total": len(queue["items"])}, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="Queue new or changed sources")
    scan_parser.add_argument("--include-inactive", action="store_true")
    subparsers.add_parser("ingest-next", help="Draft the oldest pending source")
    integrate_parser = subparsers.add_parser("integrate", help="Integrate one reviewed draft")
    integrate_parser.add_argument("--note", required=True)
    subparsers.add_parser("lint", help="Generate a wiki health report")
    subparsers.add_parser("retry-failed", help="Retry the oldest failed task")
    subparsers.add_parser("status", help="Print queue counts")
    args = parser.parse_args()

    config = load_config()
    try:
        if args.command == "scan":
            scan_sources(config, include_inactive=args.include_inactive)
            return 0
        if args.command == "ingest-next":
            return ingest_next(config)
        if args.command == "integrate":
            return integrate_note(config, args.note)
        if args.command == "lint":
            return lint_wiki(config)
        if args.command == "retry-failed":
            return retry_failed(config)
        if args.command == "status":
            return show_status(config)
        return 2
    except RuntimeError as error:
        log(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
