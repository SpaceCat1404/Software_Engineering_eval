"""
api/index.py — single Python entrypoint for all routes (Vercel's recommended
pattern for "Python API alongside a Next.js frontend": one ASGI app, exposed
as the `app` variable, handling every /api/* path itself).

Every storage-touching route is scoped by a `doc_type` path segment
("srs", "test_plan", or "sads" -- see scorer.RUBRICS) so the same routes/
blob layout serve all document types without duplicating the app.

Routes:
  POST /api/upload/{doc_type}         — one team's .docx/.pdf in -> ingested,
                                         stored to Blob under that doc type.
  POST /api/evaluate-local/{doc_type} — dev-only: scans a local folder
                                         (default per doc_type, see
                                         DEFAULT_SUBMISSIONS_DIRS) directly on
                                         disk and ingests every file in it.
                                         Only works against local blob
                                         storage (no Vercel Blob token set).
  GET  /api/teams/{doc_type}          — every team of that doc type, with
                                         its full ingested text/tables *and*
                                         its AI rubric score if scored --
                                         one bulk payload, no per-team fetch
                                         (cohort size is small enough that
                                         this is simpler than paginating).
  POST /api/score/{doc_type}/{id}     — run the AI rubric score (scorer.py)
                                         for one team, store + return it.
  POST /api/score-all/{doc_type}      — dev-only: score every team of that
                                         doc type that doesn't have a score
                                         yet. Same local-storage-only
                                         constraint as evaluate-local.

Plagiarism checking has been dropped from the live API and UI entirely for
both doc types (judged unlikely to matter / not worth maintaining as a
first-class feature). srs_table_plagiarism.py and plagiarism.py remain in
the repo untouched, runnable standalone if a specific pair is ever worth
spot-checking by hand:
    python srs_table_plagiarism.py --students-dir pipeline_out/students
"""
import sys
import tempfile
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent / "_lib"))

from fastapi import FastAPI, UploadFile, File, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import blob_store  # noqa: E402
from srs_ingest import ingest, resolve_team_id, dedupe_by_team_id  # noqa: E402
from scorer import score as score_submission, RUBRICS  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_SUBMISSIONS_DIRS = {
    "srs": REPO_ROOT / "student_submissions" / "SRS_responses",
    "test_plan": REPO_ROOT / "student_submissions" / "test_plan_responses",
    "sads": REPO_ROOT / "student_submissions" / "SAD_spec_responses",
}
SUPPORTED_SUFFIXES = (".docx", ".pdf")
DocType = Literal["srs", "test_plan", "sads"]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _prefix(doc_type: str, team_id: str = "") -> str:
    return f"submissions/{doc_type}/{team_id}"


def store_submission(doc_type: str, team_id: str, ingested: dict) -> None:
    blob_store.put_json(f"{_prefix(doc_type, team_id)}_ingested.json", ingested)


@app.post("/api/upload/{doc_type}")
async def upload(doc_type: DocType, file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, "expected a .docx or .pdf file")

    team_id, rank = resolve_team_id(Path(file.filename).stem)

    # Resubmission check: if this team already has a stored submission,
    # only overwrite it if the new file outranks the stored one (see
    # srs_ingest.resolve_team_id -- higher "(N)" suffix = later
    # resubmission). Otherwise this upload is an older duplicate arriving
    # after a newer one -- skip it rather than clobbering the real latest
    # version.
    existing = blob_store.list_prefix(f"{_prefix(doc_type, team_id)}_ingested")
    if existing:
        existing_ingested = blob_store.get_json_by_url(existing[0]["url"])
        _, existing_rank = resolve_team_id(Path(existing_ingested.get("source", team_id)).stem)
        if rank <= existing_rank:
            return {"team_id": team_id, "skipped": True,
                    "reason": f"a newer submission for this team is already stored "
                              f"({existing_ingested.get('source')}) -- this upload was not stored"}
        # Genuinely superseding an existing submission (and, if scored, its
        # now-stale score) -- archive the old data before overwriting it.
        blob_store.archive_before_overwrite(_prefix(doc_type, team_id))

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        ingested = ingest(tmp_path)
    except Exception as e:
        raise HTTPException(400, f"could not parse {suffix}: {e}")
    ingested["source"] = file.filename  # real filename, not the tempfile's random name

    store_submission(doc_type, team_id, ingested)

    return {"team_id": team_id, "skipped": False, "lines": len(ingested["raw_text"].splitlines()),
            "tables": len(ingested["tables"])}


class EvaluateLocalRequest(BaseModel):
    folder: str | None = None


