#!/usr/bin/env python3
"""Install the pinned PaperForge Chinese skill and this repository's vault adapter."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


PAPERFORGE_COMMIT = "68addabc0d425b9dd358eaf604e5806e930ad3a2"
PAPERFORGE_SHA256 = "25dba4472cb9b113dfd1960069e5c74817bcf5f393a1ceccee41fd80e72b1b0c"
PAPERFORGE_URL = (
    "https://raw.githubusercontent.com/FeijiangHan/PaperForge/"
    f"{PAPERFORGE_COMMIT}/SKILL_CHN.md"
)


def download() -> bytes:
    request = Request(PAPERFORGE_URL, headers={"User-Agent": "obsidian-knowledge-base-installer"})
    with urlopen(request, timeout=30) as response:
        content = response.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != PAPERFORGE_SHA256:
        raise RuntimeError(f"PaperForge checksum mismatch: {digest}")
    return content


def install_directory(source: Path, destination: Path, force: bool) -> None:
    if destination.exists():
        if not force:
            raise FileExistsError(f"Already exists: {destination}; rerun with --force to replace it")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=codex_home / "skills",
        help="Codex skills directory (default: $CODEX_HOME/skills or ~/.codex/skills)",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing skill directories")
    args = parser.parse_args()

    target = args.target_dir.expanduser().resolve()
    adapter_source = Path(__file__).resolve().parents[1] / "skills" / "paperforge-vault-note"
    if not (adapter_source / "SKILL.md").is_file():
        raise RuntimeError(f"Missing adapter skill: {adapter_source}")

    destinations = [target / "paper-reading-zh", target / "paperforge-vault-note"]
    existing = [destination for destination in destinations if destination.exists()]
    if existing and not args.force:
        joined = ", ".join(str(destination) for destination in existing)
        raise FileExistsError(f"Already exists: {joined}; rerun with --force to replace them")

    upstream_content = download()
    with tempfile.TemporaryDirectory(prefix="paperforge-skill-") as temporary:
        upstream_source = Path(temporary) / "paper-reading-zh"
        upstream_source.mkdir()
        (upstream_source / "SKILL.md").write_bytes(upstream_content)
        install_directory(upstream_source, destinations[0], args.force)

    install_directory(adapter_source, destinations[1], args.force)
    print(f"Installed PaperForge skills in {target}")
    print(f"Pinned upstream commit: {PAPERFORGE_COMMIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
