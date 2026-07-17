#!/usr/bin/env python3
"""
sync_scores_to_blob.py — copy already-computed *_score.json reports from
pipeline_out/ (written by batch_score.py) into pipeline_out/blob_local/
submissions/ (what the web UI actually reads via blob_store.py).

batch_score.py and the web UI's local blob store are two independent
caches of the same score.json shape -- see SESSION_NOTES.txt session 2 for
the same class of bug with the completeness cache. This just re-syncs them
without re-running the LLM (39 real API calls already happened once).

Usage:
    python sync_scores_to_blob.py [--pipeline-dir pipeline_out]
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline-dir", default="pipeline_out")
    args = ap.parse_args()

    pdir = Path(args.pipeline_dir)
    blob_dir = pdir / "blob_local" / "submissions"
    blob_dir.mkdir(parents=True, exist_ok=True)

    score_files = sorted(pdir.glob("*_score.json"))
    if not score_files:
        print(f"No *_score.json found directly under {pdir}")
        return

    copied = 0
    for fp in score_files:
        report = json.loads(fp.read_text(encoding="utf-8"))
        team_id = fp.stem[: -len("_score")]
        dest = blob_dir / f"{team_id}_score.json"
        dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
        copied += 1

    print(f"Synced {copied} score report(s) into {blob_dir}")


if __name__ == "__main__":
    main()
