#!/usr/bin/env python3
"""
scorer.py — AI rubric scoring, generalized across document types.

Was srs_score.py (SRS-only). Test Plan grading needs the same engine --
extract-then-score against a local OpenAI-compatible LLM endpoint, then a
deterministic citation-grounding check -- with a completely different
rubric. Rather than fork a second near-identical file (and now a bug found
in one copy has to be re-found and re-fixed in the other), the *engine* is
shared and the *rubric* is not:

  SHARED (doc-type-agnostic, unchanged from srs_score.py):
    - call_llm(): the retry/JSON-parsing loop against the LLM endpoint.
    - verify_citations(): checks that every ID the model claims to have
      extracted actually appears, verbatim, in the ground-truth extracted
      text. This check means the same thing regardless of what the ID is
      (a requirement ID, a test case ID, ...).
    - build_submission_text(): assembles srs_ingest.py's raw text + tables
      into the prompt body.
    None of this makes a grading judgment -- it's plumbing.

  BESPOKE PER DOC TYPE (this is where the actual grading value lives, and
  it stays fully hand-written, never templated away):
    - RUBRICS[doc_type]["rubric_text"]: the complete grading rubric sent to
      the LLM verbatim, unique to that document type.
    - RUBRICS[doc_type]["criteria"]: the specific criteria and their point
      values. Each criterion has an optional "group" (e.g. a future SADS
      rubric groups criteria under "Architecture"/"Design" subtotals; SRS
      and Test Plan are flat, so every criterion's group is None) -- this
      is the one piece of shared *shape* in the criteria schema, added so
      a doc type with a two-level rubric doesn't require a schema rework,
      not because SRS/Test Plan's criteria are actually grouped.
    - RUBRICS[doc_type]["id_categories"]: what kinds of items PASS 1 should
      extract (e.g. SRS extracts functional/non-functional/security
      requirement IDs; Test Plan extracts test case IDs, SRS requirement
      IDs referenced for traceability, and security validation items).

Usage:
    python3 scorer.py <ingested.json> --doc-type srs --output <score.json>
    python3 scorer.py <ingested.json> --doc-type test_plan --output <score.json>
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3-coder-30b-a3b")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "300"))

# ============================================================
# Bespoke per-doc-type rubrics
# ============================================================

SRS_RUBRIC_TEXT = """
You are an expert Software Engineering professor evaluating a student's Software Requirements Specification (SRS) document.

EVALUATION RUBRIC (Total: 12 marks):

CRITERION "intro" — Introduction & Descriptive Sections (Max: 2 marks)
  Award marks based on completeness and quality of:
  - Section 1: Introduction (Purpose, Scope, Audience/Stakeholders, Definitions)
  - Section 2: Overall Description (Product perspective, functions, user roles, operating environment, constraints)
  - Section 3: External Interface Requirements (User, Hardware, Software, Communication interfaces)
  Scoring: 0=missing/empty, 1=partial (some sections incomplete), 2=complete and well-written

CRITERION "requirements" — Functional & Non-Functional Requirements (Max: 6 marks)
  Requirements MUST be:
  - Clear, unambiguous, concise, and measurable
  - Minimum 10 Functional Requirements (FRs) and 4 Non-Functional Requirements (NFRs)
  Scoring:
  - 0 marks: No requirements or completely empty/template only
  - 1-2 marks: Some requirements listed but poorly written, too few (<5 FRs), or just template headings
  - 3-4 marks: Has requirements (5-9 FRs and/or 2-3 NFRs) but quality issues (vague, unmeasurable)
  - 5 marks: Has >=10 FRs and >=4 NFRs, mostly well-written
  - 6 marks: Has >=10 FRs and >=4 NFRs, all clear/unambiguous/measurable, excellent quality
  Apply the overall grading scale: >=80% criteria met -> full marks for this section; >=50% criteria met -> 60% of marks