@app.post("/api/evaluate-local/{doc_type}")
async def evaluate_local(doc_type: DocType, body: EvaluateLocalRequest = EvaluateLocalRequest()):
    if not blob_store.USE_LOCAL:
        raise HTTPException(400, "evaluate-local is only available in local dev "
                                  "(no BLOB_READ_WRITE_TOKEN set) -- use per-file "
                                  "upload when deployed to Vercel")

    folder = Path(body.folder) if body.folder else DEFAULT_SUBMISSIONS_DIRS[doc_type]
    if not folder.is_dir():
        raise HTTPException(400, f"folder not found: {folder}")

    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        raise HTTPException(400, f"no .docx/.pdf files found in {folder}")

    winners, skipped_dupes = dedupe_by_team_id(files)

    # This batch is about to overwrite every existing ingested/score file
    # for this doc type -- archive whatever's currently there first.
    blob_store.archive_before_overwrite(_prefix(doc_type))

    results = []
    for team_id, fp in winners:
        try:
            ingested = ingest(fp)
        except Exception as e:
            results.append({"team_id": team_id, "file": fp.name, "error": str(e)})
            continue
        ingested["source"] = fp.name
        store_submission(doc_type, team_id, ingested)
        results.append({"team_id": team_id, "file": fp.name,
                         "lines": len(ingested["raw_text"].splitlines()),
                         "tables": len(ingested["tables"])})

    for team_id, fp, reason in skipped_dupes:
        results.append({"team_id": team_id, "file": fp.name, "skipped": True, "reason": reason})

    return {"folder": str(folder), "teams": results,
            "duplicates_skipped": len(skipped_dupes)}


@app.get("/api/teams/{doc_type}")
async def list_teams(doc_type: DocType):
    blobs = blob_store.list_prefix(_prefix(doc_type))
    ingested_blobs = {b["pathname"]: b for b in blobs if b["pathname"].endswith("_ingested.json")}
    score_blobs = {b["pathname"]: b for b in blobs if b["pathname"].endswith("_score.json")}

    teams = []
    for pathname, blob in ingested_blobs.items():
        team_id = Path(pathname).stem.replace("_ingested", "")
        ingested = blob_store.get_json_by_url(blob["url"])
        score_blob = score_blobs.get(f"{_prefix(doc_type, team_id)}_score.json")
        score = blob_store.get_json_by_url(score_blob["url"]) if score_blob else None
        teams.append({
            "team_id": team_id,
            "source": ingested.get("source", team_id),
            "raw_text": ingested.get("raw_text", ""),
            "tables": ingested.get("tables", []),
            "score": score,
        })
    cfg = RUBRICS[doc_type]
    return {
        "doc_type": doc_type,
        "id_categories": cfg["id_categories"],
        "criteria": cfg["criteria"],
        "max_total": cfg["max_total"],
        "teams": teams,
    }


@app.post("/api/score/{doc_type}/{team_id}")
async def score_team(doc_type: DocType, team_id: str):
    ingested_blobs = blob_store.list_prefix(f"{_prefix(doc_type, team_id)}_ingested")
    if not ingested_blobs:
        raise HTTPException(404, "team not found -- ingest it first (upload or evaluate-local)")
    ingested = blob_store.get_json_by_url(ingested_blobs[0]["url"])
    blob_store.archive_before_overwrite(f"{_prefix(doc_type, team_id)}_score")
    report = score_submission(ingested, doc_type)
    blob_store.put_json(f"{_prefix(doc_type, team_id)}_score.json", report)
    return report


@app.post("/api/score-all/{doc_type}")
async def score_all(doc_type: DocType):
    if not blob_store.USE_LOCAL:
        raise HTTPException(400, "score-all is only available in local dev "
                                  "(no BLOB_READ_WRITE_TOKEN set) -- score "
                                  "teams individually via POST /api/score/{doc_type}/{id} when deployed")

    blobs = blob_store.list_prefix(_prefix(doc_type))
    team_ids = sorted({
        Path(b["pathname"]).stem.replace("_ingested", "")
        for b in blobs if b["pathname"].endswith("_ingested.json")
    })

    # About to overwrite every existing score for this doc type -- archive
    # the whole doc type's current state in one snapshot first (a single
    # run folder, not one per team).
    blob_store.archive_before_overwrite(_prefix(doc_type))

    results = []
    for team_id in team_ids:
        ingested_blobs = [b for b in blobs if b["pathname"] == f"{_prefix(doc_type, team_id)}_ingested.json"]
        ingested = blob_store.get_json_by_url(ingested_blobs[0]["url"])
        report = score_submission(ingested, doc_type)
        blob_store.put_json(f"{_prefix(doc_type, team_id)}_score.json", report)
        results.append({"team_id": team_id, "total_score": report["total_score"],
                         "percentage": report["percentage"], "flags": report["flags"]})

    return {"scored": len(results), "teams": results}
