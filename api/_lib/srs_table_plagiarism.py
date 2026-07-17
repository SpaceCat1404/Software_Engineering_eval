#!/usr/bin/env python3
"""
srs_table_plagiarism.py — row-level plagiarism for SRS requirement tables.

Extends the existing plagiarism.py rather than replacing it:
  - reuses shingles() / jaccard() / structural_similarity() as-is
  - drops the CNS pipeline's image-hash steps entirely (no screenshots here)
  - adds one new comparison unit: the REQUIREMENT ROW, not the whole document

Why row-level, not whole-doc:
SRS req tables are heavily templated (fixed columns: Req ID, Requirement,
Type, Priority, ...). Two students who each wrote their own project can
still have near-identical requirement TEXT (copy-pasted rows, or both
copied from the same source) while their Req IDs differ by project prefix
("ATM-F-001" vs "LMS-F-001") and their surrounding prose differs enough
that whole-document Jaccard/structural similarity stays under threshold.
Comparing at row granularity, on the Requirement text alone, catches this
directly — and tells you WHICH rows were copied, not just "these two docs
are somewhat similar."

Run AFTER srs_ingest.py. Reads every *_ingested.json under --students-dir.

Scale note: this is built for small cohorts (~16-20 team submissions, not
100+ individual CNS labs). Full pairwise row x row comparison is
C(20,2) x ~25 rows^2 ~= well under 1M comparisons -- milliseconds. No
bucket-then-drilldown staging needed; that would only pay for itself at
much larger n. What DOES still matter at any scale is false positives from
generic SRS boilerplate phrasing ("the system shall authenticate the user
via username and password") that two teams write independently -- see
COMMON_ROW_MIN_TEAMS below, same idea as the image pipeline's
find_common_images / COMMON_IMAGE_MIN_STUDENTS.

Usage:
    python3 srs_table_plagiarism.py --students-dir pipeline_out/students
"""
import argparse
import itertools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from plagiarism import shingles, jaccard, structural_similarity, WORD_RE  # noqa: E402

ROW_JACCARD_THRESHOLD = 0.55       # rows are short, so require a tighter match than whole-doc
ROW_STRUCTURAL_THRESHOLD = 0.70
MIN_ROW_WORDS = 5                  # skip near-empty/placeholder rows ("TBD", "-")
REQUIREMENT_COL_ALIASES = ["requirement", "requirement (shall...)", "requirement short"]
# Compared with whitespace stripped -- PDF-table extraction wraps header text
# mid-word ("Requireme\nnt"), so a plain lower/strip match misses it.
REQUIREMENT_COL_ALIASES_NORM = {a.replace(" ", "") for a in REQUIREMENT_COL_ALIASES}

# A requirement row that near-matches rows from at least this many DIFFERENT
# teams is treated as generic SRS boilerplate (common phrasing for "shall
# authenticate", "shall log", "shall encrypt at rest", etc.) rather than
# evidence of copying between any one pair, and is excluded from flagging.
# With only 16-20 teams total, 3 means "roughly a sixth of the cohort
# independently wrote near-identical wording" -- tune down to 2 for smaller
# cohorts.
COMMON_ROW_MIN_TEAMS = 3

# Strips project-specific req-ID-style tokens so "ATM-F-001 shall..." and
# "LMS-F-001 shall..." aren't scored as different just because of the prefix,
# if a student pasted the ID inline into the requirement text itself.
ID_TOKEN_RE = re.compile(r"\b[A-Za-z]{2,6}-(?:F|NF|SEC)-\d{2,4}\b", re.IGNORECASE)


def requirement_col(headers: list) -> str | None:
    norm = {re.sub(r"\s+", "", h.lower()): h for h in headers}
    for alias in REQUIREMENT_COL_ALIASES_NORM:
        if alias in norm:
            return norm[alias]
    return None


def extract_rows(ingested: dict) -> list:
    """Returns [{'table_idx': ..., 'row_idx': ..., 'req_id': ...,
    'text': normalized requirement text}, ...] across the whole document.
    No section grouping anymore (srs_ingest.py's tables are a flat,
    document-order list) -- row-level plagiarism never needed the section a
    row lived in, only the row text itself."""
    out = []
    for ti, t in enumerate(ingested["tables"]):
        if not t["req_id_col"]:
            continue
        col = requirement_col(t["headers"])
        if not col:
            continue
        for ri, row in enumerate(t["rows"]):
            text = ID_TOKEN_RE.sub("", row.get(col, "")).strip()
            if len(text.split()) < MIN_ROW_WORDS:
                continue
            out.append({
                "table_idx": ti, "row_idx": ri,
                "req_id": row.get(t["req_id_col"], "?"), "text": text,
            })
    return out


