# Automated knowledge pipeline

The pipeline watches the Zotero manifest and human experiment notes, tracks content hashes, extracts structured PDF content, creates Codex drafts, integrates reviewed notes, and produces weekly health reports.

Common commands:

```bash
/usr/bin/python3 system/knowledge/run_pipeline.py scan
/usr/bin/python3 system/knowledge/run_pipeline.py status
/usr/bin/python3 system/knowledge/run_pipeline.py ingest-next
/usr/bin/python3 system/knowledge/run_pipeline.py integrate --note "wiki/papers/YYYY-MM-DD - First Author - Paper Title.md"
/usr/bin/python3 system/knowledge/run_pipeline.py lint
```

Obsidian exposes equivalent commands. Automatic ingest processes one source at a time.

Paper extraction uses MinerU by default. Its structured content list is regrouped by
`page_idx`, preserving formulas, tables, figures, captions, and `## Page N` evidence
boundaries in `extracts/papers/*.md`. Extracted images are copied to
`extracts/papers/assets/<attachment-key>/<source-hash>/`. `pdftotext -layout` remains
an automatic fallback if MinerU is unavailable, times out, fails, or produces too little
content. A task is marked `needs_ocr` only when the fallback also produces insufficient
text.

The important parser settings in `config.json` are:

- `pdf_extractor`: normally `mineru`.
- `mineru_path`: absolute path to the isolated MinerU executable.
- `mineru_backend`: `pipeline` is the conservative local default.
- `mineru_method`: `auto` chooses embedded text or OCR.
- `mineru_model_cache`: local model cache outside the iCloud vault.
- `mineru_fallback_to_pdftotext`: keep `true` for unattended operation.

If Zotero sync has cached supporting-information PDFs, their paths and availability
are attached to the paper task. They are not extracted by default. PaperForge opens SI
only for a specific claim that the primary paper explicitly delegates to SI, and cites
the exact SI page when used.

Paper draft filenames, level-one headings, and index aliases follow
`YYYY-MM-DD - 第一作者 - 文献标题`. The date is fixed when draft generation first starts.
Paper frontmatter always includes `impact_factor`, `impact_factor_year`, and
`impact_factor_source`. Zotero sync uses a cached Codex live-web lookup against
official publisher or Clarivate pages and records `impact_factor_retrieved_at`;
unavailable values remain explicit YAML `null` values.

## PaperForge paper reading

Install the pinned upstream PaperForge skill and the vault adapter before processing papers:

```bash
python3 scripts/install-paperforge-skills.py
```

The installer downloads `SKILL_CHN.md` from a pinned PaperForge commit, verifies its checksum, and installs it as the standard `paper-reading-zh/SKILL.md`. Upstream PaperForge content is not vendored in this repository.
