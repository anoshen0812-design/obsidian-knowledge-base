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
boundaries in `extracts/papers/*.md`. MinerU's complete extraction cache is kept in
`extracts/papers/assets/<attachment-key>/<source-hash>/`. Images actually selected for
a note are copied to `wiki/papers/images/<exact-note-stem>/`; each note records that
directory in its `images_dir` property and may only embed assets from its own directory.
`pdftotext -layout` remains
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
are attached to the paper task. They are not extracted by default. Forge Paper Note opens SI
only for a specific claim that the primary paper explicitly delegates to SI, and cites
the exact SI page when used.

Paper draft filenames, level-one headings, and index aliases follow
`YYYY-MM-DD - 第一作者 - 文献标题`. The date is fixed when draft generation first starts.
Paper frontmatter always includes `impact_factor`, `impact_factor_year`, and
`impact_factor_source`. Zotero sync uses a cached Codex live-web lookup against
official publisher or Clarivate pages and records `impact_factor_retrieved_at`;
unavailable values remain explicit YAML `null` values.

## Forge Paper Note paper reading

The automated paper task uses the local `forge-paper-note` skill exclusively. Verify the
local installation before processing papers:

```bash
python3 scripts/check-forge-paper-note.py
```

The check requires `$CODEX_HOME/skills/forge-paper-note/SKILL.md` plus its deterministic
figure, lint, and save scripts. The skill itself is device-local and is not vendored in this
repository. Set `forge_python_path` in `config.json` to a Python 3.10+ interpreter; the
runner passes that exact interpreter to unattended Forge tasks.
