#!/usr/bin/env python3
"""Validate the device-local paper-reading skill and its Mode A contract."""

from __future__ import annotations

import os
from pathlib import Path


REQUIRED_MARKERS = (
    "## Mode A: Paragraph-by-Paragraph Deep Reading",
    "### Agentic Q&A Protocol (Mode A)",
    "Obsidian Knowledge Snippet",
)


def main() -> int:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    skill_file = codex_home / "skills" / "paper-reading" / "SKILL.md"
    if not skill_file.is_file():
        print(f"paper-reading skill not found: {skill_file}")
        return 1
    content = skill_file.read_text(encoding="utf-8", errors="ignore")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in content]
    if missing:
        print(f"paper-reading skill does not expose the required Mode A contract: {skill_file}")
        for marker in missing:
            print(f"- missing marker: {marker}")
        return 1
    print(f"paper-reading Mode A ready: {skill_file.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
