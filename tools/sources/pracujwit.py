"""Pracuj.pl IT jobs via the pracujwit.pl RSS feed — no auth required."""

import feedparser
from datetime import date

from tools.profiles import QA, Profile

RSS_URL = "https://pracujwit.pl/rss/Testowanie/"

QA_KEYWORDS = {
    "qa", "quality assurance", "test automation", "playwright", "sdet",
    "tester", "qa engineer", "test engineer", "automated testing",
    "selenium", "cypress", "automation engineer",
}

EXCLUDE_KEYWORDS = {"intern", "staz", "praktykant"}  # "junior" allowed since 2026-11-10

REMOTE_KEYWORDS = {"remote", "zdaln", "home office", "praca zdalna"}


def fetch(profile: Profile = QA) -> list[dict]:
    # The RSS feed is the testing category only — meaningless for other profiles
    if not profile.use_pracuj:
        return []
    try:
        feed = feedparser.parse(RSS_URL)
    except Exception as e:
        print(f"[Pracuj.pl] Failed to parse RSS: {e}")
        return []

    results = []
    today = date.today().isoformat()
    # Recruitment agencies (e.g. GRH Polska) post the same role repeatedly over weeks
    seen_jobs: set[tuple[str, str]] = set()

    for entry in feed.entries:
        title = entry.get("title", "")
        title_lower = title.lower()
        summary = entry.get("summary", "").lower()
        combined = title_lower + " " + summary

        # Must be QA/testing related
        if not any(kw in title_lower for kw in QA_KEYWORDS):
            continue

        # Exclude interns, and the profile's own exclusions (senior/lead roles, 2026-11-12)
        if any(kw in title_lower for kw in EXCLUDE_KEYWORDS) or profile.excluded(title):
            continue

        # Must mention remote somewhere in title or summary
        if not any(kw in combined for kw in REMOTE_KEYWORDS):
            continue

        url = entry.get("link", "")
        company = _extract_company(entry)

        dedup_key = (title_lower, company.lower())
        if dedup_key in seen_jobs:
            continue
        seen_jobs.add(dedup_key)

        results.append(
            {
                "title": title,
                "company": company,
                "salary": "",  # RSS doesn't include salary
                "source": "Pracuj.pl",
                "url": url,
                "found_date": today,
            }
        )

    return results


def _extract_company(entry: dict) -> str:
    # Author field is absent in pracujwit.pl RSS; extract from URL slug instead.
    # URL pattern: .../job-title-at-company-name/
    url = entry.get("link", "")
    slug = url.rstrip("/").split("/")[-1]
    if "-at-" in slug:
        company_slug = slug.split("-at-", 1)[-1]
        return company_slug.replace("-", " ").title()
    author = entry.get("author", "")
    if author:
        return author
    return ""
