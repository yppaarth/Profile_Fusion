"""
Tests for the candidate-transformer pipeline.
Run with: pytest tests/ -v

Coverage:
  - Each normalizer
  - Each extractor (with minimal fixtures)
  - Merge logic (conflict resolution)
  - Entity matching
  - Projection config
  - Validation
  - Pipeline edge cases
"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.normalizers import (
    canonicalize_skill,
    canonicalize_skills,
    normalize_date,
    normalize_phone,
)
from src.validators import validate_email, validate_phone, validate_profile
from src.matcher import same_candidate
from src.schemas import (
    CanonicalProfile,
    EducationEntry,
    ExperienceEntry,
    Provenance,
    SourceType,
)
from src.merge import merge_profiles
from src.projection import apply_projection
from src.confidence import field_confidence, compute_overall


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

class TestPhoneNormalization:
    def test_us_number(self):
        assert normalize_phone("+14155552671") == "+14155552671"

    def test_us_formatted(self):
        assert normalize_phone("(415) 555-2671") == "+14155552671"

    def test_us_dashes(self):
        assert normalize_phone("415-555-2671") == "+14155552671"

    def test_indian_number(self):
        result = normalize_phone("+919876543210")
        assert result == "+919876543210"

    def test_invalid_returns_none(self):
        assert normalize_phone("not-a-number") is None

    def test_too_short_returns_none(self):
        assert normalize_phone("12345") is None

    def test_empty_returns_none(self):
        assert normalize_phone("") is None


class TestDateNormalization:
    def test_already_normalized(self):
        assert normalize_date("2022-01") == "2022-01"

    def test_year_only(self):
        assert normalize_date("2022") == "2022-01"

    def test_month_year_text(self):
        result = normalize_date("Jan 2020")
        assert result == "2020-01"

    def test_present(self):
        assert normalize_date("Present") == "present"
        assert normalize_date("present") == "present"
        assert normalize_date("Current") == "present"

    def test_none_input(self):
        assert normalize_date(None) is None

    def test_empty_string(self):
        assert normalize_date("") is None


class TestSkillCanonicalization:
    def test_exact_alias(self):
        assert canonicalize_skill("Machine learning") == "Machine Learning"
        assert canonicalize_skill("ML") == "Machine Learning"

    def test_cpp_variants(self):
        assert canonicalize_skill("C Plus Plus") == "C++"
        assert canonicalize_skill("c++") == "C++"
        assert canonicalize_skill("C++ Programming") == "C++"

    def test_unknown_skill_preserved(self):
        result = canonicalize_skill("SomeObscureFramework")
        assert result == "SomeObscureFramework"

    def test_dedup_in_list(self):
        skills = ["Python", "python", "Python3", "ML", "machine learning"]
        result = canonicalize_skills(skills)
        assert result.count("Python") == 1
        assert result.count("Machine Learning") == 1

    def test_empty_list(self):
        assert canonicalize_skills([]) == []


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class TestValidators:
    def test_valid_email(self):
        assert validate_email("user@example.com") is True

    def test_invalid_email_no_at(self):
        assert validate_email("userexample.com") is False

    def test_invalid_email_empty(self):
        assert validate_email("") is False
        assert validate_email(None) is False

    def test_valid_e164_phone(self):
        assert validate_phone("+14155552671") is True

    def test_invalid_phone(self):
        assert validate_phone("not-a-phone") is False
        assert validate_phone(None) is False

    def test_profile_warnings_no_name(self):
        p = CanonicalProfile(email="a@b.com")
        warnings = validate_profile(p)
        assert any("name" in w.lower() for w in warnings)

    def test_profile_warnings_no_email(self):
        p = CanonicalProfile(name="John Doe")
        warnings = validate_profile(p)
        assert any("email" in w.lower() for w in warnings)

    def test_profile_no_warnings_when_complete(self):
        p = CanonicalProfile(
            name="John Doe",
            email="john@example.com",
            phone="+14155551234",
            skills=["Python"],
            overall_confidence=0.85,
        )
        warnings = validate_profile(p)
        # May have no warnings or only minor ones
        bad_warnings = [w for w in warnings if "Invalid" in w or "No name" in w or "No email" in w]
        assert not bad_warnings


# ---------------------------------------------------------------------------
# Entity Matching
# ---------------------------------------------------------------------------

class TestEntityMatching:
    def test_same_email(self):
        a = {"email": "john@example.com", "phone": None, "name": "John"}
        b = {"email": "john@example.com", "phone": None, "name": "Johnny"}
        assert same_candidate(a, b) is True

    def test_same_phone(self):
        a = {"email": None, "phone": "+14155551234", "name": "Jane"}
        b = {"email": None, "phone": "(415) 555-1234", "name": "Jane Smith"}
        assert same_candidate(a, b) is True

    def test_different_people(self):
        a = {"email": "alice@example.com", "phone": "+14155551111", "name": "Alice"}
        b = {"email": "bob@example.com", "phone": "+14155552222", "name": "Bob"}
        assert same_candidate(a, b) is False

    def test_name_alone_not_sufficient(self):
        a = {"email": None, "phone": None, "name": "John Smith"}
        b = {"email": None, "phone": None, "name": "John Smith"}
        # No email or phone to corroborate — should NOT merge
        assert same_candidate(a, b) is False

    def test_different_emails_no_match(self):
        a = {"email": "alice@a.com", "phone": None, "name": "Alice"}
        b = {"email": "alice@b.com", "phone": None, "name": "Alice"}
        assert same_candidate(a, b) is False

    def test_same_name_without_identifiers_is_not_a_pipeline_warning(self, caplog):
        from src.pipeline import _check_entity_consistency

        csv_profile = CanonicalProfile(name="Priya Sharma", email="priya@example.com")
        linkedin_profile = CanonicalProfile(name="Priya Sharma")

        with caplog.at_level(logging.WARNING):
            _check_entity_consistency([
                (csv_profile, SourceType.CSV),
                (linkedin_profile, SourceType.LINKEDIN),
            ])

        assert "different candidate" not in caplog.text

    def test_conflicting_names_are_pipeline_warning(self, caplog):
        from src.pipeline import _check_entity_consistency

        csv_profile = CanonicalProfile(name="Priya Sharma", email="priya@example.com")
        linkedin_profile = CanonicalProfile(name="Alex Morgan")

        with caplog.at_level(logging.WARNING):
            _check_entity_consistency([
                (csv_profile, SourceType.CSV),
                (linkedin_profile, SourceType.LINKEDIN),
            ])

        assert "different candidate" in caplog.text


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

class TestMerge:
    def _make_profile(self, **kwargs) -> CanonicalProfile:
        return CanonicalProfile(**kwargs)

    def test_email_highest_confidence_wins(self):
        # CSV email has 0.98 confidence; resume has 0.92
        # Both have the same email here — CSV should win as source
        csv_p = self._make_profile(email="priya@example.com", name="Priya")
        resume_p = self._make_profile(email="priya@example.com", name="Priya Sharma")

        merged = merge_profiles([
            (csv_p, SourceType.CSV),
            (resume_p, SourceType.RESUME),
        ])
        assert merged.email == "priya@example.com"
        assert merged.provenance["email"].source == SourceType.CSV

    def test_name_longest_wins(self):
        csv_p = self._make_profile(name="Priya")
        resume_p = self._make_profile(name="Priya A. Sharma")
        linkedin_p = self._make_profile(name="Priya Sharma")

        merged = merge_profiles([
            (csv_p, SourceType.CSV),
            (resume_p, SourceType.RESUME),
            (linkedin_p, SourceType.LINKEDIN),
        ])
        assert merged.name == "Priya A. Sharma"

    def test_skills_union_and_dedup(self):
        p1 = self._make_profile(skills=["Python", "Go"])
        p2 = self._make_profile(skills=["python", "ML", "Kubernetes"])

        merged = merge_profiles([
            (p1, SourceType.CSV),
            (p2, SourceType.RESUME),
        ])
        skill_set = set(merged.skills)
        assert "Python" in skill_set
        assert "Go" in skill_set
        assert "Machine Learning" in skill_set  # ML → canonicalized
        assert "Kubernetes" in skill_set
        # No duplicates
        assert len(merged.skills) == len(set(merged.skills))

    def test_experience_dedup(self):
        exp = ExperienceEntry(
            title="SWE", company="Google", start_date="2020-01", source=SourceType.RESUME
        )
        exp2 = ExperienceEntry(
            title="SWE", company="google", start_date="2020-01",
            description="A longer description here", source=SourceType.LINKEDIN
        )
        p1 = self._make_profile()
        p1.experience = [exp]
        p2 = self._make_profile()
        p2.experience = [exp2]

        merged = merge_profiles([(p1, SourceType.RESUME), (p2, SourceType.LINKEDIN)])
        # Should deduplicate to one entry
        assert len(merged.experience) == 1
        # Should keep the richer description
        assert merged.experience[0].description == "A longer description here"

    def test_phone_normalized_to_e164(self):
        p = self._make_profile(phone="+14155552671")
        merged = merge_profiles([(p, SourceType.CSV)])
        assert merged.phone == "+14155552671"

    def test_missing_source_no_crash(self):
        p = self._make_profile(name="Only One Source", email="a@b.com")
        merged = merge_profiles([(p, SourceType.CSV)])
        assert merged.name == "Only One Source"
        assert merged.email == "a@b.com"


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_csv_email_highest(self):
        assert field_confidence(SourceType.CSV, "email") == 0.98

    def test_github_location_lowest(self):
        assert field_confidence(SourceType.GITHUB, "location") == 0.60

    def test_overall_confidence_empty_profile(self):
        p = CanonicalProfile()
        assert compute_overall(p) == 0.0

    def test_overall_confidence_with_fields(self):
        p = CanonicalProfile()
        p.confidence = {"email": 0.98, "name": 0.95, "skills": 0.82}
        score = compute_overall(p)
        assert 0.0 < score <= 1.0


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class TestProjection:
    def _profile(self) -> CanonicalProfile:
        p = CanonicalProfile(
            name="Jane Doe",
            email="jane@example.com",
            phone="+14155551234",
            skills=["Python", "Go"],
            overall_confidence=0.88,
        )
        p.confidence = {"name": 0.95, "email": 0.98, "phone": 0.95}
        p.provenance = {
            "name": Provenance(field="name", source=SourceType.CSV, method="structured"),
            "email": Provenance(field="email", source=SourceType.CSV, method="structured"),
        }
        p.sources_used = [SourceType.CSV]
        return p

    def test_include_subset(self):
        p = self._profile()
        result = apply_projection(p, {"include": ["name", "email"]})
        assert "name" in result
        assert "email" in result
        assert "phone" not in result or result.get("phone") is None

    def test_field_rename(self):
        p = self._profile()
        result = apply_projection(p, {"rename": {"email": "contact_email"}, "show_confidence": False, "show_provenance": False})
        assert "contact_email" in result
        assert "email" not in result

    def test_missing_policy_omit(self):
        p = self._profile()
        result = apply_projection(
            p,
            {"include": ["name", "location"], "missing_policy": "omit", "show_confidence": False, "show_provenance": False}
        )
        # location is None — should be omitted
        assert "location" not in result
        assert "name" in result

    def test_missing_policy_null(self):
        p = self._profile()
        result = apply_projection(
            p,
            {"include": ["name", "location"], "missing_policy": "null", "show_confidence": False, "show_provenance": False}
        )
        assert result.get("location") is None

    def test_missing_policy_error(self):
        p = self._profile()
        from src.projection import ProjectionError
        with pytest.raises(ProjectionError):
            apply_projection(
                p,
                {"include": ["name", "location"], "missing_policy": "error", "show_confidence": False, "show_provenance": False}
            )

    def test_confidence_included(self):
        p = self._profile()
        result = apply_projection(p, {"show_confidence": True, "show_provenance": False})
        assert "confidence" in result
        assert "overall_confidence" in result

    def test_provenance_excluded(self):
        p = self._profile()
        result = apply_projection(p, {"show_confidence": False, "show_provenance": False})
        assert "provenance" not in result

    def test_provenance_included(self):
        p = self._profile()
        result = apply_projection(p, {"show_confidence": False, "show_provenance": True})
        assert "provenance" in result

    def test_assignment_schema_default_fields(self):
        p = self._profile()
        result = apply_projection(p, {"show_confidence": False, "show_provenance": True})
        for field in ["candidate_id", "full_name", "emails", "phones", "location", "links", "headline", "years_experience", "skills", "experience", "education", "provenance", "overall_confidence"]:
            assert field in result

    def test_normalization_config_applies_to_output(self):
        p = self._profile()
        p.phones = ["(415) 555-1234"]
        result = apply_projection(p, {"include": ["phones"], "normalize": ["phones"], "show_confidence": False, "show_provenance": False})
        assert result["phones"] == ["+14155551234"]




# ---------------------------------------------------------------------------
# Resume Extractor Heuristics
# ---------------------------------------------------------------------------

class TestResumeExtractorHeuristics:
    def test_experience_titles_are_not_swallowed_by_previous_description(self):
        from src.extractors.resume_source import _parse_experience

        entries = _parse_experience([
            "Senior Software Engineer",
            "Stripe | Jan 2022 – Present",
            "Led redesign of payment routing engine.",
            "Software Engineer II",
            "Google | Jun 2019 – Dec 2021",
            "Improved storage costs by 15%.",
            "Software Engineering Intern",
            "Microsoft | May 2018 – Aug 2018",
            "Built regression testing tooling.",
        ])

        assert [e.title for e in entries] == [
            "Senior Software Engineer",
            "Software Engineer II",
            "Software Engineering Intern",
        ]
        assert [e.company for e in entries] == ["Stripe", "Google", "Microsoft"]
        assert "Software Engineer II" not in (entries[0].description or "")
        assert "15%" in (entries[1].description or "")

    def test_education_degree_precedes_school_date_line(self):
        from src.extractors.resume_source import _parse_education

        entries = _parse_education([
            "Master of Science, Computer Science",
            "Carnegie Mellon University | 2017 – 2019",
            "Bachelor of Technology, Computer Science",
            "IIT Bombay | 2013 – 2017",
        ])

        assert [e.school for e in entries] == ["Carnegie Mellon University", "IIT Bombay"]
        assert [e.degree for e in entries] == [
            "Master of Science, Computer Science",
            "Bachelor of Technology, Computer Science",
        ]
        assert entries[0].field_of_study == "Computer Science"


# ---------------------------------------------------------------------------
# CSV Extractor
# ---------------------------------------------------------------------------

class TestCSVExtractor:
    def test_valid_csv(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,email,phone,current_company,title\nJane Doe,jane@example.com,+14155551234,Acme,Engineer\n")
        from src.extractors.csv_source import extract
        p = extract(csv_file)
        assert p.name == "Jane Doe"
        assert p.email == "jane@example.com"
        assert p.phone == "+14155551234"

    def test_missing_column_tolerant(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,email\nJane Doe,jane@example.com\n")
        from src.extractors.csv_source import extract
        p = extract(csv_file)
        assert p.name == "Jane Doe"
        assert p.phone is None

    def test_malformed_csv_empty(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("name,email,phone,current_company,title\n")
        from src.extractors.csv_source import extract
        p = extract(csv_file)
        # Should return empty profile, not crash
        assert p.name is None

    def test_file_not_found(self):
        from src.extractors.csv_source import extract
        with pytest.raises(FileNotFoundError):
            extract("/nonexistent/path.csv")


# ---------------------------------------------------------------------------
# GitHub Extractor
# ---------------------------------------------------------------------------

class TestGitHubExtractor:
    def test_from_json(self, tmp_path):
        data = {
            "user": {
                "login": "testuser",
                "name": "Test User",
                "bio": "A test bio",
                "location": "New York, NY",
                "blog": "https://testuser.dev",
                "html_url": "https://github.com/testuser",
            },
            "repos": [
                {"name": "my-repo", "language": "Python", "stargazers_count": 5, "fork": False},
                {"name": "forked", "language": "Go", "stargazers_count": 0, "fork": True},
            ]
        }
        json_file = tmp_path / "github.json"
        json_file.write_text(json.dumps(data))

        from src.extractors.github_source import extract_from_json
        p = extract_from_json(json_file)
        assert p.name == "Test User"
        assert p.bio == "A test bio"
        assert p.location == "New York, NY"
        assert "my-repo" in p.github_repos
        # Forked repos excluded
        assert "forked" not in p.github_repos
        assert "Python" in p.github_languages

    def test_missing_json(self, tmp_path):
        from src.extractors.github_source import extract_from_json
        with pytest.raises(FileNotFoundError):
            extract_from_json(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# LinkedIn Extractor
# ---------------------------------------------------------------------------

class TestLinkedInExtractor:
    def _sample_html(self) -> str:
        return """
        <html>
        <head><link rel="canonical" href="https://linkedin.com/in/testuser/"></head>
        <body>
          <h1 class="name">Test User</h1>
          <p class="headline">Senior Engineer at ACME</p>
          <p class="location">San Francisco, CA</p>
          <section id="experience">
            <h2>Experience</h2>
            <ul>
              <li>
                <span class="title">Senior Engineer</span>
                <span class="company">ACME Corp</span>
                <span class="date-period">Jan 2021 – Present</span>
              </li>
            </ul>
          </section>
          <section id="skills">
            <h2>Skills</h2>
            <ul><li>Python</li><li>Machine Learning</li></ul>
          </section>
        </body>
        </html>
        """

    def test_basic_extraction(self, tmp_path):
        html_file = tmp_path / "linkedin.html"
        html_file.write_text(self._sample_html())
        from src.extractors.linkedin_source import extract
        p = extract(html_file)
        assert p.name == "Test User"
        assert p.headline == "Senior Engineer at ACME"
        assert "Python" in p.skills
        assert "Machine Learning" in p.skills

    def test_profile_url_extracted(self, tmp_path):
        html_file = tmp_path / "linkedin.html"
        html_file.write_text(self._sample_html())
        from src.extractors.linkedin_source import extract
        p = extract(html_file)
        assert "linkedin.com/in/testuser" in (p.profile_url or "")


# ---------------------------------------------------------------------------
# Integration: full pipeline with sample files
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    def test_csv_only_pipeline(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,email,phone,current_company,title\nJane Doe,jane@example.com,+14155551234,Acme,Engineer\n")
        from src.pipeline import run
        result = run(csv_path=str(csv_file))
        assert result.get("full_name") == "Jane Doe"
        assert result.get("emails") == ["jane@example.com"]
        assert result.get("phones") == ["+14155551234"]
        assert result.get("candidate_id", "").startswith("cand_")
        assert "overall_confidence" in result

    def test_no_sources_raises(self):
        from src.pipeline import run
        with pytest.raises(ValueError):
            run()

    def test_nonexistent_sources_skip_gracefully(self):
        from src.pipeline import run
        with pytest.raises(ValueError):
            # All paths don't exist, should raise ValueError ("no valid sources")
            run(csv_path="/nonexistent.csv")
