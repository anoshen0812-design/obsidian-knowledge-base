# Knowledge queue

`pending.json` is owned by `system/knowledge/run_pipeline.py`. Do not edit it manually.

Task lifecycle:

`pending → drafted → reviewed → integrated`

Exceptional states are `failed`, `needs_ocr`, and `superseded`.
