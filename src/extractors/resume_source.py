"""
Resume PDF extractor using pdfplumber.
Resumes are unstructured — we apply heuristics section by section.

Design decisions:
  - Section detection by keyword headers (EXPERIENCE, EDUCATION, SKILLS, SUMMARY).
  - Email and phone extracted via regex before section parsing (they appear anywhere).
  - We deliberately don't try to be too clever: if a section can't be found, it's
    left empty rather than making up structure.
  - pdfplumber over PyMuPDF: pdfplumber has cleaner Python API for text extraction.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber

from src.normalizers import canonicalize_skills, normalize_date
from src.schemas import CanonicalProfile, EducationEntry, ExperienceEntry, SourceType

log = logging.getLogger(__name__)

# Patterns
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?[\d][\d\s\-().]{7,}\d)")

# Section header keywords (uppercase for matching)
SECTION_HEADERS = {
    "experience": re.compile(
        r"^\s*(work\s+experience|professional\s+experience|experience|employment)\s*$",
        re.IGNORECASE,
    ),
    "education": re.compile(
        r"^\s*(education|academic\s+background|qualifications)\s*$",
        re.IGNORECASE,
    ),
    "skills": re.compile(
        r"^\s*(skills|technical\s+skills|core\s+competencies|technologies)\s*$",
        re.IGNORECASE,
    ),
    "summary": re.compile(
        r"^\s*(summary|profile|about|objective|professional\s+summary)\s*$",
        re.IGNORECASE,
    ),
}

# Date range pattern: "Jan 2020 – Mar 2022" or "2019 - Present"
DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})"
    r"\s*[–\-–—]\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}|present|current|now)",
    re.IGNORECASE,
)


def _extract_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _detect_sections(lines: list[str]) -> dict[str, list[str]]:
    """Split lines into named sections based on header detection."""
    sections: dict[str, list[str]] = {k: [] for k in SECTION_HEADERS}
    current: str | None = None

    for line in lines:
        stripped = line.strip()
        matched = False
        for name, pattern in SECTION_HEADERS.items():
            if pattern.match(stripped):
                current = name
                matched = True
                break
        if not matched and current:
            sections[current].append(line)

    return sections


def _parse_skills(lines: list[str]) -> list[str]:
    raw: list[str] = []
    for line in lines:
        # Skills are often comma- or bullet-separated
        parts = re.split(r"[,•·|/]", line)
        for part in parts:
            s = part.strip().strip("–-•·")
            if s and len(s) > 1:
                raw.append(s)
    return canonicalize_skills(raw)


def _parse_experience(lines: list[str]) -> list[ExperienceEntry]:
    """
    Parse common resume layouts such as:
      Title
      Company | Jan 2022 - Present
      Description...

    A pending title is carried forward until the following date-bearing line.
    This prevents the next role title from being swallowed into the previous
    role's description when PDF text extraction wraps lines aggressively.
    """
    entries: list[ExperienceEntry] = []
    current: dict | None = None
    desc_lines: list[str] = []
    pending_title: str | None = None

    def flush() -> None:
        nonlocal current, desc_lines
        if not current:
            return
        entries.append(
            ExperienceEntry(
                title=current.get("title"),
                company=current.get("company"),
                start_date=current.get("start_date"),
                end_date=current.get("end_date"),
                description=" ".join(desc_lines).strip() or None,
                source=SourceType.RESUME,
            )
        )
        current = None
        desc_lines = []

    cleaned = [line.strip() for line in lines if line.strip()]
    for idx, line in enumerate(cleaned):
        m = DATE_RANGE_RE.search(line)
        if m:
            flush()
            text_before = line[: m.start()].strip().rstrip(",|–- ")
            title = pending_title
            company = text_before or None

            if text_before and " at " in text_before.lower():
                parts = re.split(r"\s+at\s+", text_before, maxsplit=1, flags=re.IGNORECASE)
                title = parts[0].strip() or title
                company = parts[1].strip() or None

            current = {
                "title": title,
                "company": company,
                "start_date": normalize_date(m.group(1)),
                "end_date": normalize_date(m.group(2)),
            }
            pending_title = None
            continue

        next_line = cleaned[idx + 1] if idx + 1 < len(cleaned) else ""
        if DATE_RANGE_RE.search(next_line):
            pending_title = line
            continue

        if current is None:
            pending_title = line
        else:
            desc_lines.append(line)

    flush()
    return entries


def _parse_education(lines: list[str]) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    current: dict | None = None
    pending_degree: str | None = None

    def flush() -> None:
        nonlocal current
        if current:
            entries.append(
                EducationEntry(
                    school=current.get("school"),
                    degree=current.get("degree"),
                    field_of_study=current.get("field"),
                    start_date=current.get("start_date"),
                    end_date=current.get("end_date"),
                    source=SourceType.RESUME,
                )
            )
        current = None

    def field_from_degree(degree: str | None) -> str | None:
        if not degree:
            return None
        field_m = re.search(r"\bin\s+(.+)$", degree, re.IGNORECASE)
        if field_m:
            return field_m.group(1).strip()
        parts = [p.strip() for p in degree.split(",", maxsplit=1)]
        return parts[1] if len(parts) == 2 else None

    cleaned = [line.strip() for line in lines if line.strip()]
    for line in cleaned:
        m = DATE_RANGE_RE.search(line)
        if m:
            flush()
            school = line[: m.start()].strip().rstrip(",|–- ") or None
            current = {
                "school": school,
                "degree": pending_degree,
                "field": field_from_degree(pending_degree),
                "start_date": normalize_date(m.group(1)),
                "end_date": normalize_date(m.group(2)),
            }
            pending_degree = None
            continue

        deg_m = re.match(
            r"(bachelor|master|phd|doctorate|b\.?s\.?|m\.?s\.?|b\.?e\.?|btech|mtech|mba)",
            line,
            re.IGNORECASE,
        )
        if deg_m:
            pending_degree = line
        elif current is None:
            pending_degree = pending_degree or line
        elif not current.get("school"):
            current["school"] = line

    flush()
    return entries


def extract(path: str | Path) -> CanonicalProfile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {path}")

    text = _extract_text(path)
    lines = text.splitlines()

    profile = CanonicalProfile()

    # Email and phone — can appear anywhere in the document
    email_m = EMAIL_RE.search(text)
    if email_m:
        profile.email = email_m.group(0)

    phone_matches = PHONE_RE.findall(text)
    if phone_matches:
        profile.phone = phone_matches[0]

    # Name heuristic: first non-empty line of the first page (usually the header)
    for line in lines:
        stripped = line.strip()
        if stripped and not EMAIL_RE.search(stripped) and not PHONE_RE.search(stripped):
            # Avoid picking up URLs or addresses
            if len(stripped.split()) <= 5 and not stripped.startswith(("http", "www")):
                profile.name = stripped
                break

    # Location heuristic: look for "City, State" or "City, Country" pattern
    loc_re = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?),\s*([A-Z]{2}|[A-Z][a-z]+)\b")
    loc_m = loc_re.search(text)
    if loc_m:
        profile.location = loc_m.group(0)

    sections = _detect_sections(lines)

    if sections["summary"]:
        profile.headline = " ".join(sections["summary"]).strip()[:300]

    profile.skills = _parse_skills(sections["skills"])
    profile.experience = _parse_experience(sections["experience"])
    profile.education = _parse_education(sections["education"])

    return profile
