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
from pathlib import Path

import requests

LOCAL_BLOB_DIR = Path(__file__).parent.parent.parent / "pipeline_out" / "blob_local"
USE_LOCAL = not os.environ.get("BLOB_READ_WRITE_TOKEN")

if not USE_LOCAL:
    import vercel_blob


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
