# Knowledge queue

`pending.json` is owned by `system/knowledge/run_pipeline.py`. Do not edit it manually.

Task lifecycle:

`pending → drafted → reviewed → integrated`

Exceptional states are `failed`, `needs_ocr`, and `superseded`.

Paper tasks may also carry a separate `paragraph_reading_status` without changing
their main lifecycle. Its states are `running`, `partial`, `completed`, and `failed`.
The workflow is never selected automatically: a human first checks
`paragraph_reading` in the primary paper note, then starts or continues Mode A from
Obsidian or with `run_pipeline.py paragraph-read --note ...`.

Use `run_pipeline.py redraft --note <exact-primary-note>` to regenerate an existing
paper through the current Forge workflow. This is the supported way to move a
completed paper task back to `pending`; do not edit `pending.json` directly.
`run_pipeline.py cancel-redrafts` safely stops the queued batch by restoring each
unfinished redraft's previous lifecycle state after its running process has ended.