CRITERION "uml" — UML Use Case Diagram (Max: 2 marks)
  - 0 marks: No UML diagram described or referenced
  - 1 mark: Mention of use case diagram but vague/minimal
  - 2 marks: At least 1 complete UML use case diagram clearly described or embedded
  NOTE: Diagrams may be images in the document. Look for references like 'Figure', 'Use Case Diagram', or 'UML' AND check the DIAGRAM EVIDENCE section below for structural confirmation (see "Using diagram evidence" instruction).

CRITERION "security" — Security Section (Max: 2 marks)
  Must contain BOTH:
  - At least 2 Security Objectives
  - At least 2 Security Requirements
  Scoring:
  - 0 marks: Security section missing or empty/template only
  - 1 mark: Has either objectives OR requirements but not both, or only 1 of each
  - 2 marks: Has >=2 security objectives AND >=2 security requirements, clearly written

OVERALL GRADING SCALE:
- If 80% or more of criteria for a section are correctly met -> award 100% of available marks for that section
- If 50-79% of criteria met -> award 60% of available marks
- If <50% of criteria met -> proportional marks
"""

TEST_PLAN_RUBRIC_TEXT = """
You are an expert Software Engineering professor evaluating a student's Software Test Plan (STP) document.

EVALUATION RUBRIC (Total: 13 marks):

CRITERION "intro" — Introduction & Descriptive Sections (Max: 2 marks)
  Award marks based on completeness and quality of:
  - Section 1: Introduction (Purpose, Scope, References, Definitions)
  - Section 2: Test Items (which modules/features are under test)
  Scoring: 0=missing/empty, 1=partial (some sections incomplete or generic/template text), 2=complete, project-specific, and well-written

CRITERION "core_sections" — Sections 3/4/5: Features to be Tested, Features Not to be Tested, Test Approach/Strategy (Max: 4 marks)
  All three must be present with content specific to THIS project (not generic placeholder text):
  - Section 3: Features to be Tested — ideally mapped to real SRS requirement IDs (e.g. "ATM-F-001: Validate PIN"), not just vague feature names
  - Section 4: Features Not to be Tested — explicit exclusions with a reason
  - Section 5: Test Approach/Strategy — test levels (unit/integration/system/acceptance), test types (functional/regression/performance/usability), and entry/exit criteria
  Scoring:
  - 0 marks: All three sections missing or template-only
  - 1 mark: Only one of the three sections present with real content
  - 2 marks: Two of the three sections present with real content
  - 3 marks: All three present, but generic (no requirement-ID mapping, vague levels/types, no entry/exit criteria)
  - 4 marks: All three present with project-specific content, features mapped to requirement IDs, clear levels/types and entry/exit criteria

CRITERION "security_validation" — Section 5.1 Security Validation (Max: 1 mark)
  - 0 marks: Section missing entirely
  - 0.5 mark (round to nearest integer per your JSON output, i.e. 0 or 1): Section present but just a heading or one vague line
  - 1 mark: Section present with concrete, project-specific security test activities (e.g. specific fields/flows to fuzz, specific compliance checks, specific auth flows to penetration-test)

CRITERION "traceability" — Traceability to SRS / RTM (Max: 1 mark)
  A Requirements Traceability Matrix or equivalent explicit mapping from SRS requirement IDs to test case IDs must actually exist (e.g. "ATM-F-001 -> TC-Auth-01, TC-Auth-02"), not just a section titled "Traceability" with no real mapping.
  - 0 marks: No traceability section, or a heading with no actual ID-to-ID mapping
  - 1 mark: A real mapping exists between at least several SRS requirement IDs and test case IDs

CRITERION "test_case_coverage" — Test Case Coverage (Max: 5 marks)
  A real test case table/list must exist (Test Case ID, description/steps, expected result at minimum), with at least 7-10 test cases, covering BOTH functional and non-functional requirements.
  Scoring:
  - 0 marks: No test case table/list, or template-only
  - 1 mark: Fewer than 4 test cases, or cases missing steps/expected results
  - 2-3 marks: 4-6 test cases with clear steps and expected results, OR >=7 cases but only covering functional requirements (no NFR test cases) or with vague steps
  - 4 marks: >=7 test cases, clear steps and expected results, covering both functional and non-functional requirements
  - 5 marks: >=10 test cases, excellent coverage of both functional and non-functional requirements, precise steps/expected results, traceable to requirement IDs

