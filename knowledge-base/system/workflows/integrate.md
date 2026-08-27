# Reviewed-note integration workflow

Integrate exactly the supplied `NOTE_PATH`. The note must already have `status: reviewed`.

## Safety boundary

- Never modify `sources/`, `extracts/`, `笔记/实验笔记/`, or `system/queue/pending.json`.
- Do not silently resolve contradictions. Record competing evidence and its conditions.
- Do not remove human review comments.
- Every scientific claim added to a canonical wiki page must link back to the reviewed note and, for papers, to a PDF page.

## Canonical page rules

Canonical knowledge lives in:

- `wiki/concepts/`
- `wiki/materials/`
- `wiki/methods/`
- `wiki/phenomena/`
- `wiki/projects/`
- `wiki/questions/`
- `wiki/synthesis/`

Create a new canonical page only when at least one condition holds:

1. the subject appears in two or more reviewed sources;
2. it is a core variable in the user's research;
3. it directly connects a paper to an experiment note;
4. competing evidence needs an explicit comparison page.

Otherwise, keep the candidate association in the reviewed note without creating an empty page.

## Integration operations

1. Read `wiki/index.md` and search existing wiki pages before creating anything.
2. Update relevant canonical pages with concise, source-bound evidence.
3. Use evidence tables where useful: claim, conditions, direction/effect, source, confidence.
4. Add bidirectional Obsidian links between the reviewed note and canonical pages.
5. Record support, qualification, or contradiction explicitly.
6. Add unresolved gaps to an existing question page or a justified new page in `wiki/questions/`.
7. Move the note's entry from `## 待审核草稿` to `## 已整合来源` in `wiki/index.md`.
8. Change the reviewed note frontmatter to `status: integrated`, `reviewed: true`, and add `integrated_at`.

Canonical pages should normally contain: current understanding, mechanism or definition, evidence, limiting/contradictory evidence, linked papers, linked experiments, and open questions.

Finish with JSON matching `system/knowledge/result.schema.json`, using `operation: integrate` and `status: integrated`.
