"""
LinkedIn HTML extractor.
We parse a saved/exported LinkedIn profile HTML — no Selenium, no live scraping.
The HTML structure LinkedIn uses for exports is relatively stable; we target
the semantic data attributes and known class patterns.

This also works with mock HTML files that follow the same structure,
which is what we use for testing and the demo.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.normalizers import canonicalize_skills, normalize_date
from src.schemas import CanonicalProfile, EducationEntry, ExperienceEntry, SourceType

log = logging.getLogger(__name__)


def _text(tag: Tag | None, default: str = "") -> str:
    if tag is None:
        return default
    return tag.get_text(separator=" ", strip=True)


def _find_section(soup: BeautifulSoup, heading_text: str) -> Tag | None:
    """Find a section by its heading text (case-insensitive)."""
    for tag in soup.find_all(["h2", "h3", "section"]):
        if heading_text.lower() in tag.get_text().lower():
            # Return the parent section or the tag itself
            parent = tag.find_parent("section")
            return parent if parent else tag
    return None


def _parse_experience(soup: BeautifulSoup) -> list[ExperienceEntry]:
    entries: list[ExperienceEntry] = []

    # LinkedIn exports experience as <li> items inside the experience section
    exp_section = _find_section(soup, "experience")
    if not exp_section:
        return entries

    for item in exp_section.find_all("li"):
        text = _text(item)
        if not text or len(text) < 5:
            continue

        entry = ExperienceEntry(source=SourceType.LINKEDIN)

        # Try structured attributes first
        title_tag = item.find(class_=re.compile(r"title|position", re.I))
        company_tag = item.find(class_=re.compile(r"company|org", re.I))
        date_tag = item.find(class_=re.compile(r"date|period|duration", re.I))

        entry.title = _text(title_tag) if title_tag else None
        entry.company = _text(company_tag) if company_tag else None

        if date_tag:
            date_text = _text(date_tag)
            # Parse "Jan 2020 – Mar 2022" style
            parts = re.split(r"\s*[–—-]\s*", date_text, maxsplit=1)
            if len(parts) == 2:
                entry.start_date = normalize_date(parts[0])
                entry.end_date = normalize_date(parts[1])

        # If structured parsing failed, fall back to heuristics on the raw text
        if not entry.title and not entry.company:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                entry.title = lines[0]
            if len(lines) > 1:
                entry.company = lines[1]

        if entry.title or entry.company:
            entries.append(entry)

    return entries


def _parse_education(soup: BeautifulSoup) -> list[EducationEntry]:
    entries: list[EducationEntry] = []

    edu_section = _find_section(soup, "education")
    if not edu_section:
        return entries

    for item in edu_section.find_all("li"):
        text = _text(item)
        if not text or len(text) < 5:
            continue

        entry = EducationEntry(source=SourceType.LINKEDIN)

        school_tag = item.find(class_=re.compile(r"school|institution|university", re.I))
        degree_tag = item.find(class_=re.compile(r"degree|field|study", re.I))
        date_tag = item.find(class_=re.compile(r"date|period|year", re.I))

        entry.school = _text(school_tag) if school_tag else None
        entry.degree = _text(degree_tag) if degree_tag else None

        if date_tag:
            date_text = _text(date_tag)
            parts = re.split(r"\s*[–—-]\s*", date_text, maxsplit=1)
            if len(parts) == 2:
                entry.start_date = normalize_date(parts[0])
                entry.end_date = normalize_date(parts[1])
            elif len(parts) == 1:
                entry.end_date = normalize_date(parts[0])

        # Fallback
        if not entry.school:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                entry.school = lines[0]
            if len(lines) > 1:
                entry.degree = lines[1]

        if entry.school:
            entries.append(entry)

    return entries


def _parse_skills(soup: BeautifulSoup) -> list[str]:
    skills_section = _find_section(soup, "skills")
    if not skills_section:
        return []

    raw: list[str] = []
    for tag in skills_section.find_all(["li", "span", "div"]):
        text = _text(tag)
        if text and 2 < len(text) < 60 and "\n" not in text:
            raw.append(text)

    return canonicalize_skills(raw)


def extract(path: str | Path) -> CanonicalProfile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"LinkedIn HTML not found: {path}")

    with open(path, encoding="utf-8", errors="replace") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")
    profile = CanonicalProfile()

    # Name: look for common profile name selectors
    name_tag = (
        soup.find(class_=re.compile(r"name|full.?name", re.I))
        or soup.find("h1")
    )
    profile.name = _text(name_tag) if name_tag else None

    # Headline
    headline_tag = soup.find(class_=re.compile(r"headline|tagline|subtitle", re.I))
    profile.headline = _text(headline_tag) if headline_tag else None

    # Location
    loc_tag = soup.find(class_=re.compile(r"location|address", re.I))
    profile.location = _text(loc_tag) if loc_tag else None

    # Profile URL
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        profile.profile_url = canonical["href"]
    else:
        url_tag = soup.find("a", href=re.compile(r"linkedin\.com/in/"))
        if url_tag:
            profile.profile_url = url_tag["href"]

    profile.experience = _parse_experience(soup)
    profile.education = _parse_education(soup)
    profile.skills = _parse_skills(soup)

    return profile