OVERALL GRADING SCALE:
- If 80% or more of criteria for a section are correctly met -> award 100% of available marks for that section
- If 50-79% of criteria met -> award 60% of available marks
- If <50% of criteria met -> proportional marks
"""

SADS_RUBRIC_TEXT = """
You are an expert Software Engineering professor evaluating a student's Software Architecture and Design Specification (SADS) document.

EVALUATION RUBRIC (Total: 20 marks, two sections: Architecture=10, Design=10):

--- ARCHITECTURE (10 marks) ---

CRITERION "component_diagram" — Component (UML) Diagram & Descriptions (Max: 4 marks)
  A component/class diagram (Section 3.3, may be an embedded image) PLUS prose descriptions of each component's responsibility (Section 3.4).
  Scoring: 0=missing/template only, 1=only one of diagram-reference or descriptions present, 2=both present but shallow (component names only, no responsibilities), 3=both present with clear per-component responsibilities, 4=both present, clear, and covering every major component of the system described elsewhere in the document
  NOTE: Check the DIAGRAM EVIDENCE section below for structural confirmation — look for a reference/caption ("Figure", "Component Diagram", "Class Diagram") plus the accompanying descriptions (see "Using diagram evidence" instruction).

CRITERION "arch_pattern" — Architecture Pattern & Rationale (Max: 2 marks)
  A named architecture pattern (e.g. layered, microservices, event-driven, client-server) with a rationale for why it was chosen (and ideally what was rejected and why).
  Scoring: 0=no pattern named, 1=pattern named but no rationale, or generic boilerplate rationale, 2=pattern named with a specific, project-grounded rationale

CRITERION "arch_traceability" — Traceability to Requirements (Max: 1 mark)
  An explicit mapping from SRS requirement IDs to architecture components (e.g. "ATM-F-001 (PIN validation) -> Auth Service"), not just a section titled "Traceability" with no real mapping.
  Scoring: 0=no traceability section or no real ID-to-component mapping, 1=a real mapping exists between at least several requirement IDs and components

CRITERION "arch_security" — Security Architecture (Max: 2 marks)
  Concrete security architecture content: threat modeling (e.g. STRIDE), specific mitigations mapped to specific threats, or equivalent (auth/authz design, encryption approach, etc.) — not just a generic "we will use HTTPS" line.
  Scoring: 0=missing/empty, 1=present but generic/shallow (e.g. lists threat categories with no project-specific mitigation), 2=concrete, project-specific threats mapped to concrete mitigations

CRITERION "arch_other" — Other Architecture Sections (Max: 1 mark)
  Goals & constraints, stakeholders & concerns, technology stack & data stores, risks & mitigations — the remaining Section 3 content not covered by the criteria above.
  Scoring: 0=largely missing/template only, 1=present with real, project-specific content

--- DESIGN (10 marks) ---

