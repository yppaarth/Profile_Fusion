"""
CSV extractor — the one structured source.
pandas reads the CSV; we extract exactly the five fields the recruiter exports.
Missing columns are tolerated and logged rather than fatal.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from src.schemas import CanonicalProfile, SourceType

log = logging.getLogger(__name__)

EXPECTED_COLUMNS = {"name", "email", "phone", "current_company", "title"}


def extract(path: str | Path) -> CanonicalProfile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    # Normalize column names: strip whitespace, lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    missing = EXPECTED_COLUMNS - set(df.columns)
    if missing:
        log.warning("CSV is missing columns: %s", missing)

    if df.empty:
        log.warning("CSV is empty: %s", path)
        return CanonicalProfile()

    # Take the first row. The CLI passes one CSV per candidate.
    row = df.iloc[0]

    def get(col: str) -> str | None:
        val = row.get(col, "").strip()
        return val if val else None

    profile = CanonicalProfile()
    profile.name = get("name")
    profile.email = get("email")
    profile.phone = get("phone")
    profile.current_company = get("current_company")
    profile.current_title = get("title")

    return profile
