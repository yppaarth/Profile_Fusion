"""
Normalization functions. Each is pure and stateless — easy to test in isolation.
Decisions:
  - phonenumbers library is the gold standard for E.164; no regex reimplementation.
  - Skills canonicalization uses a lookup map + fuzzy fallback. Extending it means
    adding entries to SKILL_ALIASES, not touching logic.
  - Dates: dateutil parses most human date strings; we truncate to YYYY-MM.
"""
from __future__ import annotations

import re
from datetime import datetime

import phonenumbers
from dateutil import parser as dateparser

# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def normalize_phone(raw: str, default_region: str = "US") -> str | None:
    """Return E.164 string or None if unparseable."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def normalize_date(raw: str | None) -> str | None:
    """Coerce messy date strings to YYYY-MM. Returns None if unparseable."""
    if not raw:
        return None
    raw = raw.strip()
    if re.match(r"^\d{4}-\d{2}$", raw):
        return raw
    if re.match(r"^\d{4}$", raw):
        return f"{raw}-01"
    if raw.lower() in ("present", "current", "now", "–"):
        return "present"
    try:
        dt = dateparser.parse(raw, default=datetime(2000, 1, 1))
        return dt.strftime("%Y-%m")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Country → ISO-3166 alpha-2
# ---------------------------------------------------------------------------

COUNTRY_MAP: dict[str, str] = {
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "britain": "GB",
    "india": "IN",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "singapore": "SG",
    "netherlands": "NL",
}

def normalize_country(raw: str | None) -> str | None:
    if not raw:
        return None
    return COUNTRY_MAP.get(raw.strip().lower())


# ---------------------------------------------------------------------------
# Skills canonicalization
# ---------------------------------------------------------------------------

# Canonical name → list of aliases that map to it
SKILL_ALIASES: dict[str, list[str]] = {
    "C++": ["c++", "c plus plus", "c++ programming", "cplusplus"],
    "C#": ["c#", "csharp", "c sharp"],
    "JavaScript": ["javascript", "js", "java script"],
    "TypeScript": ["typescript", "ts"],
    "Python": ["python", "python3", "python 3"],
    "Machine Learning": ["machine learning", "ml", "machinelearning"],
    "Deep Learning": ["deep learning", "dl", "deeplearning"],
    "Natural Language Processing": ["nlp", "natural language processing"],
    "SQL": ["sql", "structured query language"],
    "React": ["react", "reactjs", "react.js"],
    "Node.js": ["node.js", "nodejs", "node js"],
    "Docker": ["docker", "docker container"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Azure": ["azure", "microsoft azure"],
    "Git": ["git", "git version control"],
    "Java": ["java"],
    "Go": ["golang", "go language"],
    "Rust": ["rust", "rust lang"],
    "Ruby": ["ruby", "ruby on rails"],
    "TensorFlow": ["tensorflow", "tf"],
    "PyTorch": ["pytorch", "torch"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "REST API": ["rest", "rest api", "restful", "restful api"],
    "GraphQL": ["graphql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
}

# Build reverse lookup once at import time
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in SKILL_ALIASES.items():
    _ALIAS_TO_CANONICAL[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias.lower()] = canonical


def canonicalize_skill(raw: str) -> str:
    """Return the canonical skill name, or the title-cased original if unknown."""
    return _ALIAS_TO_CANONICAL.get(raw.strip().lower(), raw.strip())


def canonicalize_skills(raw_skills: list[str]) -> list[str]:
    """Canonicalize and deduplicate a list of skill strings."""
    seen: set[str] = set()
    result: list[str] = []
    for s in raw_skills:
        canon = canonicalize_skill(s)
        if canon not in seen:
            seen.add(canon)
            result.append(canon)
    return result
