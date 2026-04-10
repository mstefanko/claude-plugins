"""Text normalization and fuzzy matching utilities."""

import re
import unicodedata

from .constants import SYNONYMS, _VERSION_CHARS

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


def normalize(text: str) -> str:
    """Normalize text for matching: lowercase, strip hyphens/underscores/dots/possessives."""
    text = unicodedata.normalize('NFKD', text)
    text = text.lower()
    text = re.sub(r"[-_.]", " ", text)
    text = re.sub(r"['\u2019]s\b", "", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def looks_like_version(keyword: str) -> bool:
    """Return True if keyword contains a version-number-like segment."""
    parts = keyword.replace("-", " ").replace("_", " ").split()
    for p in parts:
        stripped = p.strip()
        if stripped and all(c in _VERSION_CHARS for c in stripped) and "." in stripped:
            return True
    return False


def strip_version(keyword: str) -> str:
    """Remove trailing version numbers: 'ruby 3.3' -> 'ruby'."""
    parts = keyword.strip().split()
    cleaned = []
    for p in parts:
        if all(c in _VERSION_CHARS for c in p) and p:
            continue
        cleaned.append(p)
    return " ".join(cleaned) if cleaned else ""


def fuzzy_match_keyword(keyword: str, text: str) -> tuple:
    """Three-tier matching: exact normalized -> synonym -> fuzzy.

    Returns (matched: bool, method: str, score: float).
    """
    kw_norm = normalize(keyword)
    text_norm = normalize(text)

    # Tier 1: Exact normalized substring
    if kw_norm in text_norm:
        return (True, "exact", 100.0)

    # Tier 2: Synonym expansion (skip synonyms <=2 chars to avoid false positives)
    for syn in SYNONYMS.get(keyword, []):
        syn_norm = normalize(syn)
        if len(syn_norm) > 2 and syn_norm in text_norm:
            return (True, "synonym", 95.0)

    # Tier 3: rapidfuzz (if available, skip for short keywords)
    if HAS_RAPIDFUZZ and len(kw_norm) > 3:
        score = fuzz.token_set_ratio(
            kw_norm, text_norm,
            processor=None,  # already normalized
            score_cutoff=70,
        )
        if score:
            return (True, "fuzzy", score)

    return (False, "none", 0.0)
