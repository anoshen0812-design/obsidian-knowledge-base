#!/usr/bin/env python3
"""Validate the device-local Forge Paper Note installation used by the pipeline."""

from __future__ import annotations

import os
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_FILES = (
    "SKILL.md",
    "references/knowledge-base-profile.md",
    "references/research-audit.md",
    "references/technical-language-audit.md",
    "scripts/lint_note.py",
    "scripts/lint_research_audit.py",
    "scripts/lint_technical_language.py",
    "scripts/materialize_figure_asset.py",
    "scripts/write_obsidian_note.py",
)

CURRENT_PAPER_ONLY_MARKERS = (
    "## Current-paper-only literature context",
    "paper_characterization_only",
    "Do not use web search",
)


def compatible_python(explicit: str) -> str:
    candidates = [explicit] if explicit else [
        sys.executable,
        *(shutil.which(name) or "" for name in ("python3.13", "python3.12", "python3.11", "python3.10")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        result = subprocess.run(
            [candidate, "-c", "import sys; raise SystemExit(sys.version_info < (3, 10))"],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            return str(Path(candidate).expanduser().resolve())
    raise RuntimeError("No Python 3.10+ interpreter found; pass --python /absolute/path/to/python.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="", help="Python 3.10+ interpreter used by Forge scripts")
    args = parser.parse_args()
    try:
        interpreter = compatible_python(args.python)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    skill_dir = codex_home / "skills" / "forge-paper-note"
    missing = [relative for relative in REQUIRED_FILES if not (skill_dir / relative).is_file()]
    if missing:
        print(f"Forge Paper Note is incomplete at {skill_dir}", file=sys.stderr)
        for relative in missing:
            print(f"- missing: {relative}", file=sys.stderr)
        return 1

    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    missing_markers = [marker for marker in CURRENT_PAPER_ONLY_MARKERS if marker not in skill_text]
    if missing_markers:
        print("Forge Paper Note is missing the local-only prior-work policy", file=sys.stderr)
        for marker in missing_markers:
            print(f"- missing marker: {marker}", file=sys.stderr)
        return 1

    audit_linter = (skill_dir / "scripts/lint_research_audit.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    if 'VERIFICATION_STATUSES = {"paper_characterization_only"}' not in audit_linter:
        print("Forge research-audit lint does not enforce paper_characterization_only", file=sys.stderr)
        return 1

    print(f"Forge Paper Note ready: {skill_dir}")
    print("Prior-work policy: current paper only; network literature research disabled")
    print(f"Compatible Python: {interpreter}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
