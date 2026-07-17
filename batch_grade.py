#!/usr/bin/env python3
"""
batch_grade.py — ingest a whole folder of student submissions in one run.

Local/CLI counterpart to the web app's one-file-at-a-time upload flow: point
it at a folder (e.g. student_submissions/SRS_responses), and it ingests
every .docx/.pdf in it. No Blob storage, no Vercel — everything reads from
and writes to the local filesystem. Run batch_score.py separately for the
AI rubric score (see scorer.py).

Row-level plagiarism checking (srs_table_plagiarism.py) is no longer run
automatically here -- it's been dropped from the default flow (judged
unlikely to matter / not worth maintaining as a first-class feature), but
the checker itself is untouched and still available. Pass --plagiarism to
run it anyway (SRS only -- it keys off SRS's requirement-row shape).

Usage:
    python3 batch_grade.py student_submissions/SRS_responses --doc-type srs --output-dir pipeline_out
    python3 batch_grade.py student_submissions/test_plan_responses --doc-type test_plan --output-dir pipeline_out
"""
import argparse
import json
import sys
from pathlib import Path

from srs_ingest import ingest

SUPPORTED = {".docx", ".pdf"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submissions_dir")
    ap.add_argument("--doc-type", choices=["srs", "test_plan"], default="srs")
    ap.add_argument("--output-dir", default="pipeline_out")
    ap.add_argument("--plagiarism", action="store_true",
                     help="also run the row-level plagiarism check (SRS only, opt-in)")
    args = ap.parse_args()

    if args.plagiarism and args.doc_type != "srs":
        print("ERROR: --plagiarism only supports --doc-type srs "
              "(it keys off SRS's requirement-row table shape)", file=sys.stderr)
        sys.exit(1)

    submissions_dir = Path(args.submissions_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in submissions_dir.iterdir()
        if p.suffix.lower() in SUPPORTED
    )
    if not files:
        print(f"ERROR: no .docx/.pdf files found under {submissions_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(files)} submission(s) in {submissions_dir}.", file=sys.stderr)

    students = []
    summary = []
    for fp in files:
        team_id = fp.stem
        try:
            ingested = ingest(fp)
        except Exception as e:
            print(f"  [SKIP] {fp.name}: could not parse ({e})", file=sys.stderr)
            summary.append({"team_id": team_id, "file": fp.name, "error": str(e)})
            continue

        (out_dir / f"{team_id}_ingested.json").write_text(json.dumps(ingested, indent=2), encoding="utf-8")

        students.append((team_id, ingested))
        summary.append({
            "team_id": team_id, "file": fp.name,
            "lines": len(ingested["raw_text"].splitlines()),
            "tables": len(ingested["tables"]),
        })
        print(f"  [OK]   {fp.name}: {len(ingested['raw_text'].splitlines())} lines, "
              f"{len(ingested['tables'])} tables", file=sys.stderr)

    summary_path = out_dir / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}", file=sys.stderr)

    if args.plagiarism:
        from srs_table_plagiarism import compare_students
        if len(students) >= 2:
            report = compare_students(students)
            report_path = out_dir / "table_plagiarism_report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"{report['flagged_row_pair_count']} row pair(s) flagged across "
                  f"{len(report['flagged_students'])} student(s). Wrote {report_path}", file=sys.stderr)
        else:
            print("Fewer than 2 successfully-ingested submissions — skipping plagiarism check.", file=sys.stderr)


if __name__ == "__main__":
    main()
