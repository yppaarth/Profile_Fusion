"""
Pydantic models for the canonical candidate profile and projected assignment output.
The public canonical shape follows the assignment contract while retaining a few
legacy scalar fields internally so extractors can stay simple and source-specific.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceType(str, Enum):
    CSV = "csv"
    RESUME = "resume"
    LINKEDIN = "linkedin"
    GITHUB = "github"


class Provenance(BaseModel):
    field: str
    source: SourceType
    method: str


class FieldValue(BaseModel):
    """A field value bundled with its confidence and provenance."""
    value: Any
    confidence: float
    provenance: Provenance


class Location(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None


class Links(BaseModel):
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class ExperienceEntry(BaseModel):
    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    source: SourceType | None = None


class EducationEntry(BaseModel):
    school: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    source: SourceType | None = None


class CanonicalProfile(BaseModel):
    """Merged, normalized, confidence-scored candidate profile."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Assignment-required public schema fields
    candidate_id: str | None = None
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: Location | str | None = None
    links: Links = Field(default_factory=Links)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    overall_confidence: float = 0.0

    # Internal/legacy fields populated by individual extractors before merge.
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    current_company: str | None = None
    current_title: str | None = None
    bio: str | None = None
    github_repos: list[str] = Field(default_factory=list)
    github_languages: list[str] = Field(default_factory=list)
    website: str | None = None
    profile_url: str | None = None

    # Confidence map: field_name -> float in [0, 1]
    confidence: dict[str, float] = Field(default_factory=dict)

    # Which sources contributed
    sources_used: list[SourceType] = Field(default_factory=list)


class ProjectedCandidateProfile(BaseModel):
    """Full output schema used to validate default projected output."""

    model_config = ConfigDict(extra="allow")

    candidate_id: str
    full_name: str
    emails: list[str]
    phones: list[str]
    location: Location | None = None
    links: Links = Field(default_factory=Links)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    overall_confidence: float

    @field_validator("emails")
    @classmethod
    def emails_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("emails must contain at least one address")
        return value

    @field_validator("phones")
    @classmethod
    def phones_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("phones must contain at least one number")
        return value
