"""
Confidence scoring.
Each source x field combination has a base confidence. The weighted average
across populated fields gives overall_confidence.
"""
from __future__ import annotations

from src.schemas import CanonicalProfile, SourceType

FIELD_CONFIDENCE: dict[tuple[SourceType, str], float] = {
    (SourceType.CSV, "full_name"): 0.95,
    (SourceType.CSV, "emails"): 0.98,
    (SourceType.CSV, "phones"): 0.95,
    (SourceType.CSV, "current_company"): 0.90,
    (SourceType.CSV, "current_title"): 0.90,
    (SourceType.RESUME, "full_name"): 0.85,
    (SourceType.RESUME, "emails"): 0.92,
    (SourceType.RESUME, "phones"): 0.88,
    (SourceType.RESUME, "skills"): 0.82,
    (SourceType.RESUME, "education"): 0.85,
    (SourceType.RESUME, "experience"): 0.85,
    (SourceType.RESUME, "headline"): 0.80,
    (SourceType.RESUME, "location"): 0.75,
    (SourceType.LINKEDIN, "headline"): 0.88,
    (SourceType.LINKEDIN, "location"): 0.80,
    (SourceType.LINKEDIN, "skills"): 0.78,
    (SourceType.LINKEDIN, "experience"): 0.80,
    (SourceType.LINKEDIN, "education"): 0.80,
    (SourceType.LINKEDIN, "links"): 0.72,
    (SourceType.GITHUB, "full_name"): 0.70,
    (SourceType.GITHUB, "bio"): 0.65,
    (SourceType.GITHUB, "location"): 0.60,
    (SourceType.GITHUB, "links"): 0.80,
    (SourceType.GITHUB, "github_languages"): 0.90,
    (SourceType.GITHUB, "github_repos"): 0.90,
    # Backward-compatible names for extractor/unit tests.
    (SourceType.CSV, "name"): 0.95,
    (SourceType.CSV, "email"): 0.98,
    (SourceType.CSV, "phone"): 0.95,
    (SourceType.RESUME, "name"): 0.85,
    (SourceType.RESUME, "email"): 0.92,
    (SourceType.RESUME, "phone"): 0.88,
    (SourceType.GITHUB, "name"): 0.70,
    (SourceType.GITHUB, "website"): 0.80,
}

SOURCE_DEFAULT: dict[SourceType, float] = {
    SourceType.CSV: 0.88,
    SourceType.RESUME: 0.78,
    SourceType.LINKEDIN: 0.72,
    SourceType.GITHUB: 0.65,
}

FIELD_WEIGHTS: dict[str, float] = {
    "emails": 2.0,
    "full_name": 1.5,
    "phones": 1.0,
    "headline": 1.0,
    "skills": 0.8,
    "experience": 0.8,
    "education": 0.8,
    "location": 0.5,
    "links": 0.4,
    "years_experience": 0.5,
    "current_company": 0.7,
    "current_title": 0.7,
    # Backward-compatible weights.
    "email": 2.0,
    "name": 1.5,
    "phone": 1.0,
}


def field_confidence(source: SourceType, field: str) -> float:
    return FIELD_CONFIDENCE.get((source, field), SOURCE_DEFAULT.get(source, 0.60))


def compute_overall(profile: CanonicalProfile) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for field, conf in profile.confidence.items():
        w = FIELD_WEIGHTS.get(field, 0.5)
        weighted_sum += conf * w
        total_weight += w
    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 4)