CRITERION "sequence_diagrams" — UML Sequence Diagrams (Max: 4 marks)
  At least 2 sequence diagrams (may be embedded images), each covering a distinct flow specific to this project (not the template's example flows).
  Scoring: 0=none, 1=only 1 diagram or only vague mentions, 2=2 diagrams present but generic/template-like flows, 3=2 diagrams present covering distinct project-specific flows, 4=>=2 diagrams, clearly project-specific, covering meaningfully different flows (not trivial variations of the same flow)
  NOTE: Check the DIAGRAM EVIDENCE section below for structural confirmation — look for references/captions and the flow description around them (see "Using diagram evidence" instruction).

CRITERION "api_design" — API Design (Max: 3 marks)
  Interface definitions for at least 2 components: endpoint/method, request shape, response shape, and error cases.
  Scoring: 0=no API design content, 1=fewer than 2 endpoints defined, or missing request/response/error detail, 2=>=2 endpoints with request/response but weak or missing error cases, 3=>=2 endpoints, each with request, response, AND concrete error cases

CRITERION "error_handling" — Error Handling, Logging & Monitoring (Max: 2 marks)
  Standardized error handling approach, what gets logged (and what must NOT be logged, e.g. sensitive data), and what gets monitored (specific metrics, not just "we will monitor the system").
  Scoring: 0=missing/empty, 1=present but generic (no specific metrics/log fields), 2=concrete, project-specific error handling, logging, and monitoring content

CRITERION "design_other" — Other Design Sections (Max: 1 mark)
  Design overview, UX design, open issues & next steps — the remaining Section 4 content not covered by the criteria above.
  Scoring: 0=largely missing/template only, 1=present with real, project-specific content

OVERALL GRADING SCALE:
- If 80% or more of criteria for a section are correctly met -> award 100% of available marks for that section
- If 50-79% of criteria met -> award 60% of available marks
- If <50% of criteria met -> proportional marks
"""

RUBRICS = {
    "srs": {
        "max_total": 12,
        "rubric_text": SRS_RUBRIC_TEXT,
        "criteria": [
            {"key": "intro", "label": "Introduction & descriptive sections", "max": 2, "group": None},
            {"key": "requirements", "label": "Functional & non-functional requirements", "max": 6, "group": None},
            {"key": "uml", "label": "UML use case diagram", "max": 2, "group": None},
            {"key": "security", "label": "Security section", "max": 2, "group": None},
        ],
        "id_categories": [
            {"key": "functional_requirements", "label": "Functional Requirements"},
            {"key": "non_functional_requirements", "label": "Non-Functional Requirements"},
            {"key": "security_objectives", "label": "Security Objectives"},
            {"key": "security_requirements", "label": "Security Requirements"},
        ],
    },
    "test_plan": {
        "max_total": 13,
        "rubric_text": TEST_PLAN_RUBRIC_TEXT,
        "criteria": [
            {"key": "intro", "label": "Introduction & descriptive sections", "max": 2, "group": None},
            {"key": "core_sections", "label": "Sections 3/4/5 (Features to/not to be tested, Test Approach)", "max": 4, "group": None},
            {"key": "security_validation", "label": "Section 5.1 Security Validation", "max": 1, "group": None},
            {"key": "traceability", "label": "Traceability to SRS (RTM)", "max": 1, "group": None},
            {"key": "test_case_coverage", "label": "Test case coverage (>=7-10, FR+NFR)", "max": 5, "group": None},
        ],
        "id_categories": [
            {"key": "test_case_ids", "label": "Test Case IDs"},
            {"key": "srs_requirement_ids_referenced", "label": "SRS Requirement IDs referenced (traceability)"},
            {"key": "security_validation_items", "label": "Security Validation items"},
        ],
    },
    # SADS (Software Architecture & Design Spec) -- the one doc type with a
    # real two-level rubric (Architecture=10, Design=10, each with its own
    # sub-criteria). Confirms the "group" field above was enough to add this
    # without a schema rework -- nothing in the shared engine below needed
    # to change.
    "sads": {
        "max_total": 20,
        "rubric_text": SADS_RUBRIC_TEXT,
        "criteria": [
            {"key": "component_diagram", "label": "Component diagram & description", "max": 4, "group": "Architecture"},
            {"key": "arch_pattern", "label": "Architecture pattern", "max": 2, "group": "Architecture"},
            {"key": "arch_traceability", "label": "Traceability to requirements", "max": 1, "group": "Architecture"},
            {"key": "arch_security", "label": "Security architecture", "max": 2, "group": "Architecture"},
            {"key": "arch_other", "label": "Other architecture sections", "max": 1, "group": "Architecture"},
            {"key": "sequence_diagrams", "label": "UML sequence diagrams (>=2)", "max": 4, "group": "Design"},
            {"key": "api_design", "label": "API design", "max": 3, "group": "Design"},
            {"key": "error_handling", "label": "Error handling", "max": 2, "group": "Design"},
            {"key": "design_other", "label": "Other design sections", "max": 1, "group": "Design"},
        ],
        "id_categories": [
            {"key": "requirement_ids_referenced", "label": "Requirement IDs referenced (traceability)"},
            {"key": "api_endpoints", "label": "API endpoints"},
            {"key": "components", "label": "Components named"},
        ],
    },
}

DOC_TYPES = tuple(RUBRICS.keys())


# ============================================================
# Shared engine -- doc-type-agnostic
# ============================================================

DASH_CHARS = "-‐‑‒–—"
_DASH_RE = re.compile(f"[{DASH_CHARS}]")
_WS_RE = re.compile(r"\s+")


def _normalize_id(s: str) -> str:
    """Uppercase, collapse dash variants to '-', and strip ALL whitespace
    (not just leading/trailing) -- PDF table extraction wraps ID cells
    mid-word onto multiple lines (e.g. "A/B-\\nF-\\n001"), so without this
    the grounding check below false-flags every citation from a wrapped
    cell as hallucinated when it's actually a real, correctly-cited ID."""
    s = _DASH_RE.sub("-", (s or "").upper())
    return _WS_RE.sub("", s)


def build_submission_text(ingested: dict) -> str:
    """Assemble srs_ingest.py's raw text + tables into a single text blob for
    the prompt. No section/heading structure to preserve -- the document's
    own paragraph order (raw_text) already reads the way a human skimming it
    would; tables are appended after since PDF/docx text extraction doesn't
    interleave them inline with surrounding paragraphs reliably anyway."""
    lines = [ingested["raw_text"]]
    for t in ingested["tables"]:
        if not t["rows"]:
            continue
        lines.append(f"[table: {', '.join(t['headers'])}]")
        for row in t["rows"]:
            lines.append(" | ".join(f"{k}: {v}" for k, v in row.items() if v))
    return "\n".join(lines)


def _diagram_evidence_text(ingested: dict) -> str:
    """Structural (not semantic) evidence about embedded diagram images,
    from diagram_check.py's OpenCV heuristics -- box/ellipse/line counts
    per image, run at ingest time. This replaces blind "benefit of the
    doubt for diagrams" scoring: a "Figure 3: Use Case Diagram" caption
    next to an image with zero box/line/ellipse structure (e.g. a logo, a
    photo, a blank placeholder) is no longer indistinguishable from a real
    diagram just because both have a caption."""
    images = ingested.get("images", [])
    if not images:
        return ("No embedded raster images of diagram size (>=150x150) were found. "
                 "This does NOT rule out a real diagram -- some documents embed diagrams "
                 "as native vector graphics rather than raster images, which this check "
                 "can't see. Judge from the surrounding text/captions in that case, but "
                 "flag it in 'flags' as unverified.")
    lines = [f"{len(images)} distinct embedded image(s) found (duplicates across pages collapsed); "
              "automated structural analysis of each (box/ellipse/line counts via OpenCV "
              "shape detection -- NOT semantic UML validation, just a structural sanity check):"]
    for i, img in enumerate(images, 1):
        loc = f"page {img['page']}" if "page" in img else "embedded"
        rep = f", repeated on {img['repeated_count']} pages" if img.get("repeated_count", 1) > 1 else ""
        lines.append(
            f"  Image {i} ({loc}{rep}, {img['width']}x{img['height']}): {img['type_guess']} "
            f"[boxes={img['n_boxes']}, ellipses={img['n_ellipses']}, lines={img['n_lines']}, "
            f"has_diagram_structure={img['has_diagram_structure']}]"
        )
    return "\n".join(lines)


def _document_haystack(ingested: dict) -> str:
    """Everything srs_ingest.py extracted, normalized into one blob to check
    citations against -- the same ground truth the model was given, not a
    second, independent parse of it."""
    parts = [ingested.get("raw_text", "")]
    for t in ingested.get("tables", []):
        for row in t.get("rows", []):
            parts.extend(str(v) for v in row.values() if v)
    return _normalize_id("\n".join(parts))


def verify_citations(ingested: dict, result: dict, id_categories: list) -> dict:
    """Sanity check: does every item the model claims to have extracted
    actually appear, verbatim (modulo dash-character/whitespace
    normalization), in the text it was given? This catches hallucinated
    counts deterministically, without relying on a second unreliable
    counter to agree with the first. Doc-type-agnostic: just iterates
    whatever id_categories that rubric declared."""
    haystack = _document_haystack(ingested)
    all_cited = []
    for cat in id_categories:
        all_cited.extend(result.get(f"{cat['key']}_found", None) or [])

    ungrounded = [cid for cid in all_cited if _normalize_id(cid) not in haystack]
    grounded_count = len(all_cited) - len(ungrounded)
    fraction = (grounded_count / len(all_cited)) if all_cited else 1.0

    return {
        "cited_count": len(all_cited),
        "grounded_count": grounded_count,
        "grounded_fraction": round(fraction, 3),
        "ungrounded_ids": ungrounded,
    }


def _build_prompt(doc_type: str, submission_text: str, ingested: dict) -> str:
    cfg = RUBRICS[doc_type]
    criteria = cfg["criteria"]
    id_categories = cfg["id_categories"]

    extract_fields = ",\n".join(
        f'  "{cat["key"]}_found": ["<exact item as it appears>", "..."]' for cat in id_categories
    )
    score_fields = ",\n".join(
        f'  "{c["key"]}_score": <integer 0-{c["max"]}>,\n'
        f'  "{c["key"]}_justification": "<1-2 sentences naming what\'s present/missing>"'
        for c in criteria
    )
    extract_categories = ", ".join(cat["label"] for cat in id_categories)
    diagram_evidence = _diagram_evidence_text(ingested)

    return f"""
{cfg["rubric_text"]}

---
STUDENT SUBMISSION:
{submission_text}
---

DIAGRAM EVIDENCE (automated structural analysis of embedded images, see "Using diagram evidence" instruction below):
{diagram_evidence}
---

Evaluate this document strictly according to the rubric above. Work in two passes:

PASS 1 — EXTRACT. Read the entire submission text and tables above, start to
finish, and list every item you can actually find for each of these
categories: {extract_categories}. Copy each item exactly as it appears in
the text -- do not invent, renumber, or guess items that "should" be there.
Be exhaustive: do not stop after the first few. This extraction is what you
must base your scoring on -- do not silently estimate a round number
("about 10") that isn't backed by what you actually listed.

PASS 2 — SCORE. Using only what you extracted/read (not a guess), score
each criterion. For every criterion where you deduct marks, name the
SPECIFIC missing or weak element in the justification (e.g. "no Scope
subsection", "only 4 test cases found, need >=7", "traceability section
present but has no actual ID-to-ID mapping") -- a justification that just
restates the score without saying what's actually wrong is not acceptable.

IMPORTANT INSTRUCTIONS:
1. If the document appears to be an unfilled template (placeholder text like "<< >>", "[description here]", "TBD", or just section headings with no actual content), award 0 for those sections and say so explicitly.
2. Be strict but fair.
3. Using diagram evidence: a "Figure"/"UML"/diagram caption in the text is NOT by itself proof of a real diagram -- cross-check it against the DIAGRAM EVIDENCE section. An image with has_diagram_structure=true and a type_guess consistent with what the caption claims (e.g. caption says "Use Case Diagram" and the evidence says "use-case-like") is real corroborating evidence -- score normally/generously for that criterion. A caption with NO corresponding image, or only images with has_diagram_structure=false ("no diagram-like structure detected"), means the diagram is NOT confirmed -- do not award full marks on caption text alone; treat it like the "vague/minimal" or "missing" scoring tier for that criterion. This is a structural heuristic (box/line/ellipse counts), not full UML correctness checking, so still use judgment on borderline cases -- but stop defaulting to full benefit of the doubt.
4. If the DIAGRAM EVIDENCE section reports no images at all (not even unstructured ones) despite the text repeatedly describing/referencing specific diagrams in detail, that's the "vector graphics not raster" edge case noted in the evidence section -- use reasonable judgment from the text description, but say so in "flags" so it can be spot-checked manually.
5. If anything about the submission itself looks off (duplicated blocks, suspiciously templated language, truncated content), note it in "flags". Otherwise "flags" is "None".

Respond ONLY in this exact JSON format (no other text before or after):
{{
{extract_fields},
{score_fields},
  "total_score": <integer 0-{cfg["max_total"]}>,
  "percentage": <float 0-100>,
  "overall_feedback": "<2-3 sentences of constructive feedback for the student>",
  "flags": "<anything that looks off about the submission itself, or 'None'>"
}}
"""


def call_llm(prompt: str) -> dict:
    """POST to the OpenAI-compatible /v1/chat/completions endpoint, retrying
    on transient failures or malformed JSON."""
    last_err = None
    for attempt in range(3):
        try:
            response = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                },
                timeout=LLM_TIMEOUT,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"].strip()

            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                raise ValueError(f"no JSON found in response: {raw[:300]}")
            return json.loads(json_match.group())
        except Exception as e:  # noqa: BLE001 - broad retry, mirrors prior behavior
            last_err = e
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError(f"LLM call failed after 3 attempts: {last_err}")


