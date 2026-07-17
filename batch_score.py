#!/usr/bin/env python3
"""
batch_score.py — run scorer.score() (AI rubric scoring) over every
*_ingested.json already produced by batch_grade.py.

There is no deterministic completeness checker: scorer.py's rubric does its
own extract-then-score pass and self-verifies via verify_citations() (every
item the model claims to have found is checked against the actual
extracted text) -- see report["sanity_check"].

Cross-check logic here is now just:
  - Surface any report flagged with a low sanity_check.grounded_fraction
    (model cited items that don't actually appear in the text -- possible
    hallucination).
  - Flag scores that look internally inconsistent (e.g. total_score not
    equal to the sum of the rubric's criteria) or came back as a hard error.

Usage:
    python batch_score.py --pipeline-dir pipeline_out --doc-type srs
    python batch_score.py --pipeline-dir pipeline_out --doc-type test_plan
"""
import argparse
import json
import sys
from pathlib import Path

from scorer import score as score_submission

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline-dir", default="pipeline_out")
    ap.add_argument("--doc-type", choices=["srs", "test_plan", "sads"], default="srs")
    args = ap.parse_args()

    pdir = Path(args.pipeline_dir)
    ingested_files = sorted(pdir.glob("*_ingested.json"))
    if not ingested_files:
        print(f"ERROR: no *_ingested.json under {pdir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(ingested_files)} ingested submission(s) in {pdir}.", file=sys.stderr)

    cross_check = []
    for i, fp in enumerate(ingested_files, 1):
        team_id = fp.stem[: -len("_ingested")]
        ingested = json.loads(fp.read_text(encoding="utf-8"))

        print(f"  [{i}/{len(ingested_files)}] scoring {team_id} ...", file=sys.stderr)
        try:
            report = score_submission(ingested, args.doc_type)
        except Exception as e:  # noqa: BLE001
            print(f"    [FAIL] {e}", file=sys.stderr)
            cross_check.append({"team_id": team_id, "error": str(e)})
            continue

        out_path = pdir / f"{team_id}_score.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        sum_of_criteria = sum(c["score"] for c in report["criteria"])
        internal_mismatch = sum_of_criteria != report["total_score"]
        hard_error = report.get("flags", "").startswith("SCORING ERROR")
        sanity = report.get("sanity_check", {})
        low_grounding = sanity.get("grounded_fraction", 1.0) < 0.8

        row = {
            "team_id": team_id,
            "total_score": report["total_score"],
            "percentage": report["percentage"],
            "flags": report.get("flags"),
            "grounded_fraction": sanity.get("grounded_fraction"),
            "ungrounded_ids": sanity.get("ungrounded_ids"),
            "internal_sum_mismatch": internal_mismatch,
            "low_grounding": low_grounding,
            "hard_error": hard_error,
        }
        cross_check.append(row)
        print(f"    [OK] {report['total_score']}/{report['max_total']} ({report['percentage']}%) "
              f"grounded={sanity.get('grounded_fraction')} flags={report.get('flags')!r}", file=sys.stderr)

    out_path = pdir / "batch_score_summary.json"
    out_path.write_text(json.dumps(cross_check, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}", file=sys.stderr)

    scored = [r for r in cross_check if "error" not in r and not r.get("hard_error")]
    mismatches = [r for r in cross_check if r.get("low_grounding") or r.get("internal_sum_mismatch")]
    errors = [r for r in cross_check if "error" in r or r.get("hard_error")]

    print(f"\n=== SUMMARY ===", file=sys.stderr)
    print(f"Scored cleanly: {len(scored)}/{len(cross_check)}", file=sys.stderr)
    print(f"Flagged for cross-check (low grounding or internal sum mismatch): {len(mismatches)}", file=sys.stderr)
    for m in mismatches:
        print(f"  - {m['team_id']}: grounded={m.get('grounded_fraction')} "
              f"ungrounded={m.get('ungrounded_ids')} internal_sum_mismatch={m.get('internal_sum_mismatch')}", file=sys.stderr)
    print(f"Errored: {len(errors)}", file=sys.stderr)
    for e in errors:
        print(f"  - {e['team_id']}: {e.get('error') or e.get('flags')}", file=sys.stderr)


if __name__ == "__main__":
    main()
