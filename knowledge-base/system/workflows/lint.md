# Wiki health-check workflow

Inspect `wiki/`, `system/ingest-log.md`, the generated source manifest, and experiment-note filenames. Generate only the report path supplied by the caller.

Check for:

- broken or ambiguous internal links;
- orphan pages without meaningful inbound links;
- integrated claims missing a source or PDF page;
- duplicate or near-duplicate concept pages;
- contradictions that are being presented as a single settled claim;
- stale draft or reviewed notes not integrated;
- important recurring concepts that lack a canonical page;
- canonical pages supported by only one weak source;
- paper–experiment disagreements worth investigating;
- missing source files or inactive Zotero attachments;
- paper notes missing `impact_factor`, `impact_factor_year`, `impact_factor_source`, or `impact_factor_retrieved_at`, and non-null impact factors without a source or retrieval time;
- knowledge gaps that suggest a new literature search or experiment.

The report must separate: critical integrity problems, review backlog, contradiction candidates, graph/link quality, and suggested next investigations. Include exact file links.

Do not automatically modify scientific content or resolve contradictions. Finish with JSON matching `system/knowledge/result.schema.json`, using `operation: lint` and `status: reported`.
