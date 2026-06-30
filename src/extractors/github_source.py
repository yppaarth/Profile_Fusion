"""
GitHub extractor.
Accepts either:
  1. A path to a pre-fetched JSON file (data/github.json) — used in offline/demo mode
  2. A GitHub username or profile URL — fetches live via REST API

Design: we support both modes so the pipeline works without a GitHub token
(public API has 60 req/hr unauthenticated). The JSON format matches the
GitHub API response exactly, so the same parsing logic handles both cases.

No Selenium, no HTML scraping — the REST API is cleaner and more stable.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests

from src.schemas import CanonicalProfile, SourceType

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _auth_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return {**HEADERS, "Authorization": f"Bearer {token}"}
    return HEADERS


def _extract_username(url_or_name: str) -> str:
    """Parse 'github.com/johndoe' or just 'johndoe'."""
    m = re.search(r"github\.com/([^/\s?#]+)", url_or_name)
    return m.group(1) if m else url_or_name.strip().lstrip("@")


def _fetch_user(username: str) -> dict:
    resp = requests.get(
        f"{GITHUB_API}/users/{username}",
        headers=_auth_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_repos(username: str) -> list[dict]:
    resp = requests.get(
        f"{GITHUB_API}/users/{username}/repos",
        headers=_auth_headers(),
        params={"sort": "pushed", "per_page": 30},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_user_json(user: dict, repos: list[dict]) -> CanonicalProfile:
    profile = CanonicalProfile()

    profile.name = user.get("name") or user.get("login")
    profile.bio = user.get("bio")
    profile.location = user.get("location")
    profile.website = user.get("blog") or user.get("html_url")
    profile.profile_url = user.get("html_url")

    # Top repos (non-fork, by star count)
    public_repos = [r for r in repos if not r.get("fork", False)]
    public_repos.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
    profile.github_repos = [r["name"] for r in public_repos[:10] if r.get("name")]

    # Languages across repos (deduplicated, ordered by frequency)
    lang_counts: dict[str, int] = {}
    for repo in repos:
        lang = repo.get("language")
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    profile.github_languages = [
        lang for lang, _ in sorted(lang_counts.items(), key=lambda x: -x[1])
    ]

    return profile


def extract_from_json(path: str | Path) -> CanonicalProfile:
    """Load from pre-fetched JSON. Supports both user+repos combined or user-only."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GitHub JSON not found: {path}")

    with open(path) as f:
        data = json.load(f)

    # Accept two formats: {"user": {...}, "repos": [...]} or just the user object
    if "user" in data:
        user = data["user"]
        repos = data.get("repos", [])
    else:
        user = data
        repos = []

    return _parse_user_json(user, repos)


def extract_from_url(url_or_username: str) -> CanonicalProfile:
    """Fetch live from GitHub API."""
    username = _extract_username(url_or_username)
    log.info("Fetching GitHub profile for: %s", username)
    try:
        user = _fetch_user(username)
        repos = _fetch_repos(username)
        return _parse_user_json(user, repos)
    except requests.HTTPError as e:
        log.error("GitHub API error for %s: %s", username, e)
        return CanonicalProfile()
    except requests.RequestException as e:
        log.error("Network error fetching GitHub profile: %s", e)
        return CanonicalProfile()


def extract(path_or_url: str | Path) -> CanonicalProfile:
    """
    Dispatch: if path_or_url is an existing file, load JSON.
    Otherwise treat as a URL or username and fetch from API.
    """
    p = Path(str(path_or_url))
    if p.exists() and p.suffix == ".json":
        return extract_from_json(p)
    return extract_from_url(str(path_or_url))