def row_pair_matches(row_a: dict, row_b: dict, shingle_sets_a, shingle_sets_b) -> tuple | None:
    jac, _ = jaccard(shingle_sets_a, shingle_sets_b)
    struct = structural_similarity(WORD_RE.findall(row_a["text"].lower()),
                                    WORD_RE.findall(row_b["text"].lower()))
    if jac >= ROW_JACCARD_THRESHOLD or struct >= ROW_STRUCTURAL_THRESHOLD:
        return round(jac, 3), round(struct, 3)
    return None


def find_common_rows(students: list, all_rows: list, shingle_sets: list) -> set:
    """Returns the set of (student_idx, row_idx) pairs whose text near-matches
    rows owned by >= COMMON_ROW_MIN_TEAMS DIFFERENT teams -- generic SRS
    boilerplate, not evidence of copying between any one pair. Mirrors
    find_common_images() in the image pipeline exactly."""
    n = len(students)
    flat = [(i, ri) for i in range(n) for ri in range(len(all_rows[i]))]
    common = set()
    for i, ri in flat:
        owners = {i}
        for j, rj in flat:
            if j == i:
                continue
            if row_pair_matches(all_rows[i][ri], all_rows[j][rj],
                                 shingle_sets[i][ri], shingle_sets[j][rj]):
                owners.add(j)
        if len(owners) >= COMMON_ROW_MIN_TEAMS:
            common.add((i, ri))
    return common


def compare_students(students: list) -> dict:
    """students: [(stem, ingested_dict), ...]"""
    all_rows = [extract_rows(sj) for _, sj in students]
    shingle_sets = [[shingles(r["text"]) for r in rows] for rows in all_rows]
    n = len(students)

    common = find_common_rows(students, all_rows, shingle_sets)
    if common:
        print(f"  [filter] {len(common)} row(s) near-matched across "
              f">= {COMMON_ROW_MIN_TEAMS} different teams -- treated as "
              f"boilerplate, excluded from flagging.", file=sys.stderr)

    flagged = []
    for i, j in itertools.combinations(range(n), 2):
        stem_a, stem_b = students[i][0], students[j][0]
        for ri, row_a in enumerate(all_rows[i]):
            if (i, ri) in common:
                continue
            for rj, row_b in enumerate(all_rows[j]):
                if (j, rj) in common:
                    continue
                scores = row_pair_matches(row_a, row_b, shingle_sets[i][ri], shingle_sets[j][rj])
                if scores is None:
                    continue
                jac, struct = scores
                flagged.append({
                    "student_a": stem_a, "student_b": stem_b,
                    "req_id_a": row_a["req_id"], "req_id_b": row_b["req_id"],
                    "text_a": row_a["text"], "text_b": row_b["text"],
                    "jaccard": jac, "structural_similarity": struct,
                })

    by_student = {}
    for f in flagged:
        for stem, other in ((f["student_a"], f["student_b"]), (f["student_b"], f["student_a"])):
            by_student.setdefault(stem, set()).add(other)

    return {
        "students_checked": n,
        "common_rows_excluded": len(common),
        "flagged_row_pair_count": len(flagged),
        "flagged_pairs": flagged,
        "flagged_students": {k: sorted(v) for k, v in by_student.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--students-dir", default="pipeline_out/students")
    ap.add_argument("--output", default="pipeline_out/table_plagiarism_report.json")
    args = ap.parse_args()

    files = sorted(Path(args.students_dir).rglob("*_ingested.json"))
    if not files:
        print(f"ERROR: no *_ingested.json under {args.students_dir}", file=sys.stderr)
        sys.exit(1)

    students = [(fp.stem.replace("_ingested", ""), json.loads(fp.read_text(encoding="utf-8")))
                for fp in files]
    print(f"Loaded {len(students)} submissions.", file=sys.stderr)

    report = compare_students(students)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['flagged_row_pair_count']} row pair(s) flagged across "
          f"{len(report['flagged_students'])} student(s). Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
