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
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"


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
    return {
        "display_title": display_title,
        "first_author": first_author,
        "note_path": f"wiki/papers/{safe_stem(display_title, max_bytes=220)}.md",
    }


def load_config() -> Dict[str, Any]:
    config = read_json(CONFIG_PATH, None)
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid pipeline config: {CONFIG_PATH}")
    config["vault"] = Path(config["vault_path"]).expanduser().resolve()
    return config


def required_paper_skills(config: Dict[str, Any]) -> List[str]:
    values = config.get("paper_reading_skills", ["paper-reading-zh", "paperforge-vault-note"])
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
            "Run scripts/install-paperforge-skills.py from the repository root."
        )
    return skills


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


def paper_task(entry: Dict[str, Any], vault: Path) -> Optional[Dict[str, Any]]:
    source_rel = entry.get("destination", "")
    source = vault / source_rel
    if not source.is_file():
        return None
    sha256 = entry.get("sha256") or file_sha256(source)
    attachment_key = entry.get("attachment_key", "")
    parent_key = entry.get("parent_key", "") or attachment_key
    source_identity = f"paper:{attachment_key}"
    task = {
        "active_in_zotero": bool(entry.get("active", True)),
        "attempts": 0,
        "attachment_key": attachment_key,
        "created_at": now_iso(),
        "creators": entry.get("creators", []),
        "doi": entry.get("doi", ""),
        "extract_path": f"extracts/papers/{attachment_key}.md",
        "id": f"{source_identity}:{sha256[:16]}",
        "kind": "paper",
        "parent_key": parent_key,
        "sha256": sha256,
        "source_identity": source_identity,
        "source_path": source_rel,
        "status": "pending",
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


def scan_sources(config: Dict[str, Any], include_inactive: bool = False) -> int:
    vault = config["vault"]
    queue = load_queue(config)
    known = existing_task_ids(queue)
    candidates: List[Dict[str, Any]] = []

    manifest_path = vault / "sources" / "literature" / "manifests" / "zotero-doc.json"
    manifest = read_json(manifest_path, {"items": []})
    for entry in manifest.get("items", []):
        if entry.get("active", True) or include_inactive:
            task = paper_task(entry, vault)
            if task:
                candidates.append(task)

    experiment_dir = vault / "笔记" / "实验笔记"
    if experiment_dir.exists():
        for source in sorted(experiment_dir.rglob("*.md")):
            if source.name.endswith("索引.md"):
                continue
            candidates.append(experiment_task(source, vault))

    added = 0
    for candidate in candidates:
        if candidate["id"] in known:
            continue
        supersede_older(queue, candidate["source_identity"], candidate["id"])
        queue["items"].append(candidate)
        known.add(candidate["id"])
        added += 1

    if added:
        save_queue(config, queue)
    log(f"scan complete candidates={len(candidates)} added={added}")
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


def extract_pdf(config: Dict[str, Any], task: Dict[str, Any]) -> Path:
    vault = config["vault"]
    source = vault / task["source_path"]
    destination = vault / task["extract_path"]
    marker = f"source_sha256: {task['sha256']}"
    if destination.exists() and marker in destination.read_text(encoding="utf-8", errors="ignore")[:1000]:
        return destination

    fd, temp_name = tempfile.mkstemp(prefix="knowledge-extract-", suffix=".txt")
    os.close(fd)
    try:
        result = subprocess.run(
            [config["pdftotext_path"], "-layout", "-enc", "UTF-8", str(source), temp_name],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "pdftotext failed")
        raw = Path(temp_name).read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    finally:
        Path(temp_name).unlink(missing_ok=True)

    visible_chars = len(re.sub(r"\s+", "", raw))
    if visible_chars < int(config.get("minimum_extracted_characters", 1200)):
        raise ValueError(f"needs_ocr: extracted only {visible_chars} non-whitespace characters")

    pages = raw.split("\f")
    lines = [
        "---",
        "type: extracted-paper",
        f"source_pdf: \"[[{task['source_path']}]]\"",
        f"source_sha256: {task['sha256']}",
        f"attachment_key: {task.get('attachment_key', '')}",
        f"generated_at: {now_iso()}",
        "---",
        "",
        f"# {task.get('title', 'Untitled')} — 提取文本",
        "",
        "> 此文件由程序从 PDF 提取，可随时重新生成。页码标题用于知识声明溯源。",
        "",
    ]
    for page_number, page in enumerate(pages, start=1):
        page = page.strip()
        if not page:
            continue
        lines.extend([f"## Page {page_number}", "", page, ""])
    atomic_write_text(destination, "\n".join(lines).rstrip() + "\n")
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
    environment = os.environ.copy()
    proxy_url = str(config.get("proxy_url", "")).strip()
    if proxy_url:
        for key in ("all_proxy", "http_proxy", "https_proxy", "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
            environment[key] = proxy_url
        environment.setdefault("no_proxy", "localhost,127.0.0.1")
        environment.setdefault("NO_PROXY", "localhost,127.0.0.1")
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
                generated_date = task.get("generated_date") or local_date()
                task["generated_date"] = generated_date
                task.update(paper_note_identity(task, generated_date))
                save_queue(config, queue)
                extract_path = extract_pdf(config, task)
                task["extract_path"] = str(extract_path.relative_to(config["vault"]))
            workflow = config["vault"] / "system" / "workflows" / "ingest.md"
            skill_instruction = ""
            if task["kind"] == "paper":
                invocations = " and ".join(f"${name}" for name in paper_skills)
                skill_instruction = f"\nUse {invocations} for the paper analysis and vault-note mapping."
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
