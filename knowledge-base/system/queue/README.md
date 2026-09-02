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
