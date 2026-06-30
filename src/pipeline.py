"""
Pipeline: orchestrates Extract -> Normalize -> Match -> Merge -> Score -> Validate -> Project.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.confidence import compute_overall
from src.extractors import csv_source, github_source, linkedin_source, resume_source
from src.merge import merge_profiles
from src.normalizers import normalize_date, normalize_phone
from src.projection import apply_projection, load_config
from src.schemas import CanonicalProfile, SourceType
from src.validators import validate_profile, validate_projected_output

log = logging.getLogger(__name__)


def _normalize_profile(profile: CanonicalProfile, source: SourceType) -> CanonicalProfile:
    if profile.phone:
        normalized = normalize_phone(profile.phone)
        if normalized:
            profile.phone = normalized
        else:
            log.warning("[%s] Could not normalize phone: %r", source.value, profile.phone)
            profile.phone = None
    profile.phones = [p for p in (normalize_phone(p) for p in profile.phones) if p]

    for exp in profile.experience:
        exp.start_date = normalize_date(exp.start_date)
        exp.end_date = normalize_date(exp.end_date)

    for edu in profile.education:
        edu.start_date = normalize_date(edu.start_date)
        edu.end_date = normalize_date(edu.end_date)

    return profile


def run(
    csv_path: str | None = None,
    resume_path: str | None = None,
    linkedin_path: str | None = None,
    github_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    source_profiles: list[tuple[CanonicalProfile, SourceType]] = []

    if csv_path and Path(csv_path).exists():
        try:
            source_profiles.append((_normalize_profile(csv_source.extract(csv_path), SourceType.CSV), SourceType.CSV))
        except Exception as e:
            log.error("CSV extraction failed: %s", e)

    if resume_path and Path(resume_path).exists():
        try:
            source_profiles.append((_normalize_profile(resume_source.extract(resume_path), SourceType.RESUME), SourceType.RESUME))
        except Exception as e:
            log.error("Resume extraction failed: %s", e)

    if linkedin_path and Path(linkedin_path).exists():
        try:
            source_profiles.append((_normalize_profile(linkedin_source.extract(linkedin_path), SourceType.LINKEDIN), SourceType.LINKEDIN))
        except Exception as e:
            log.error("LinkedIn extraction failed: %s", e)

    if github_path:
        try:
            source_profiles.append((_normalize_profile(github_source.extract(github_path), SourceType.GITHUB), SourceType.GITHUB))
        except Exception as e:
            log.error("GitHub extraction failed: %s", e)

    if not source_profiles:
        raise ValueError("No valid sources provided or all sources failed to extract.")

    _check_entity_consistency(source_profiles)
    merged = merge_profiles(source_profiles)
    merged.overall_confidence = compute_overall(merged)

    warnings = validate_profile(merged)
    for warning in warnings:
        log.warning("Validation: %s", warning)

    config = load_config(config_path)
    output = apply_projection(merged, config)
    output_warnings = validate_projected_output(output, require_complete=not bool(config.get("include")))
    warnings.extend(output_warnings)
    for warning in output_warnings:
        log.warning("Output validation: %s", warning)

    if warnings:
        output["warnings"] = warnings
    return output


def _check_entity_consistency(source_profiles: list[tuple[CanonicalProfile, SourceType]]) -> None:
    """Warn only on concrete identity conflicts, not on missing identifiers."""
    from src.matcher import _names_fuzzy_match, _phones_match, same_candidate

    if len(source_profiles) < 2:
        return

    records = [{"email": p.email, "phone": p.phone, "name": p.name or p.full_name} for p, _ in source_profiles]
    ref = records[0]
    ref_source = source_profiles[0][1]
    for i, rec in enumerate(records[1:], 1):
        if same_candidate(ref, rec):
            continue
        email_conflict = bool(ref.get("email") and rec.get("email") and ref["email"].lower().strip() != rec["email"].lower().strip())
        phone_conflict = bool(ref.get("phone") and rec.get("phone") and not _phones_match(ref.get("phone"), rec.get("phone")))
        names_conflict = bool(ref.get("name") and rec.get("name") and not _names_fuzzy_match(ref.get("name"), rec.get("name")))
        if email_conflict or phone_conflict or names_conflict:
            source = source_profiles[i][1]
            log.warning("Source '%s' may describe a different candidate than '%s'. Merging anyway; review output carefully.", source.value, ref_source.value)
