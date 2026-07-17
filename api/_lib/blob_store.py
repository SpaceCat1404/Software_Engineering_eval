"""
blob_store.py — thin JSON read/write wrapper over Vercel Blob.

Why this exists at all: Vercel functions have no persistent filesystem
between invocations, so "team A uploads, later the instructor runs a
cohort-wide comparison" can't just be two steps reading/writing local files
the way the original CLI scripts do. Every ingested/completeness/report
JSON has to round-trip through Blob storage instead.

Uses the 'vercel_blob' PyPI package (unofficial wrapper around the Blob
REST API — see requirements.txt). Reads BLOB_READ_WRITE_TOKEN from the
environment automatically; Vercel sets this for you once a Blob store is
connected to the project (Project Settings -> Storage -> connect Blob store).

Local dev fallback: with no BLOB_READ_WRITE_TOKEN set (e.g. running
`uvicorn` directly instead of `vercel dev`, before a Blob store is linked),
this reads/writes plain JSON files under LOCAL_BLOB_DIR instead. Lets the
UI be exercised end-to-end without a Vercel account.
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import requests

LOCAL_BLOB_DIR = Path(__file__).parent.parent.parent / "pipeline_out" / "blob_local"
CLI_RUNS_DIR = Path(__file__).parent.parent.parent / "pipeline_out" / "cli_runs"
USE_LOCAL = not os.environ.get("BLOB_READ_WRITE_TOKEN")

if not USE_LOCAL:
    import vercel_blob


def archive_before_overwrite(prefix: str) -> Path | None:
    """Snapshot every local blob file under LOCAL_BLOB_DIR whose relative
    path starts with `prefix` into a timestamped folder under
    pipeline_out/cli_runs/, before a batch operation (evaluate-local,
    score-all, or a superseding single upload/score) overwrites it. `prefix`
    is a pathname prefix, not necessarily a directory -- e.g.
    "submissions/sads" (catches a whole doc type's directory) or
    "submissions/sads/SomeTeam" (catches just that team's *_ingested.json/
    *_score.json siblings), matching the same prefix convention put_json/
    list_prefix already use.

    Grading output represents real work (LLM calls, time) and should never
    just vanish because a later run touched the same path -- this makes
    "archive the old run before writing the new one" happen automatically
    instead of relying on nobody ever running rm -rf on live data again.
    No-op if nothing exists yet at that prefix, or if using real Vercel Blob
    (which has its own versioning, no local snapshot needed)."""
    if not USE_LOCAL or not LOCAL_BLOB_DIR.exists():
        return None
    matches = [
        p for p in LOCAL_BLOB_DIR.rglob("*.json")
        if str(p.relative_to(LOCAL_BLOB_DIR)).replace("\\", "/").startswith(prefix)
    ]
    if not matches:
        return None
    CLI_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    next_seq = len(list(CLI_RUNS_DIR.glob("run_*"))) + 1
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest_root = CLI_RUNS_DIR / f"run_{next_seq:02d}_{stamp}" / "blob_local"
    for p in matches:
        dest = dest_root / p.relative_to(LOCAL_BLOB_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    return dest_root


def put_json(pathname: str, obj: dict) -> dict:
    if USE_LOCAL:
        path = LOCAL_BLOB_DIR / pathname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        return {"pathname": pathname, "url": f"file://{path}"}
    body = json.dumps(obj, indent=2).encode("utf-8")
    return vercel_blob.put(pathname, body, {"addRandomSuffix": "false", "allowOverwrite": "true"})


def list_prefix(prefix: str) -> list:
    if USE_LOCAL:
        if not LOCAL_BLOB_DIR.exists():
            return []
        return [
            {"pathname": str(p.relative_to(LOCAL_BLOB_DIR)).replace("\\", "/"), "url": f"file://{p}"}
            for p in LOCAL_BLOB_DIR.glob(f"{prefix}*.json")
        ]
    resp = vercel_blob.list({"prefix": prefix, "limit": "1000"})
    return resp.get("blobs", [])


def get_json_by_url(url: str) -> dict:
    if url.startswith("file://"):
        return json.loads(Path(url[len("file://"):]).read_text(encoding="utf-8"))
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()
