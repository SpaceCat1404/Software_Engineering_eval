#!/usr/bin/env python3
"""
srs_ingest.py — extract a student SRS .docx/.pdf into structured JSON.

Output shape:
{
  "source": "<filename>",
  "raw_text": "<every non-table line of the document, one per line, in
               document order -- headings included as plain text>",
  "tables": [
    {
      "headers": ["Req ID", "Requirement", ...],
      "rows": [ {"Req ID": "ATM-F-001", "Requirement": "...", ...}, ... ],
      "req_id_col": "Req ID",   # None if this table isn't a requirements table
      "n_data_rows": 3
    },
    ...
  ]
}

No heading/section detection. An earlier version of this module tried to
reconstruct document structure (Heading 1/2/3 styles for docx, a font-size/
numbering heuristic for PDF) so downstream checks could group content by
section ("does this doc have a Security Requirements section, and is it
long enough"). That approach doesn't generalize across real student
submissions -- two real bugs found on 2026-07-15 alone were both
section-detection failures: one PDF's headings had no bold/size
distinction from body text at all (nothing to key off), and unrelatedly, a
different doc's requirement lines used ":" instead of "-" and silently
undercounted. Rather than keep patching a heuristic that keeps finding new
ways to be wrong on formatting it wasn't tuned against, section detection
is dropped entirely: this module just extracts raw text + tables, srs_
completeness.py counts requirements globally by ID marker (no section
needed -- the marker already encodes FR/NFR/security), and srs_score.py's
LLM rubric judges descriptive-section presence/quality directly from the
full raw text instead of trusting a heading-matcher to have found the
right boundaries.

Usage:
    python3 srs_ingest.py <docx_or_pdf_path> --output-dir <dir>
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import docx
import fitz  # PyMuPDF
from docx.table import Table
from docx.text.paragraph import Paragraph

import diagram_check

REQ_ID_HEADER_ALIASES = {"req id", "requirement id", "reqid", "id"}
# Compared with all whitespace stripped -- PDF table extraction wraps header
# text mid-word ("Req\nID", "Requireme\nnt"), so a plain lower/strip match
# misses real requirement tables entirely.
REQ_ID_HEADER_ALIASES_NORM = {a.replace(" ", "") for a in REQ_ID_HEADER_ALIASES}


def normalize_header(h: str) -> str:
    return re.sub(r"\s+", "", h.lower())

# Matches bulleted requirement lines like "HCM-F-001 — The system shall..."
# or "PWM-SR-001 - TLS 1.2+ mandatory...": an ID token (2-8 letter prefix,
# F/NF/SEC/SR marker, 2-4 digit number) followed by a separator and the text.
# Word/PDF exports often use non-breaking hyphens (U+2011) inside the ID
# itself ("HCM‑F‑001"), so DASH_CHARS covers both separator and ID dashes.
DASH_CHARS = "-‐‑‒–—"
# Some submissions use a colon instead of a dash between the ID and the
# requirement text ("UAAS-F-001: Validate credentials...", "GDPR-F-001: The
# system shall..."). Found via cross-checking the LLM scorer's "COUNT
# MISMATCH" flags against a 0-FR parse on two real submissions that plainly
# had 15-20 well-formed requirements -- the old dash-only separator silently
# dropped every one of them. SEP_CHARS is only for the ID/text separator;
# the ID's own internal dashes are still DASH_CHARS-only (colons never
# appear inside an ID like "HCM-F-001").
SEP_CHARS = DASH_CHARS + ":"
REQ_LINE_RE = re.compile(
    rf"^[•●▪\s]*([A-Za-z]{{2,8}}[{DASH_CHARS}](?:F|NF|SEC|SO|SR)[{DASH_CHARS}]\d{{2,4}})"
    rf"\s*(?:\([^)]*\)\s*)?[{SEP_CHARS}]\s*(.+)$"
)


def table_to_dict(t: Table) -> dict:
    rows = [[c.text.strip() for c in r.cells] for r in t.rows]
    if not rows:
        return {"headers": [], "rows": [], "req_id_col": None, "n_data_rows": 0}
    headers = rows[0]
    data_rows = rows[1:]
    req_id_col = None
    for h in headers:
        if normalize_header(h) in REQ_ID_HEADER_ALIASES_NORM:
            req_id_col = h
            break
    dict_rows = []
    for r in data_rows:
        # skip fully-blank rows (leftover template rows the student didn't fill)
        if not any(cell for cell in r):
            continue
        dict_rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
    return {
        "headers": headers,
        "rows": dict_rows,
        "req_id_col": req_id_col,
        "n_data_rows": len(dict_rows),
    }


def _make_synthetic_table() -> dict:
    return {"headers": ["Req ID", "Requirement"], "rows": [], "req_id_col": "Req ID", "n_data_rows": 0}


def ingest_docx(docx_path: Path) -> dict:
    d = docx.Document(str(docx_path))
    text_lines = []
    tables = []
    synthetic = _make_synthetic_table()

    for el in d.iter_inner_content():
        if isinstance(el, Paragraph):
            text = el.text.strip()
            if not text:
                continue
            text_lines.append(text)
            m = REQ_LINE_RE.match(text)
            if m:
                req_id = re.sub(f"[{DASH_CHARS}]", "-", m.group(1))
                synthetic["rows"].append({"Req ID": req_id, "Requirement": m.group(2).strip()})
                synthetic["n_data_rows"] += 1
        elif isinstance(el, Table):
            tables.append(table_to_dict(el))

    if synthetic["rows"]:
        tables.append(synthetic)

    result = {"source": docx_path.name, "raw_text": "\n".join(text_lines), "tables": tables}
    images = diagram_check.extract_and_analyze(docx_path)
    if images:
        result["images"] = images
    return result


def pdf_table_to_dict(rows: list) -> dict:
    rows = [[(c or "").strip() for c in r] for r in rows]
    if not rows:
        return {"headers": [], "rows": [], "req_id_col": None, "n_data_rows": 0}
    raw_headers = rows[0]
    data_rows = rows[1:]

    req_id_idx = None
    for i, h in enumerate(raw_headers):
        if normalize_header(h) in REQ_ID_HEADER_ALIASES_NORM:
            req_id_idx = i
            break

    # Column labels used as dict keys below -- fall back to a positional
    # label ("Column N") for any blank header cell, and disambiguate repeats,
    # so cells never collide onto the same key and get silently dropped.
    # Found on a real submission where every header cell was a blank icon
    # (not text): every row's dict comprehension was collapsing 10 real
    # columns down to 1 because they all keyed to "".
    seen = {}
    headers = []
    for i, h in enumerate(raw_headers):
        label = h if h else f"Column {i + 1}"
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            label = f"{label} ({seen[label]})"
        headers.append(label)

    req_id_col = headers[req_id_idx] if req_id_idx is not None else None

    dict_rows = []
    for r in data_rows:
        if not any(cell for cell in r):
            continue
        dict_rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
    return {
        "headers": headers,
        "rows": dict_rows,
        "req_id_col": req_id_col,
        "n_data_rows": len(dict_rows),
    }


def _looks_like_header_row(row: list) -> bool:
    return any(normalize_header(c or "") in REQ_ID_HEADER_ALIASES_NORM for c in row)


def _merge_as_continuation(tables: list, raw_rows: list) -> bool:
    """find_tables() runs per page, so a requirements table whose rows spill
    onto the next page comes back as a second, unrelated Table object -- and
    its first (data) row gets parsed as a header by pdf_table_to_dict(),
    corrupting the column mapping and silently mislabeling/dropping rows
    (seen in the wild: a 5-row NFR table split 2+3 across a page break came
    out as "2 NFR rows found"). If the most recently appended table has the
    same column count and this table's first row doesn't look like a header
    (no Req-ID-alias cell in it), treat every row here as continuation data
    appended to that table instead of parsing a new one."""
    if not tables or not raw_rows:
        return False
    prev = tables[-1]
    headers = prev["headers"]
    if not headers or len(raw_rows[0]) != len(headers) or _looks_like_header_row(raw_rows[0]):
        return False
    req_id_idx = headers.index(prev["req_id_col"]) if prev["req_id_col"] else None
    for r in raw_rows:
        r = [(c or "").strip() for c in r]
        if not any(r):
            continue
        # A row whose Req-ID cell is blank is the wrapped-text tail of the
        # previous page's last row (find_tables() sometimes splits a
        # word-wrapped cell into its own phantom row at the page boundary),
        # not a genuine new requirement -- skip it rather than counting it.
        if req_id_idx is not None and not r[req_id_idx]:
            continue
        prev["rows"].append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
    prev["n_data_rows"] = len(prev["rows"])
    return True


# A page below this many real (non-whitespace) characters from normal text
# extraction is treated as "nothing here" and retried via OCR -- catches
# scanned/image-only pages (0 chars) and pages where PyMuPDF only recovers
# garbage/incidental text (e.g. a handful of bullet glyphs, a title-page
# fragment) while the actual content is a flattened image. A real body page
# is always well over this even at just a heading.
OCR_MIN_PAGE_CHARS = 40


def _tessdata_dir() -> str | None:
    """Locate Tesseract's tessdata folder so PyMuPDF's OCR can find trained
    language data even when it isn't on PATH/registered where PyMuPDF looks
    by default -- confirmed necessary on this machine (UB Mannheim installer
    puts it in Program Files but get_textpage_ocr() without an explicit path
    still raised 'Tesseract is not installed')."""
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).exists():
        return env
    exe = shutil.which("tesseract")
    if exe:
        candidate = Path(exe).parent / "tessdata"
        if candidate.exists():
            return str(candidate)
    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


_TESSDATA_DIR = _tessdata_dir()


def _page_text_lines(page, textpage=None) -> list:
    """(line_text, line_bbox) pairs for every real text line on a page, read
    from the given textpage (or the page's own, if None)."""
    lines = []
    for block in page.get_text("dict", textpage=textpage)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            line_text = "".join(s["text"] for s in spans).strip()
            lines.append((line_text, fitz.Rect(line["bbox"])))
    return lines


def ingest_pdf(pdf_path: Path) -> dict:
    doc = fitz.open(str(pdf_path))
    text_lines = []
    tables = []
    synthetic = _make_synthetic_table()
    ocr_pages = []

    for page_num, page in enumerate(doc):
        found_tables = list(page.find_tables().tables)
        table_rects = [(fitz.Rect(t.bbox), t) for t in found_tables]
        used_tables = set()

        lines = _page_text_lines(page)
        if sum(len(t) for t, _ in lines) < OCR_MIN_PAGE_CHARS and _TESSDATA_DIR:
            try:
                ocr_textpage = page.get_textpage_ocr(flags=0, full=True, tessdata=_TESSDATA_DIR)
                ocr_lines = _page_text_lines(page, textpage=ocr_textpage)
            except Exception:
                ocr_lines = []
            if sum(len(t) for t, _ in ocr_lines) > sum(len(t) for t, _ in lines):
                lines = ocr_lines
                table_rects = []  # OCR text has no real vector table structure to align against
                ocr_pages.append(page_num + 1)

        for line_text, line_bbox in lines:
            in_table = next((t for rect, t in table_rects if rect.intersects(line_bbox)), None)
            if in_table is not None:
                if id(in_table) not in used_tables:
                    used_tables.add(id(in_table))
                    raw_rows = in_table.extract()
                    if not _merge_as_continuation(tables, raw_rows):
                        tables.append(pdf_table_to_dict(raw_rows))
                continue

            m = REQ_LINE_RE.match(line_text)
            if m:
                req_id = re.sub(f"[{DASH_CHARS}]", "-", m.group(1))
                synthetic["rows"].append({"Req ID": req_id, "Requirement": m.group(2).strip()})
                synthetic["n_data_rows"] += 1
            text_lines.append(line_text)

    if synthetic["rows"]:
        tables.append(synthetic)

    result = {"source": pdf_path.name, "raw_text": "\n".join(text_lines), "tables": tables}
    if ocr_pages:
        result["ocr_pages"] = ocr_pages
    images = diagram_check.extract_and_analyze(pdf_path)
    if images:
        result["images"] = images
    return result


def ingest(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return ingest_pdf(path)
    return ingest_docx(path)


_RESUBMISSION_SUFFIX_RE = re.compile(r"^(.*?)\s*\((\d+)\)$")


def resolve_team_id(filename_stem: str) -> tuple:
    """Split a filename stem into (team_id, resubmission_rank) for duplicate-
    submission handling. A file re-uploaded/re-downloaded by the OS or an
    LMS commonly gets an appended " (1)", " (2)", ... suffix -- strip it so
    "Team A.pdf" and "Team A (1).pdf" resolve to the same team_id, and rank
    the suffix so a higher number (assumed to be the later resubmission)
    outranks a lower one, which in turn outranks no suffix at all (rank -1).
    Doesn't attempt to match genuinely different filenames for the same
    student (e.g. a renamed resubmission) -- that needs a human, not a
    filename heuristic."""
    m = _RESUBMISSION_SUFFIX_RE.match(filename_stem)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return filename_stem, -1


def dedupe_by_team_id(paths: list) -> tuple:
    """Given a list of submission file paths, group by resolve_team_id()'s
    base team_id and keep only the highest-ranked (latest resubmission) file
    per team. Returns (winners, skipped) where winners is [(team_id, path),
    ...] in the same relative order as the input, and skipped is
    [(team_id, path, reason), ...] for every lower-ranked duplicate that was
    NOT ingested."""
    groups: dict = {}
    for p in paths:
        team_id, rank = resolve_team_id(p.stem)
        groups.setdefault(team_id, []).append((rank, p))

    winners = []
    skipped = []
    for team_id, entries in groups.items():
        entries.sort(key=lambda e: e[0])
        best_rank, best_path = entries[-1]
        for rank, p in entries[:-1]:
            skipped.append((team_id, p, f"superseded by {best_path.name} (resubmission rank {rank} < {best_rank})"))
        winners.append((team_id, best_path))

    order = {p: i for i, p in enumerate(paths)}
    winners.sort(key=lambda w: order[w[1]])
    return winners, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path")
    ap.add_argument("--output-dir", default=".")
    args = ap.parse_args()

    input_path = Path(args.input_path)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ingest(input_path)
    out_path = out_dir / f"{input_path.stem}_ingested.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}  ({len(result['raw_text'].splitlines())} lines, "
          f"{len(result['tables'])} tables)", file=sys.stderr)


if __name__ == "__main__":
    main()
