"""
Entity matching across source records.
Goal: decide whether two FieldValue dicts refer to the same person.

Rules (in order):
  1. Exact email match → same person
  2. Exact normalized phone match → same person
  3. Exact name match + any other match → same person
  4. Fuzzy name (≥0.85) + email match → same person
  5. Name alone → NOT sufficient (too many John Smiths)

This is intentionally conservative. False merges corrupt the profile;
false non-merges just leave gaps.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from src.normalizers import normalize_phone


def _phones_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na, nb = normalize_phone(a), normalize_phone(b)
    return bool(na and nb and na == nb)


def _names_fuzzy_match(a: str | None, b: str | None, threshold: float = 85.0) -> bool:
    if not a or not b:
        return False
    score = fuzz.token_sort_ratio(a.lower(), b.lower())
    return score >= threshold


def same_candidate(record_a: dict, record_b: dict) -> bool:
    """
    Both records are dicts with optional keys: email, phone, name.
    Returns True if they almost certainly describe the same person.
    """
    email_a = (record_a.get("email") or "").lower().strip()
    email_b = (record_b.get("email") or "").lower().strip()

    # Rule 1: exact email
    if email_a and email_b and email_a == email_b:
        return True

    # Rule 2: normalized phone
    if _phones_match(record_a.get("phone"), record_b.get("phone")):
        return True

    # Rules 3 & 4: name match requires at least one other signal
    name_a = record_a.get("name")
    name_b = record_b.get("name")
    if name_a and name_b:
        exact_name = name_a.lower().strip() == name_b.lower().strip()
        fuzzy_name = _names_fuzzy_match(name_a, name_b)

        if (exact_name or fuzzy_name) and email_a and email_b and email_a == email_b:
            return True  # already caught by rule 1, but explicit

        if exact_name and _phones_match(record_a.get("phone"), record_b.get("phone")):
            return True

    return False
