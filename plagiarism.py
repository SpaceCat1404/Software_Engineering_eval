#!/usr/bin/env python3
"""
plagiarism.py — simple 3-step plagiarism checker (CNS pipeline version).

Only the reusable text-similarity primitives are needed by srs_table_plagiarism.py:
shingles(), jaccard(), structural_similarity(), WORD_RE. Full original docstring
and CLI preserved for reference / drop-in compatibility.
"""
import difflib
import re

SHINGLE_SIZE = 5
JACCARD_THRESHOLD = 0.45
MIN_SHINGLE_MATCHES = 4
MIN_TEXT_LENGTH = 30
STRUCTURAL_SIMILARITY_THRESHOLD = 0.60

WORD_RE = re.compile(r"[a-z0-9]+")


def shingles(text: str, k: int = SHINGLE_SIZE) -> set:
    words = WORD_RE.findall(text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set, b: set) -> tuple:
    if not a or not b:
        return 0.0, 0
    inter = a & b
    return len(inter) / len(a | b), len(inter)


def structural_similarity(words_a: list, words_b: list) -> float:
    if not words_a or not words_b:
        return 0.0
    return difflib.SequenceMatcher(None, words_a, words_b, autojunk=False).ratio()
