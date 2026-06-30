"""
Projection layer: transform the merged canonical profile into a runtime-configured
output payload without code changes.

Supported config keys:
  include: list of canonical fields to output
  rename: mapping from canonical field name to output key
  normalize: list or mapping of output normalization options
  show_confidence: include per-field confidence block
  show_provenance: include provenance block
  missing_policy: "null" | "omit" | "error"
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.normalizers import canonicalize_skills, normalize_phone
from src.schemas import CanonicalProfile, Location


class ProjectionError(Exception):
    pass


def load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(p) as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ProjectionError("Projection config must be a JSON object")
    return config


def _serialize_value(v: Any) -> Any:
    if hasattr(v, "model_dump"):
        return v.model_dump(exclude_none=True)
    if isinstance(v, list):
        return [_serialize_value(i) for i in v]
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    return v


def _normalization_enabled(normalize_config: Any, field: str) -> bool:
    if normalize_config is True:
        return True
    if normalize_config in (False, None):
        return False
    if isinstance(normalize_config, list):
        return field in normalize_config or "all" in normalize_config
    if isinstance(normalize_config, dict):
        value = normalize_config.get(field, normalize_config.get("all", False))
        return bool(value)
    return False


def _apply_output_normalization(field: str, value: Any, normalize_config: Any) -> Any:
    if not _normalization_enabled(normalize_config, field):
        return value
    value = deepcopy(value)
    if field == "phones" and isinstance(value, list):
        return [phone for phone in (normalize_phone(v) for v in value) if phone]
    if field == "skills" and isinstance(value, list):
        return canonicalize_skills(value)
    if field == "location" and isinstance(value, Location):
        return value
    return value


ASSIGNMENT_FIELDS = [
    "candidate_id",
    "full_name",
    "emails",
    "phones",
    "location",
    "links",
    "headline",
    "years_experience",
    "skills",
    "experience",
    "education",
    "provenance",
    "overall_confidence",
]

LEGACY_ALIASES = {
    "name": "full_name",
    "email": "emails",
    "phone": "phones",
    "profile_url": "links",
    "website": "links",
}


def _profile_value(profile: CanonicalProfile, field: str) -> Any:
    canonical_field = LEGACY_ALIASES.get(field, field)
    if canonical_field == "provenance":
        public_fields = set(ASSIGNMENT_FIELDS) - {"provenance"}
        return {key: value for key, value in profile.provenance.items() if key in public_fields}
    if canonical_field == "overall_confidence":
        return profile.overall_confidence
    if canonical_field == "full_name":
        return profile.full_name or profile.name
    if canonical_field == "emails":
        return profile.emails or ([profile.email] if profile.email else [])
    if canonical_field == "phones":
        return profile.phones or ([profile.phone] if profile.phone else [])
    return getattr(profile, canonical_field, None)



def _output_key(requested_field: str, canonical_field: str, rename: dict[str, str]) -> str:
    alias_for = {"full_name": "name", "emails": "email", "phones": "phone"}
    return rename.get(requested_field) or rename.get(canonical_field) or rename.get(alias_for.get(canonical_field, "")) or requested_field


def _confidence_value(profile: CanonicalProfile, requested_field: str, canonical_field: str) -> float | None:
    alias_for = {"full_name": "name", "emails": "email", "phones": "phone"}
    return (
        profile.confidence.get(canonical_field)
        or profile.confidence.get(requested_field)
        or profile.confidence.get(alias_for.get(canonical_field, ""))
    )


def _provenance_value(profile: CanonicalProfile, requested_field: str, canonical_field: str):
    alias_for = {"full_name": "name", "emails": "email", "phones": "phone"}
    return (
        profile.provenance.get(canonical_field)
        or profile.provenance.get(requested_field)
        or profile.provenance.get(alias_for.get(canonical_field, ""))
    )

def apply_projection(profile: CanonicalProfile, config: dict) -> dict:
    include: list[str] | None = config.get("include")
    rename: dict[str, str] = config.get("rename", {})
    normalize_config = config.get("normalize", True)
    show_confidence: bool = config.get("show_confidence", True)
    show_provenance: bool = config.get("show_provenance", True)
    missing_policy: str = config.get("missing_policy", "null")

    if missing_policy not in {"null", "omit", "error"}:
        raise ProjectionError("missing_policy must be one of: null, omit, error")

    fields_to_output = include if include else ASSIGNMENT_FIELDS
    output: dict[str, Any] = {}

    for requested_field in fields_to_output:
        field = LEGACY_ALIASES.get(requested_field, requested_field)
        if field == "provenance" and not show_provenance:
            continue
        value = _profile_value(profile, requested_field)
        value = _apply_output_normalization(field, value, normalize_config)
        is_empty = value is None or value == {} or (value == [] and requested_field in {"emails", "phones"})

        if is_empty:
            if missing_policy == "omit":
                continue
            if missing_policy == "error":
                raise ProjectionError(f"Required field '{requested_field}' is missing from profile")
            value = None

        output_key = _output_key(requested_field, field, rename)
        output[output_key] = _serialize_value(value)

    if show_confidence:
        confidence: dict[str, Any] = {}
        for requested_field in fields_to_output:
            field = LEGACY_ALIASES.get(requested_field, requested_field)
            conf = _confidence_value(profile, requested_field, field)
            if conf is not None:
                output_key = _output_key(requested_field, field, rename)
                confidence[output_key] = conf
        if confidence:
            output["confidence"] = confidence

    if show_provenance and "provenance" not in output:
        provenance: dict[str, Any] = {}
        for requested_field in fields_to_output:
            field = LEGACY_ALIASES.get(requested_field, requested_field)
            prov = _provenance_value(profile, requested_field, field)
            if prov:
                output_key = _output_key(requested_field, field, rename)
                provenance[output_key] = prov.model_dump()
        if provenance:
            output["provenance"] = provenance

    output["sources_used"] = [s.value for s in profile.sources_used]
    return output
