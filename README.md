# Profile Fusion

Transforms candidate data from multiple heterogeneous sources (structured CSV, PDF resume, LinkedIn HTML, GitHub API) into one assignment-compliant canonical profile with `candidate_id`, `full_name`, `emails[]`, `phones[]`, structured location, links, experience, education, provenance, and confidence scores.

---

## Architecture

The pipeline has 9 isolated stages:

```
Source Detection → Extract → Normalize → Entity Matching → Conflict Resolution
       → Confidence Scoring → Canonical Profile → Projection Layer → Output JSON
```

Each stage is a separate module. The pipeline (`src/pipeline.py`) is pure orchestration — no business logic lives there.

### Source types

| Source          | Type               | Fields                                                                       |
| --------------- | ------------------ | ---------------------------------------------------------------------------- |
| Recruiter CSV   | Structured         | full_name, emails, phones, current_company, title                            |
| Resume PDF      | Unstructured       | skills, experience, education, emails, phones, structured location, headline |
| LinkedIn HTML   | Unstructured       | headline, experience, education, skills, location, LinkedIn URL              |
| GitHub JSON/URL | Unstructured (API) | full_name, bio, repositories, languages, location, GitHub URL, website       |

---

## Project Structure

```
candidate-transformer/
├── README.md
├── requirements.txt
├── generate_sample_pdf.py     # generates data/resume.pdf
├── config/
│   ├── default_projection.json
│   └── sample_projection.json
├── data/
│   ├── sample.csv
│   ├── resume.pdf
│   ├── linkedin.html
│   └── github.json
├── src/
│   ├── cli.py                 # CLI entry point (Typer + Rich)
│   ├── pipeline.py            # Pipeline orchestrator
│   ├── schemas.py             # Pydantic models (CanonicalProfile, Provenance, etc.)
│   ├── normalizers.py         # Phone (E.164), dates (YYYY-MM), skills (canonical map)
│   ├── validators.py          # Email/phone validation, profile completeness checks
│   ├── confidence.py          # Per-field confidence weights + overall score
│   ├── matcher.py             # Entity matching (email, phone, fuzzy name)
│   ├── merge.py               # Deterministic conflict resolution
│   ├── projection.py          # Config-driven output transformation
│   └── extractors/
│       ├── csv_source.py      # pandas CSV parser
│       ├── resume_source.py   # pdfplumber + heuristic section parser
│       ├── linkedin_source.py # BeautifulSoup HTML parser
│       └── github_source.py   # GitHub REST API or pre-fetched JSON
├── tests/
│   └── test_pipeline.py       # pytest coverage for normalizers, extractors, merge, projection, validation
└── sample_outputs/
    ├── default_output.json
    └── custom_config_output.json
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Generate the sample resume PDF (only needed once)
venv/bin/python generate_sample_pdf.py
```

---

## Running

```bash
# Full run with all four sources
PYTHONPATH=. venv/bin/python src/cli.py \
  --csv data/sample.csv \
  --resume data/resume.pdf \
  --linkedin data/linkedin.html \
  --github data/github.json

# With custom output config (field renames, subset, no provenance)
PYTHONPATH=. venv/bin/python src/cli.py \
  --csv data/sample.csv \
  --resume data/resume.pdf \
  --linkedin data/linkedin.html \
  --github data/github.json \
  --config config/sample_projection.json

# Save to file
PYTHONPATH=. venv/bin/python src/cli.py \
  --csv data/sample.csv \
  --github data/github.json \
  --output out.json

# GitHub by username (live API)
PYTHONPATH=. venv/bin/python src/cli.py \
  --github priya-sharma-dev

# Verbose mode (debug logging)
PYTHONPATH=. venv/bin/python src/cli.py --csv data/sample.csv -v

# Run tests
PYTHONPATH=. venv/bin/python -m pytest tests/ -v
```

---

## Projection Config

The projection layer is entirely config-driven. Place a JSON file with any of these keys:

```json
{
  "include": ["candidate_id", "full_name", "emails", "skills"],
  "rename": { "full_name": "candidate_name", "emails": "contact_emails" },
  "normalize": {
    "phones": "e164",
    "skills": "canonical",
    "location": "structured"
  },
  "show_confidence": true,
  "show_provenance": false,
  "missing_policy": "omit"
}
```

No code changes required for different output schemas.

---

## Merge Strategy

Priority: **CSV → Resume → LinkedIn → GitHub** (highest to lowest).

| Field            | Rule                                                                       |
| ---------------- | -------------------------------------------------------------------------- |
| emails           | Highest confidence email wins; all emails are deduplicated into `emails[]` |
| phones           | Priority order, normalized to E.164, deduplicated into `phones[]`          |
| full_name        | Longest valid name across sources                                          |
| location         | First non-null in priority order, parsed into `{city, region, country}`    |
| skills           | Union across all sources, then canonicalized and deduplicated              |
| experience       | Merge duplicates by (company, title, start_date); keep richer description  |
| education        | Merge duplicates by (school, degree)                                       |
| headline         | Resume → LinkedIn → GitHub bio                                             |
| years_experience | Derived deterministically from normalized experience date ranges           |
| links            | Source-specific map for LinkedIn, GitHub, and website URLs                 |

---

## Confidence Scoring

Every field gets a base confidence by `(source, field)` pair:

| Source   | Email | Location | Skills |
| -------- | ----- | -------- | ------ |
| CSV      | 0.98  | —        | —      |
| Resume   | 0.92  | 0.75     | 0.82   |
| LinkedIn | —     | 0.80     | 0.78   |
| GitHub   | —     | 0.60     | —      |

`overall_confidence` = weighted average across all populated fields (email weighted 2×, name 1.5×, scalar fields 0.5-1×).

Every public canonical field can carry provenance:

```json
{
  "field": "emails",
  "source": "csv",
  "method": "highest_confidence_deduped"
}
```

---

## Assumptions

- CSV contains exactly one candidate per file (the CLI is single-candidate).
- LinkedIn input is a saved/exported HTML file, not live-scraped.
- GitHub input can be a pre-fetched JSON (offline) or a live username/URL.
- Resume PDFs contain machine-readable text (not scanned images/OCR).
- Phone normalization defaults to US region when no country code is present.

---

## Tradeoffs

**Heuristic PDF parsing vs. ML extraction**: Section detection by keyword headers is fast, explainable, and zero-dependency. It fails on creative resume layouts. An ML-based extractor (e.g. LayoutLM) would generalize better but adds significant complexity and model weight — not appropriate for a demo system.

**Deterministic merge vs. probabilistic**: Hard-coded priority rules are predictable and debuggable. In production you'd want A/B-testable merge strategies and possibly a learned ranker. The current design makes the merge strategy explicit and auditable, which matters for HR tooling.

**Entity matching conservatism**: We require email or phone to confirm a match — name alone is insufficient. This means we might output a slightly incomplete profile if sources have typos in emails, but we never corrupt profiles by merging two different people.

---

## Future Improvements

- Resume OCR support (PyTesseract / AWS Textract) for scanned PDFs
- ML-based section extraction (LayoutLM, Donut) for layout-invariant parsing
- Batch processing: multiple candidates from one CSV
- Learned confidence calibration from human-labeled merge decisions
- Plugin architecture for adding new sources without touching the core pipeline
- REST API wrapper around the pipeline for service deployment
