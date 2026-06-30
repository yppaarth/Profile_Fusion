"""
Validation layer. Normalization transforms data; validation enforces invariants
for both the merged canonical profile and projected output payload.
"""
from __future__ import annotations

import re
from typing import Any

import phonenumbers
from pydantic import ValidationError as PydanticValidationError

from src.schemas import CanonicalProfile, ProjectedCandidateProfile

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ValidationError(Exception):
    pass


def validate_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(EMAIL_RE.match(email.strip()))


def validate_phone(phone: str | None) -> bool:
    if not phone:
        return False
    try:
        parsed = phonenumbers.parse(phone)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.NumberParseException:
        return False


def validate_profile(profile: CanonicalProfile) -> list[str]:
    warnings: list[str] = []
    emails = profile.emails or ([profile.email] if profile.email else [])
    phones = profile.phones or ([profile.phone] if profile.phone else [])

    for email in emails:
        if not validate_email(email):
            warnings.append(f"Invalid email format: {email!r}")

    for phone in phones:
        if not validate_phone(phone):
            warnings.append(f"Phone is not valid E.164: {phone!r}")

    if not (profile.full_name or profile.name):
        warnings.append("No name found in any source")
    if not emails:
        warnings.append("No email found in any source")
    if not profile.skills:
        warnings.append("No skills extracted from any source")
    if profile.overall_confidence < 0.4:
        warnings.append(f"Overall confidence is low ({profile.overall_confidence:.2f}); verify source quality")
    return warnings


def validate_projected_output(output: dict[str, Any], require_complete: bool = True) -> list[str]:
    if not require_complete:
        return []
    try:
        ProjectedCandidateProfile.model_validate(output)
        return []
    except PydanticValidationError as exc:
        return [f"Output schema validation failed: {err['loc']}: {err['msg']}" for err in exc.errors()]
