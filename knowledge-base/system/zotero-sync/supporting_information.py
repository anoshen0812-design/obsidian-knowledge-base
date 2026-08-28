#!/usr/bin/env python3
"""Discover and cache PDF supporting information for Zotero papers.

The module deliberately keeps supporting files separate from primary paper PDFs.
It accepts Zotero child attachments, structured Figshare records, and explicit
supporting-information links on publisher landing pages. Every downloaded file
must pass a PDF-magic check and is recorded with provenance in a manifest.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


USER_AGENT = "ObsidianKnowledgeBase/1.0 (+local Zotero supporting-information sync)"
PDF_CONTENT_TYPES = {"application/pdf", "application/octet-stream", "binary/octet-stream"}
SUPPORTING_PHRASES = (
    "supporting information",
    "supplementary information",
    "supporting material",
    "supplementary material",
    "electronic supplementary material",
    "supplemental information",
    "supplemental material",
)
REJECT_PHRASES = (
    "peer review",
    "review file",
    "reporting summary",
    "editor decision",
    "author response",
    "source data",
)
SUPPORTING_FILENAME_PATTERNS = (
    re.compile(r"(?:^|[_\-.])si(?:[_\-.]|\d)", re.IGNORECASE),
    re.compile(r"(?:supp|suppl|supporting|supplementary)", re.IGNORECASE),
    re.compile(r"(?:^|[_\-.])mmc\d+", re.IGNORECASE),
    re.compile(r"(?:^|[_\-.])moesm\d+", re.IGNORECASE),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


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
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, content.encode("utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"(?i)^doi:\s*", "", doi).strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        return ""
    return doi.rstrip(".,;)").lower()


def safe_component(value: Any, fallback: str = "supporting-information", max_bytes: int = 180) -> str:
    text = Path(str(value or fallback)).name
    text = re.sub(r"[\\/:*?\"<>|\[\]\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._") or fallback
    while len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
    return text


def supporting_filename(source_name: Any, source_id: str) -> str:
    name = safe_component(source_name)
    stem = Path(name).stem or "supporting-information"
    suffix = f" ({safe_component(source_id, 'source', 60)}).pdf"
    while len((stem + suffix).encode("utf-8")) > 220 and stem:
        stem = stem[:-1]
    return stem.rstrip(" ._") + suffix


def _attachment_text(data: Dict[str, Any]) -> str:
    tags = " ".join(str(tag.get("tag", "")) for tag in data.get("tags", []) if isinstance(tag, dict))
    return " ".join(
        str(data.get(key, "")) for key in ("title", "filename", "note")
    ) + " " + tags


def looks_like_supporting_filename(value: Any) -> bool:
    name = unquote(str(value or ""))
    return any(pattern.search(name) for pattern in SUPPORTING_FILENAME_PATTERNS)


def is_supplementary_pdf_attachment(item: Dict[str, Any]) -> bool:
    data = item.get("data", {})
    if data.get("itemType") != "attachment" or data.get("contentType") != "application/pdf":
        return False
    text = html.unescape(_attachment_text(data)).lower()
    if any(phrase in text for phrase in REJECT_PHRASES):
        return False
    return any(phrase in text for phrase in SUPPORTING_PHRASES) or looks_like_supporting_filename(text)


def is_auxiliary_pdf_attachment(item: Dict[str, Any]) -> bool:
    """Return true for SI and non-paper PDFs that must not enter the paper queue."""

    data = item.get("data", {})
    if data.get("itemType") != "attachment" or data.get("contentType") != "application/pdf":
        return False
    text = html.unescape(_attachment_text(data)).lower()
    return is_supplementary_pdf_attachment(item) or any(phrase in text for phrase in REJECT_PHRASES)


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"unsupported URL: {url}")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("local network URL rejected")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("non-public URL rejected")


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, timeout_seconds: int, proxy_url: str = "") -> None:
        handlers: List[Any] = [SafeRedirectHandler()]
        if proxy_url:
            handlers.insert(0, ProxyHandler({"http": proxy_url, "https": proxy_url}))
        self.opener = build_opener(*handlers)
        self.timeout_seconds = timeout_seconds

    def get(self, url: str, max_bytes: int, accept: str = "*/*") -> Tuple[bytes, str, Dict[str, str]]:
        return self.request(url, max_bytes=max_bytes, accept=accept)

    def post_json(self, url: str, payload: Dict[str, Any], max_bytes: int) -> Tuple[bytes, str, Dict[str, str]]:
        return self.request(
            url,
            max_bytes=max_bytes,
            accept="application/json",
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )

    def request(
        self,
        url: str,
        max_bytes: int,
        accept: str,
        data: Optional[bytes] = None,
        content_type: str = "",
    ) -> Tuple[bytes, str, Dict[str, str]]:
        _validate_public_url(url)
        headers = {"Accept": accept, "User-Agent": USER_AGENT, "Connection": "close"}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            final_url = response.geturl()
            _validate_public_url(final_url)
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise ValueError(f"response exceeds {max_bytes} bytes")
            chunks: List[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"response exceeds {max_bytes} bytes")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
        return b"".join(chunks), final_url, response_headers


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[Tuple[str, str]] = []
        self._anchor: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "a" and values.get("href"):
            label_parts = [values.get("title", ""), values.get("aria-label", "")]
            self._anchor = {"href": values["href"], "label": label_parts, "depth": 1}
        elif self._anchor is not None:
            self._anchor["depth"] += 1
        if tag == "link" and values.get("href"):
            rel = values.get("rel", "") + " " + values.get("type", "")
            if "supp" in rel.lower():
                self.links.append((values["href"], rel))

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor["label"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._anchor is None:
            return
        self._anchor["depth"] -= 1
        if tag == "a" or self._anchor["depth"] <= 0:
            label = " ".join(" ".join(self._anchor["label"]).split())
            self.links.append((self._anchor["href"], label))
            self._anchor = None


def candidate_score(url: str, label: str) -> int:
    decoded_url = unquote(url).lower()
    text = f"{decoded_url} {html.unescape(label).lower()}"
    if any(phrase in text for phrase in REJECT_PHRASES):
        return -100
    score = 0
    if any(phrase in text for phrase in SUPPORTING_PHRASES):
        score += 10
    if looks_like_supporting_filename(decoded_url):
        score += 7
    if "/suppl_file/" in decoded_url or "downloadsupplement" in decoded_url:
        score += 7
    if re.search(r"\.pdf(?:$|[?#])", decoded_url):
        score += 3
    if "pdf" in label.lower():
        score += 1
    return score


def figshare_candidates(client: HttpClient, doi: str) -> Tuple[List[Dict[str, str]], List[str]]:
    candidates: List[Dict[str, str]] = []
    errors: List[str] = []
    search_url = "https://api.figshare.com/v2/articles/search"
    try:
        raw, _, _ = client.post_json(search_url, {"resource_doi": doi, "page_size": 100}, 4 * 1024 * 1024)
        records = json.loads(raw.decode("utf-8"))
        for record in records:
            if normalize_doi(record.get("resource_doi")) != doi:
                continue
            article_id = str(record.get("id", ""))
            if not article_id.isdigit():
                continue
            detail_url = f"https://api.figshare.com/v2/articles/{article_id}"
            detail_raw, _, _ = client.get(detail_url, 4 * 1024 * 1024, "application/json")
            detail = json.loads(detail_raw.decode("utf-8"))
            record_signal = (
                bool(re.search(r"(?i)\.s\d+$", str(detail.get("doi", ""))))
                or any(phrase in str(detail.get("title", "")).lower() for phrase in SUPPORTING_PHRASES)
            )
            for file_info in detail.get("files", []):
                name = str(file_info.get("name", ""))
                mimetype = str(file_info.get("mimetype", "")).lower()
                if mimetype != "application/pdf" and not name.lower().endswith(".pdf"):
                    continue
                if not record_signal and not looks_like_supporting_filename(name):
                    continue
                download_url = str(file_info.get("download_url", ""))
                if not download_url:
                    continue
                candidates.append(
                    {
                        "source": "figshare",
                        "source_id": f"figshare-{file_info.get('id', article_id)}",
                        "source_url": download_url,
                        "record_url": detail_url,
                        "label": str(detail.get("title", "Supporting information")),
                        "filename": name,
                        "expected_md5": str(file_info.get("computed_md5") or file_info.get("supplied_md5") or ""),
                        "license": str((detail.get("license") or {}).get("name", "")),
                    }
                )
    except Exception as error:
        errors.append(f"figshare: {error}")
    return candidates, errors


def publisher_candidates(
    client: HttpClient,
    doi: str,
    metadata_url: str,
) -> Tuple[List[Dict[str, str]], List[str]]:
    candidates: List[Dict[str, str]] = []
    errors: List[str] = []
    landing_urls: List[str] = []
    if metadata_url and urlparse(metadata_url).scheme in {"http", "https"}:
        landing_urls.append(metadata_url)
    else:
        landing_urls.append(f"https://doi.org/{quote(doi, safe='/()')}")
    seen_landing = set()
    for landing_url in landing_urls:
        if landing_url in seen_landing:
            continue
        seen_landing.add(landing_url)
        try:
            raw, final_url, headers = client.get(
                landing_url,
                8 * 1024 * 1024,
                "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            )
            content_type = headers.get("content-type", "").lower()
            if "html" not in content_type and not raw.lstrip().startswith((b"<!DOCTYPE", b"<html")):
                continue
            parser = LinkCollector()
            parser.feed(raw.decode("utf-8", errors="ignore"))
            for href, label in parser.links:
                candidate_url = urljoin(final_url, html.unescape(href))
                if candidate_score(candidate_url, label) < 8:
                    continue
                candidates.append(
                    {
                        "source": "publisher",
                        "source_id": f"publisher-{hashlib.sha1(candidate_url.encode('utf-8')).hexdigest()[:12]}",
                        "source_url": candidate_url,
                        "record_url": final_url,
                        "label": label or "Supporting information",
                        "filename": Path(unquote(urlparse(candidate_url).path)).name or "supporting-information.pdf",
                        "expected_md5": "",
                        "license": "",
                    }
                )
            if candidates:
                break
        except Exception as error:
            errors.append(f"publisher {urlparse(landing_url).netloc}: {error}")
    unique: Dict[str, Dict[str, str]] = {}
    for candidate in sorted(candidates, key=lambda item: candidate_score(item["source_url"], item["label"]), reverse=True):
        unique.setdefault(candidate["source_url"], candidate)
    return list(unique.values())[:12], errors


def discover_candidates(client: HttpClient, doi: str, metadata_url: str) -> Tuple[List[Dict[str, str]], List[str]]:
    all_candidates, all_errors = figshare_candidates(client, doi)
    if not all_candidates:
        publisher_results, publisher_errors = publisher_candidates(client, doi, metadata_url)
        all_candidates.extend(publisher_results)
        all_errors.extend(publisher_errors)
    unique: Dict[str, Dict[str, str]] = {}
    for candidate in all_candidates:
        unique.setdefault(candidate["source_url"], candidate)
    return list(unique.values()), all_errors


def _archive_previous(destination: Path, history_dir: Path, previous_sha: str) -> None:
    if not destination.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archived = history_dir / f"{destination.stem}__{stamp}__{previous_sha[:8] or 'unknown'}.pdf"
    history_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, archived)


def _copy_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    os.close(fd)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _pdf_bytes(client: HttpClient, candidate: Dict[str, str], max_file_bytes: int) -> Tuple[bytes, str]:
    raw, final_url, headers = client.get(candidate["source_url"], max_file_bytes, "application/pdf,*/*;q=0.1")
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in PDF_CONTENT_TYPES and not raw.startswith(b"%PDF-"):
        raise ValueError(f"unexpected content type {content_type}")
    if len(raw) < 1024 or not raw.startswith(b"%PDF-"):
        raise ValueError("download is not a valid PDF")
    expected_md5 = candidate.get("expected_md5", "").lower()
    if expected_md5 and hashlib.md5(raw).hexdigest() != expected_md5:  # nosec: publisher integrity value
        raise ValueError("download MD5 does not match repository metadata")
    return raw, final_url


def _valid_previous_files(entry: Dict[str, Any], vault: Path) -> List[Dict[str, Any]]:
    valid: List[Dict[str, Any]] = []
    for file_entry in entry.get("files", []):
        destination = vault / str(file_entry.get("destination", ""))
        if destination.is_file() and destination.stat().st_size >= 1024:
            valid.append(dict(file_entry))
    return valid


def _due_for_online_check(previous: Dict[str, Any], current_doi: str) -> bool:
    if normalize_doi(previous.get("doi")) != current_doi:
        return True
    next_check = parse_iso(previous.get("next_check_after"))
    return next_check is None or datetime.now(timezone.utc).astimezone() >= next_check


def sync_supporting_information(
    config: Dict[str, Any],
    vault: Path,
    literature_dir: Path,
    parents: Dict[str, Dict[str, Any]],
    main_parent_keys: Iterable[str],
    supplementary_attachments: Iterable[Dict[str, Any]],
    source_path_resolver,
    logger,
) -> Tuple[Dict[str, Any], bool, Dict[str, int]]:
    settings = config.get("supplementary_information", {})
    enabled = bool(settings.get("enabled", False))
    relative_manifest = str(
        settings.get("manifest", "sources/literature/manifests/supporting-information.json")
    )
    manifest_path = vault / relative_manifest
    previous_manifest = read_json(manifest_path, {"items": []})
    previous_by_parent = {
        str(entry.get("parent_key", "")): entry
        for entry in previous_manifest.get("items", [])
        if entry.get("parent_key")
    }
    if not enabled:
        return previous_manifest, False, {"available": 0, "downloaded": 0, "failed": 0}

    relative_directory = str(settings.get("directory", "sources/literature/si"))
    si_root = vault / relative_directory
    history_root = literature_dir / "history" / "si"
    timeout_seconds = max(5, int(settings.get("timeout_seconds", 30)))
    max_file_bytes = max(1024 * 1024, int(settings.get("max_file_bytes", 100 * 1024 * 1024)))
    refresh_days = max(1, int(settings.get("refresh_days", 30)))
    retry_days = max(1, int(settings.get("retry_days", 7)))
    client = HttpClient(timeout_seconds, str(settings.get("proxy_url", "")).strip())
    checked_now = now_iso()

    si_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for attachment in supplementary_attachments:
        parent_key = str(attachment.get("data", {}).get("parentItem", ""))
        if parent_key:
            si_by_parent.setdefault(parent_key, []).append(attachment)

    entries: List[Dict[str, Any]] = []
    downloaded_count = 0
    failed_count = 0
    active_parent_keys = {key for key in main_parent_keys if key}
    for parent_key in sorted(active_parent_keys):
        parent = parents.get(parent_key, {})
        data = parent.get("data", {})
        doi = normalize_doi(data.get("DOI"))
        previous = previous_by_parent.get(parent_key, {})
        files = _valid_previous_files(previous, vault)
        errors: List[str] = []

        previous_zotero = {
            str(file_entry.get("zotero_attachment_key", "")): file_entry
            for file_entry in files
            if file_entry.get("zotero_attachment_key")
        }
        for attachment in si_by_parent.get(parent_key, []):
            attachment_key = str(attachment.get("key", ""))
            attachment_data = attachment.get("data", {})
            old_file = previous_zotero.get(attachment_key, {})
            try:
                source = Path(source_path_resolver(attachment_key))
                if not source.is_file():
                    raise FileNotFoundError(source)
                source_fingerprint = attachment_data.get("md5") or f"{source.stat().st_size}:{source.stat().st_mtime_ns}"
                destination_name = old_file.get("destination_name") or supporting_filename(
                    attachment_data.get("filename") or source.name,
                    f"zotero-{attachment_key}",
                )
                destination = si_root / parent_key / destination_name
                needs_copy = (
                    not destination.exists()
                    or old_file.get("source_fingerprint") != source_fingerprint
                )
                if needs_copy:
                    if destination.exists():
                        _archive_previous(destination, history_root / parent_key, old_file.get("sha256", ""))
                    _copy_atomically(source, destination)
                    downloaded_count += 1
                    logger(f"SI copied from Zotero {attachment_key}: {destination.name}")
                sha256 = file_sha256(destination)
                files = [
                    item for item in files
                    if item.get("zotero_attachment_key") != attachment_key
                ]
                files.append(
                    {
                        "bytes": destination.stat().st_size,
                        "destination": str(destination.relative_to(vault)),
                        "destination_name": destination.name,
                        "label": str(attachment_data.get("title") or "Zotero supporting information"),
                        "sha256": sha256,
                        "source": "zotero",
                        "source_fingerprint": source_fingerprint,
                        "source_url": f"zotero://select/library/items/{attachment_key}",
                        "zotero_attachment_key": attachment_key,
                    }
                )
            except Exception as error:
                errors.append(f"zotero {attachment_key}: {error}")

        due = bool(doi) and _due_for_online_check(previous, doi)
        checked_at = str(previous.get("checked_at", ""))
        if due:
            checked_at = checked_now
            candidates, discovery_errors = discover_candidates(client, doi, str(data.get("url", "")))
            errors.extend(discovery_errors)
            known_sources = {str(item.get("source_url", "")) for item in files}
            known_hashes = {str(item.get("sha256", "")) for item in files}
            for candidate in candidates:
                if candidate["source_url"] in known_sources:
                    continue
                try:
                    raw, final_url = _pdf_bytes(client, candidate, max_file_bytes)
                    sha256 = hashlib.sha256(raw).hexdigest()
                    if sha256 in known_hashes:
                        continue
                    destination_name = supporting_filename(candidate.get("filename"), candidate["source_id"])
                    destination = si_root / parent_key / destination_name
                    if destination.exists() and file_sha256(destination) != sha256:
                        _archive_previous(destination, history_root / parent_key, file_sha256(destination))
                    atomic_write_bytes(destination, raw)
                    files.append(
                        {
                            "bytes": len(raw),
                            "destination": str(destination.relative_to(vault)),
                            "destination_name": destination.name,
                            "label": candidate.get("label", "Supporting information"),
                            "license": candidate.get("license", ""),
                            "record_url": candidate.get("record_url", ""),
                            "sha256": sha256,
                            "source": candidate.get("source", "publisher"),
                            "source_url": final_url,
                        }
                    )
                    known_hashes.add(sha256)
                    known_sources.add(candidate["source_url"])
                    downloaded_count += 1
                    logger(f"SI downloaded {parent_key}: {destination.name}")
                except Exception as error:
                    errors.append(f"download {candidate.get('source_url', '')}: {error}")

        files = sorted(files, key=lambda item: (str(item.get("source", "")), str(item.get("destination", ""))))
        if files:
            status = "available"
            next_days = refresh_days
        elif not doi:
            status = "no_doi"
            next_days = retry_days
        elif errors and due:
            status = "not_found"
            next_days = retry_days
        else:
            status = str(previous.get("status") or "not_found")
            next_days = retry_days
        if errors:
            failed_count += 1
        base_time = parse_iso(checked_at) or datetime.now(timezone.utc).astimezone()
        entry = {
            "active": True,
            "checked_at": checked_at,
            "doi": doi,
            "errors": [str(error)[-500:] for error in errors[-8:]],
            "files": files,
            "next_check_after": (base_time + timedelta(days=next_days)).isoformat(timespec="seconds"),
            "parent_key": parent_key,
            "status": status,
            "title": str(data.get("title") or "Untitled"),
            "url": str(data.get("url") or ""),
        }
        entries.append(entry)

    for parent_key, previous in previous_by_parent.items():
        if parent_key in active_parent_keys:
            continue
        inactive = dict(previous)
        inactive["active"] = False
        entries.append(inactive)

    core = {
        "items": sorted(entries, key=lambda item: str(item.get("parent_key", ""))),
        "schema_version": 1,
    }
    previous_core = {
        "items": previous_manifest.get("items", []),
        "schema_version": previous_manifest.get("schema_version", 1),
    }
    changed = core != previous_core or not manifest_path.exists()
    manifest = dict(core)
    manifest["generated_at"] = checked_now if changed else previous_manifest.get("generated_at", checked_now)
    if changed:
        atomic_write_json(manifest_path, manifest)
    stats = {
        "available": sum(1 for entry in entries if entry.get("active") and entry.get("files")),
        "downloaded": downloaded_count,
        "failed": failed_count,
    }
    return manifest, changed, stats
