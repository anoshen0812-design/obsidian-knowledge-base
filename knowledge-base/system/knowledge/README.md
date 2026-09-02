# Automated knowledge pipeline

The pipeline watches the Zotero manifest and human experiment notes, tracks content hashes, extracts structured PDF content, creates Codex drafts, integrates reviewed notes, and produces weekly health reports.

Common commands:

```bash
/usr/bin/python3 system/knowledge/run_pipeline.py scan
/usr/bin/python3 system/knowledge/run_pipeline.py status
/usr/bin/python3 system/knowledge/run_pipeline.py ingest-next
/usr/bin/python3 system/knowledge/run_pipeline.py paragraph-read --note "wiki/papers/YYYY-MM-DD - First Author - Paper Title.md"
/usr/bin/python3 system/knowledge/run_pipeline.py redraft --note "wiki/papers/YYYY-MM-DD - First Author - Paper Title.md"
/usr/bin/python3 system/knowledge/run_pipeline.py integrate --note "wiki/papers/YYYY-MM-DD - First Author - Paper Title.md"
/usr/bin/python3 system/knowledge/run_pipeline.py lint
```

Obsidian exposes equivalent commands. Automatic ingest processes one source at a time.
`redraft` only requeues the exact existing primary paper note supplied with `--note`;
the next `ingest-next` regenerates it with the current Forge workflow and returns it
to draft review without editing queue JSON by hand. Both normal paper ingest and
redrafts have a 30-minute single-paper limit (`codex_timeout_seconds` and
`redraft_timeout_seconds`, both defaulting to 1800 seconds).

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

Forge literature context is intentionally local-only: the prior-work section may
summarize only how the current paper describes its cited works. It does not search the
web or open cited papers, every entry is marked as not independently verified, and
follow-up novelty remains unresolved without external literature calibration.

## Optional Mode A paragraph reading

Every primary paper note exposes two human-owned Obsidian checkboxes:
`paragraph_reading` and `paragraph_reading_figures`. The first opts a valuable paper
into full-text paragraph reading; the second separately authorizes figure/table
analysis. Neither option runs automatically.

After checking `paragraph_reading`, open that primary note and run the Obsidian command
`开始或继续当前论文的逐段精读（Mode A）`. The runner invokes the device-local
`paper-reading` skill in Mode A and writes a separate companion note at
`wiki/papers/close-reading/<exact-primary-note-filename>`. Partial work records a
precise checkpoint and can be continued with the same command. Both notes share the
paper's existing `wiki/papers/images/<exact-note-stem>/` asset directory.

Verify the optional local skill before first use:

```bash
python3 scripts/check-paper-reading.py
```

Set `paragraph_reading_skill` to `paper-reading` and allow a longer
`paragraph_reading_timeout_seconds` in `config.json` because Mode A is substantially
more detailed than normal ingest.
