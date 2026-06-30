"""
Merge strategy: deterministic, priority-ordered, provenance-aware.
Priority (highest to lowest): CSV > Resume > LinkedIn > GitHub.
"""
from __future__ import annotations

import hashlib
from datetime import date

from src.confidence import field_confidence
from src.normalizers import canonicalize_skills, normalize_phone
from src.schemas import CanonicalProfile, EducationEntry, ExperienceEntry, Links, Location, Provenance, SourceType

SOURCE_PRIORITY = [SourceType.CSV, SourceType.RESUME, SourceType.LINKEDIN, SourceType.GITHUB]


def _priority(source: SourceType) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return 99


def _set_field(profile: CanonicalProfile, field: str, value, source: SourceType, method: str) -> None:
    setattr(profile, field, value)
    profile.confidence[field] = field_confidence(source, field)
    profile.provenance[field] = Provenance(field=field, source=source, method=method)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _merge_name(sources: list[tuple[str | None, SourceType]]) -> tuple[str | None, SourceType | None]:
    best: str | None = None
    best_source: SourceType | None = None
    for name, source in sources:
        if name and (best is None or len(name) > len(best)):
            best = name
            best_source = source
    return best, best_source


def _merge_email(sources: list[tuple[str | None, SourceType]]) -> tuple[str | None, SourceType | None]:
    candidates = [(e.lower().strip(), s) for e, s in sources if e]
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (-field_confidence(x[1], "emails"), _priority(x[1])))
    return candidates[0]


def _parse_location(raw) -> Location | None:
    if isinstance(raw, Location):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 3:
        return Location(city=parts[0], region=parts[1], country=parts[2])
    if len(parts) == 2:
        country = "US" if len(parts[1]) == 2 and parts[1].isupper() else None
        return Location(city=parts[0], region=parts[1], country=country)
    return Location(city=text)


def _candidate_id(full_name: str | None, emails: list[str], phones: list[str]) -> str | None:
    basis = emails[0] if emails else phones[0] if phones else full_name
    if not basis:
        return None
    digest = hashlib.sha256(basis.lower().strip().encode("utf-8")).hexdigest()[:12]
    return f"cand_{digest}"


def _years_experience(experience: list[ExperienceEntry]) -> float | None:
    years: set[int] = set()
    for entry in experience:
        if not entry.start_date:
            continue
        try:
            start_year = int(entry.start_date[:4])
        except ValueError:
            continue
        if entry.end_date == "present" or not entry.end_date:
            end_year = date.today().year
        else:
            try:
                end_year = int(entry.end_date[:4])
            except ValueError:
                end_year = start_year
        for year in range(start_year, max(start_year, end_year) + 1):
            years.add(year)
    if not years:
        return None
    return round(float(len(years)), 1)


def _merge_experiences(all_exp: list[ExperienceEntry]) -> list[ExperienceEntry]:
    seen: dict[tuple, ExperienceEntry] = {}
    for entry in all_exp:
        key = ((entry.company or "").lower().strip(), (entry.title or "").lower().strip(), entry.start_date or "")
        if key not in seen:
            seen[key] = entry
        else:
            existing = seen[key]
            if entry.description and (not existing.description or len(entry.description) > len(existing.description)):
                seen[key] = entry
    return sorted(seen.values(), key=lambda e: e.start_date or "", reverse=True)


def _merge_educations(all_edu: list[EducationEntry]) -> list[EducationEntry]:
    seen: dict[tuple, EducationEntry] = {}
    for entry in all_edu:
        key = ((entry.school or "").lower().strip(), (entry.degree or "").lower().strip())
        if key not in seen:
            seen[key] = entry
        else:
            existing = seen[key]
            if not existing.field_of_study and entry.field_of_study:
                seen[key] = entry
    return list(seen.values())


