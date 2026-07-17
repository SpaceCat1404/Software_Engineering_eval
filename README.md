# SRS grader (Vercel)

## What's here
- `api/index.py` — single Python (FastAPI) entrypoint, all routes
- `api/_lib/` — your existing `srs_ingest.py`, `srs_completeness.py`,
  `srs_table_plagiarism.py`, `plagiarism.py`, unmodified except one import
  path fix, plus `blob_store.py` (new — the Vercel Blob read/write glue)
- `app/` — minimal Next.js frontend: upload a docx, see completeness,
  run the cohort plagiarism check

## Why it's structured this way
Vercel functions are stateless — nothing written to disk survives between
requests. So instead of the CLI scripts' local `pipeline_out/students/`
folder, every ingested/completeness JSON gets written to Vercel Blob on
upload, and `/api/compare` reads all of them back before running the
row-level plagiarism check. This is the one real change from the local
version; the grading/checking logic itself (`srs_ingest.py`,
`srs_completeness.py`, `srs_table_plagiarism.py`) is untouched.

## Deploy
1. `npm install`
2. `vercel link` (creates/links the Vercel project)
3. In the Vercel dashboard: Project -> Storage -> Create a Blob store ->
   connect it to this project. This auto-injects `BLOB_READ_WRITE_TOKEN`.
4. `vercel env pull .env.local` (to test locally with `vercel dev`)
5. `vercel deploy`

## Local testing
`vercel dev` runs both the Next.js frontend and the Python function
together. Plain `next dev` will NOT work for the API routes — Python
functions only run under the Vercel dev server or on Vercel itself.

## Routes
- `POST /api/upload` — multipart form, field `file`, a `.docx`. Returns
  that team's completeness report immediately.
- `GET /api/teams` — every team uploaded so far + missing/skimped counts.
- `POST /api/compare` — run once all teams are in. Pulls every stored
  ingested JSON, runs the row-level table plagiarism check, returns +
  stores the cohort report.

## Approach: no section/heading detection

An earlier version tried to reconstruct document structure (heading styles
for docx, a font-size/numbering heuristic for PDF) so completeness checks
could be scoped per-section, the way the CNS pipeline this was forked from
does. That doesn't generalize here: real student SRS docs vary far more in
formatting than CNS submissions did, and two genuine bugs (a PDF whose
headings had no bold/size signal at all, and requirement lines using ":"
instead of "-") both turned out to be section-detection failures. Section
detection was dropped entirely as of 2026-07-15:
- `srs_ingest.py` just extracts raw text + tables, no heading/section tree.
- `srs_completeness.py` counts FR/NFR/security-objective/security-requirement
  rows globally by their own ID marker (F/NF/SEC/SR) — no section needed,
  the marker already says what it is.
- `srs_score.py` (the AI rubric, now wired up via `POST /api/score/{id}` and
  `POST /api/score-all`) judges presence/quality of the descriptive sections
  (introduction, overall description, UML, etc.) directly from the full raw
  text — that's a judgment call a human grader makes by reading the
  document, not something a heading-matcher should be trusted to gate.

## Known gaps / next steps
- **No auth.** Anyone with the URL can upload or trigger a comparison.
  Fine for a closed pilot; add a shared secret or login before wider use.
- **No de-dup on re-upload.** Uploading the same team twice overwrites
  their blob (by design, via `allowOverwrite`) — no versioning yet.
- **No override storage.** Once a TA wants to override an AI score, you
  need mutable, queryable state (who scored what, when, what the override
  was) — Blob storage is fine for immutable JSON artifacts but awkward for
  that; a real database earns its place at that point.