def score(ingested: dict, doc_type: str) -> dict:
    if doc_type not in RUBRICS:
        raise ValueError(f"unknown doc_type {doc_type!r}, expected one of {DOC_TYPES}")
    cfg = RUBRICS[doc_type]
    criteria_cfg = cfg["criteria"]
    id_categories = cfg["id_categories"]

    submission_text = build_submission_text(ingested)
    prompt = _build_prompt(doc_type, submission_text, ingested)

    try:
        result = call_llm(prompt)
        error = None
    except Exception as e:  # noqa: BLE001
        result = {}
        error = str(e)

    criteria = []
    total = 0
    for c in criteria_cfg:
        raw_score = result.get(f"{c['key']}_score", 0)
        try:
            clamped = max(0, min(c["max"], int(raw_score)))
        except (TypeError, ValueError):
            clamped = 0
        total += clamped
        criteria.append({
            "key": c["key"],
            "label": c["label"],
            "max": c["max"],
            "group": c.get("group"),
            "score": clamped,
            "justification": result.get(f"{c['key']}_justification", ""),
        })

    extracted_ids = {cat["key"]: result.get(f"{cat['key']}_found", []) for cat in id_categories}

    sanity = verify_citations(ingested, result, id_categories) if not error else {
        "cited_count": 0, "grounded_count": 0, "grounded_fraction": 1.0, "ungrounded_ids": [],
    }

    flags = result.get("flags", "None" if not error else f"SCORING ERROR: {error}")
    if sanity["ungrounded_ids"]:
        sample = ", ".join(sanity["ungrounded_ids"][:5])
        note = (f"UNGROUNDED CITATIONS: {len(sanity['ungrounded_ids'])}/{sanity['cited_count']} "
                f"cited item(s) not found verbatim in extracted text (e.g. {sample}) "
                f"-- possible hallucination, verify manually.")
        flags = note if flags in ("None", "") else f"{flags} | {note}"

    return {
        "source": ingested["source"],
        "doc_type": doc_type,
        "extracted_ids": extracted_ids,
        "criteria": criteria,
        "total_score": total,
        "max_total": cfg["max_total"],
        "percentage": round(total / cfg["max_total"] * 100, 1),
        "overall_feedback": result.get("overall_feedback", ""),
        "flags": flags,
        "sanity_check": sanity,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ingested_json")
    ap.add_argument("--doc-type", choices=DOC_TYPES, required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--show-prompt", action="store_true", help="print the exact prompt sent to the LLM and exit, no API call")
    args = ap.parse_args()

    ingested = json.loads(Path(args.ingested_json).read_text(encoding="utf-8"))

    if args.show_prompt:
        print(_build_prompt(args.doc_type, build_submission_text(ingested), ingested))
        return

    report = score(ingested, args.doc_type)

    out = args.output or str(Path(args.ingested_json).with_name(
        Path(args.ingested_json).stem.replace("_ingested", "") + "_score.json"))
    Path(out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"{report['source']}: {report['total_score']}/{report['max_total']} ({report['percentage']}%)", file=sys.stderr)
    print(f"  flags: {report['flags']}", file=sys.stderr)
    print(f"  sanity: {report['sanity_check']}", file=sys.stderr)
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
