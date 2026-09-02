# Automated knowledge pipeline

The pipeline watches the Zotero manifest and human experiment notes, tracks content hashes, extracts PDF text, creates Codex drafts, integrates reviewed notes, and produces weekly health reports.

Common commands:

```bash
/usr/bin/python3 system/knowledge/run_pipeline.py scan
/usr/bin/python3 system/knowledge/run_pipeline.py status
/usr/bin/python3 system/knowledge/run_pipeline.py ingest-next
/usr/bin/python3 system/knowledge/run_pipeline.py integrate --note "wiki/papers/YYYY-MM-DD - First Author - Paper Title.md"
/usr/bin/python3 system/knowledge/run_pipeline.py lint
```

Obsidian exposes equivalent commands. Automatic ingest processes one source at a time. Scanned PDFs with insufficient extractable text are marked `needs_ocr` rather than summarized unreliably.

If Zotero sync has cached supporting-information PDFs, their paths and availability
are attached to the paper task. They are not extracted by default. PaperForge opens SI
only for a specific claim that the primary paper explicitly delegates to SI, and cites
the exact SI page when used.

Paper draft filenames, level-one headings, and index aliases follow
`YYYY-MM-DD - 第一作者 - 文献标题`. The date is fixed when draft generation first starts.
Paper frontmatter always includes `impact_factor`, `impact_factor_year`, and
`impact_factor_source`; unavailable values remain explicit YAML `null` values.

## PaperForge paper reading

Install the pinned upstream PaperForge skill and the vault adapter before processing papers:

```bash
python3 scripts/install-paperforge-skills.py
```

The installer downloads `SKILL_CHN.md` from a pinned PaperForge commit, verifies its checksum, and installs it as the standard `paper-reading-zh/SKILL.md`. Upstream PaperForge content is not vendored in this repository.
