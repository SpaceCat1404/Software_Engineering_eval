#!/usr/bin/env python3
"""
diagram_check.py — structural evidence extraction for embedded diagram images.

Presence of an image isn't evidence it's a real UML diagram (a logo, a
screenshot of code, or a photo would all pass a naive "has an image"
check) -- and until now scorer.py just told the LLM to "give benefit of
the doubt" for any "Figure"/"UML" caption in the text, whether or not a
real diagram backed it. This module extracts every embedded raster image
from a docx/pdf and runs cheap OpenCV structural heuristics against each
one -- line/box/ellipse counts via Hough transforms and contour analysis
-- to produce a per-image evidence summary the scorer can actually weigh.

This is NOT semantic UML validation (it can't tell a Class diagram from a
Component diagram, or check an arrow points the "correct" direction per
UML notation) -- it's a structural sanity check: does this image contain
box/line/ellipse structure consistent with SOME kind of diagram, or is it
blank/photographic/pure-text with no diagram-like structure at all. Also
only catches diagrams embedded as raster images (PNG/JPEG) -- a diagram
drawn as native vector paths (e.g. some draw.io/Visio PDF exports) won't
be picked up by get_images() at all, so an empty result isn't proof there's
no diagram, just that this check found no raster evidence either way.
"""
import hashlib
from pathlib import Path

import cv2
import numpy as np

# Images smaller than this in either dimension are almost always logos,
# icons, or decorative header/footer art, not diagrams -- skip them so
# they don't dilute or falsely satisfy the diagram-evidence check.
MIN_DIAGRAM_DIM = 150

# Contours smaller than this fraction of the image area are noise (font
# serifs, jpeg artifacts, gridline corners), not a real box/shape in a
# diagram.
MIN_CONTOUR_AREA_FRACTION = 0.0005


def _extract_pdf_images(pdf_path: Path) -> list:
    import fitz
    doc = fitz.open(str(pdf_path))
    images = []
    for page_num, page in enumerate(doc):
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:  # CMYK/other -> convert to RGB first
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                if pix.width < MIN_DIAGRAM_DIM or pix.height < MIN_DIAGRAM_DIM:
                    continue
                images.append((page_num + 1, pix.tobytes("png")))
            except Exception:
                continue
    return images


def _extract_docx_images(docx_path: Path) -> list:
    import docx
    d = docx.Document(str(docx_path))
    images = []
    for rel in d.part.rels.values():
        if "image" not in rel.reltype:
            continue
        try:
            images.append((None, rel.target_part.blob))
        except Exception:
            continue
    return images


def analyze_image(image_bytes: bytes) -> dict | None:
    """Decode one image and score its structure. Returns None for anything
    cv2 can't decode (e.g. EMF/WMF vector blobs Word sometimes embeds) or
    that's too small -- callers should treat that the same as "no evidence
    either way", not "confirmed not a diagram"."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w < MIN_DIAGRAM_DIM or h < MIN_DIAGRAM_DIM:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = round(float(edges.mean() / 255), 4)

    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=40,
        minLineLength=max(20, min(w, h) * 0.03), maxLineGap=5,
    )
    n_lines = 0 if lines is None else len(lines)

    min_area = w * h * MIN_CONTOUR_AREA_FRACTION
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    n_boxes = 0
    n_ellipses = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            n_boxes += 1
        elif len(c) >= 5:
            # Ellipses (use-case ovals, actor heads, interface "lollipops")
            # don't approxPolyDP down to a fixed vertex count, so fit an
            # ellipse to the contour and check the fit is tight (contour
            # area close to the fitted ellipse's area) rather than boxy.
            try:
                (_, _), (major, minor), _ = cv2.fitEllipse(c)
                ellipse_area = np.pi * (major / 2) * (minor / 2)
                if ellipse_area > 0 and 0.7 < area / ellipse_area < 1.3 and len(approx) > 5:
                    n_ellipses += 1
            except cv2.error:
                pass

    has_structure = n_boxes >= 2 or n_ellipses >= 2 or n_lines >= 15
    aspect_ratio = w / h

    # Sequence diagrams and component/class diagrams both show up as
    # "many boxes + many lines" to the box/line counts alone (participant
    # headers are boxes too), so they're not separable on those counts by
    # themselves. Aspect ratio breaks the tie: sequence diagrams lay
    # participants out side-by-side (wide), component/class diagrams tend
    # taller/squarer -- confirmed against real submission diagrams during
    # development (component diagram 818x1003, two sequence diagrams
    # 766x355 and 608x326).
    if n_ellipses >= 2 and n_boxes <= 2:
        type_guess = "use-case-like (actors/ovals detected)"
    elif aspect_ratio >= 1.3 and n_boxes >= 1 and n_lines >= 30:
        type_guess = "sequence-like (wide, many connecting lines + participant boxes)"
    elif n_boxes >= 3 and n_lines >= 10:
        type_guess = "component/class-like (boxes + connectors detected)"
    elif not has_structure:
        type_guess = "no diagram-like structure detected (may be a photo, logo, or text screenshot)"
    else:
        type_guess = "diagram-like structure present, type unclear"

    return {
        "width": w,
        "height": h,
        "edge_density": edge_density,
        "n_lines": n_lines,
        "n_boxes": n_boxes,
        "n_ellipses": n_ellipses,
        "has_diagram_structure": has_structure,
        "type_guess": type_guess,
    }


def extract_and_analyze(path: Path) -> list:
    """Every sufficiently large embedded raster image's structural evidence,
    as a list of dicts (pdf images additionally carry a "page" key). Never
    raises -- a corrupt/unsupported embed is skipped, not fatal to
    ingestion; an unreadable document (bad path, wrong format) just yields
    an empty list rather than blowing up the whole ingest pipeline."""
    suffix = path.suffix.lower()
    try:
        raw = _extract_pdf_images(path) if suffix == ".pdf" else _extract_docx_images(path)
    except Exception:
        return []

    # The exact same image sometimes shows up on every page (seen in the
    # wild: a PDF export that flattened a background/watermark image onto
    # all 7 pages) -- without deduping, that reads to the scorer as "7
    # diagrams" instead of 1, wildly overcrediting diagram coverage.
    # Dedupe by content hash, keep the first occurrence, and note repeats.
    seen = {}
    order = []
    for page_num, blob in raw:
        digest = hashlib.md5(blob).hexdigest()
        if digest in seen:
            seen[digest]["repeated_count"] = seen[digest].get("repeated_count", 1) + 1
            continue
        analysis = analyze_image(blob)
        if analysis is None:
            continue
        if page_num is not None:
            analysis["page"] = page_num
        seen[digest] = analysis
        order.append(digest)
    return [seen[d] for d in order]