def merge_profiles(source_profiles: list[tuple[CanonicalProfile, SourceType]]) -> CanonicalProfile:
    ordered = sorted(source_profiles, key=lambda x: _priority(x[1]))
    merged = CanonicalProfile()
    merged.sources_used = [s for _, s in ordered]

    full_name, name_source = _merge_name([(p.full_name or p.name, s) for p, s in ordered])
    if full_name and name_source:
        _set_field(merged, "full_name", full_name, name_source, "longest_name")
        merged.name = full_name
        merged.confidence["name"] = merged.confidence["full_name"]
        merged.provenance["name"] = Provenance(field="name", source=name_source, method="legacy_alias:full_name")

    email, email_source = _merge_email([((p.emails[0] if p.emails else p.email), s) for p, s in ordered])
    all_emails = _dedupe_preserve_order([e for p, _ in ordered for e in ([*p.emails] + ([p.email] if p.email else []))])
    if email and email_source:
        emails = _dedupe_preserve_order([email] + all_emails)
        _set_field(merged, "emails", emails, email_source, "highest_confidence_deduped")
        merged.email = emails[0]
        merged.confidence["email"] = merged.confidence["emails"]
        merged.provenance["email"] = Provenance(field="email", source=email_source, method="legacy_alias:emails")

    phones: list[str] = []
    phone_source: SourceType | None = None
    for profile, source in ordered:
        for raw in [*profile.phones] + ([profile.phone] if profile.phone else []):
            normalized = normalize_phone(raw)
            if normalized:
                if phone_source is None:
                    phone_source = source
                phones.append(normalized)
    phones = _dedupe_preserve_order(phones)
    if phones and phone_source:
        _set_field(merged, "phones", phones, phone_source, "e164_normalized_deduped")
        merged.phone = phones[0]
        merged.confidence["phone"] = merged.confidence["phones"]
        merged.provenance["phone"] = Provenance(field="phone", source=phone_source, method="legacy_alias:phones")

    if merged.candidate_id is None:
        candidate_id = _candidate_id(merged.full_name, merged.emails, merged.phones)
        if candidate_id:
            source = email_source or phone_source or name_source or ordered[0][1]
            _set_field(merged, "candidate_id", candidate_id, source, "sha256_identity_key")

    for profile, source in ordered:
        loc = _parse_location(profile.location)
        if loc:
            _set_field(merged, "location", loc, source, "structured_location_parse")
            break

    for field in ["headline", "current_company", "current_title", "bio"]:
        for profile, source in ordered:
            value = getattr(profile, field, None)
            if value:
                _set_field(merged, field, value, source, "first_available")
                break

    links = Links()
    link_source: SourceType | None = None
    for profile, source in ordered:
        if source == SourceType.LINKEDIN and profile.profile_url and not links.linkedin:
            links.linkedin = profile.profile_url
            link_source = link_source or source
        elif source == SourceType.GITHUB and profile.profile_url and not links.github:
            links.github = profile.profile_url
            link_source = link_source or source
        if profile.website and not links.website:
            links.website = profile.website
            link_source = link_source or source
    if links.linkedin or links.github or links.website:
        _set_field(merged, "links", links, link_source or ordered[0][1], "source_specific_link_map")
        merged.website = links.website
        merged.profile_url = links.linkedin or links.github

    all_skills: list[str] = []
    for profile, _ in ordered:
        all_skills.extend(profile.skills)
    if all_skills:
        merged.skills = canonicalize_skills(all_skills)
        skill_sources = [s for p, s in ordered if p.skills]
        avg_conf = sum(field_confidence(s, "skills") for s in skill_sources) / len(skill_sources)
        merged.confidence["skills"] = round(avg_conf, 4)
        merged.provenance["skills"] = Provenance(field="skills", source=skill_sources[0], method="union_canonicalized")

    all_exp: list[ExperienceEntry] = []
    for profile, _ in ordered:
        all_exp.extend(profile.experience)
    if all_exp:
        merged.experience = _merge_experiences(all_exp)
        exp_sources = [s for p, s in ordered if p.experience]
        merged.confidence["experience"] = field_confidence(exp_sources[0], "experience")
        merged.provenance["experience"] = Provenance(field="experience", source=exp_sources[0], method="dedup_richest")
        years = _years_experience(merged.experience)
        if years is not None:
            _set_field(merged, "years_experience", years, exp_sources[0], "derived_from_experience_dates")

    all_edu: list[EducationEntry] = []
    for profile, _ in ordered:
        all_edu.extend(profile.education)
    if all_edu:
        merged.education = _merge_educations(all_edu)
        edu_sources = [s for p, s in ordered if p.education]
        merged.confidence["education"] = field_confidence(edu_sources[0], "education")
        merged.provenance["education"] = Provenance(field="education", source=edu_sources[0], method="dedup_detail")

    for profile, source in ordered:
        if source == SourceType.GITHUB:
            if profile.github_repos:
                merged.github_repos = profile.github_repos
                merged.confidence["github_repos"] = field_confidence(source, "github_repos")
                merged.provenance["github_repos"] = Provenance(field="github_repos", source=source, method="api")
            if profile.github_languages:
                merged.github_languages = profile.github_languages
                merged.confidence["github_languages"] = field_confidence(source, "github_languages")
                merged.provenance["github_languages"] = Provenance(field="github_languages", source=source, method="api")

    return merged
