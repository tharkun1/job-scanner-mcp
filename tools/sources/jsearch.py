"""JSearch source via RapidAPI — covers LinkedIn, Indeed, Glassdoor, ZipRecruiter.
Free tier: 200 requests/month. Uses 2 queries per run = ~8 runs/month budget."""

import json
import os
import requests
from datetime import date
from pathlib import Path

from tools.profiles import QA, Profile

API_URL = "https://jsearch.p.rapidapi.com/search"
# RapidAPI reports the requests left in each response; below this reserve JSearch is skipped until next month
QUOTA_FILE = Path(__file__).resolve().parents[2] / "jsearch-quota.json"
QUOTA_RESERVE = 15

# Spam aggregator domains that appear as fake "employers" on Indeed
SPAM_EMPLOYER_PATTERNS = {
    "railway.app", "vercel.app", "netlify.app", "herokuapp.com",
    "render.com", "glitch.me", "replit.dev",
}


def fetch(profile: Profile = QA) -> list[dict]:
    api_key = os.environ.get("RAPIDAPI_KEY")
    if not api_key:
        print("[JSearch] RAPIDAPI_KEY not set — skipping")
        return []

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    seen_urls: set[str] = set()
    seen_jobs: set[tuple[str, str]] = set()
    results = []
    today = date.today().isoformat()

    for query in profile.jsearch_queries:
        remaining = _remaining()
        if remaining is not None and remaining < QUOTA_RESERVE:
            print(f"[JSearch] Only {remaining} requests left this month — skipping JSearch until the quota resets")
            break
        try:
            jobs = _search(query, headers)
        except Exception as e:
            print(f"[JSearch] Query '{query}' failed: {e}")
            continue

        for job in jobs:
            url = job.get("job_apply_link") or job.get("job_google_link", "")
            if not url or url in seen_urls:
                continue

            title = job.get("job_title", "")
            company = job.get("employer_name", "")

            if profile.excluded(title):
                continue

            # Skip spam aggregator entries (fake "employers" are deployment URLs)
            if any(spam in company.lower() for spam in SPAM_EMPLOYER_PATTERNS):
                continue

            # Remote check — JSearch has an explicit flag
            if not job.get("job_is_remote", False):
                # Also check if "remote" appears in job description
                desc = (job.get("job_description") or "").lower()
                if "remote" not in desc:
                    continue

            dedup_key = (title.lower(), company.lower())
            if dedup_key in seen_jobs:
                continue
            seen_urls.add(url)
            seen_jobs.add(dedup_key)
            salary = _format_salary(job)

            results.append(
                {
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "source": "LinkedIn/Indeed (JSearch)",
                    "url": url,
                    "found_date": today,
                }
            )

    return results


def _remaining():
    """Requests left this month, as last reported by RapidAPI (None if never seen this month)."""
    try:
        data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("month") != date.today().strftime("%Y-%m"):
        return None  # new month: the quota has reset
    return data.get("remaining")


def _search(query: str, headers: dict) -> list[dict]:
    # "query@pl" searches in Poland (JSearch defaults to the US)
    query, _, country = query.partition("@")
    params = {
        "query": query,
        "page": "1",
        "num_pages": "1",  # one page per query saves the 200/month quota (2026-11-12)
        "date_posted": "week",
        "work_from_home": "true",
    }
    if country:
        params["country"] = country
    resp = requests.get(API_URL, headers=headers, params=params, timeout=30)
    left = resp.headers.get("x-ratelimit-requests-remaining")
    if left is not None and left.isdigit():
        QUOTA_FILE.write_text(json.dumps({"month": date.today().strftime("%Y-%m"), "remaining": int(left),
                                          "limit": resp.headers.get("x-ratelimit-requests-limit")}), encoding="utf-8")
    resp.raise_for_status()
    return resp.json().get("data", [])


def _format_salary(job: dict) -> str:
    lo = job.get("job_min_salary")
    hi = job.get("job_max_salary")
    period = job.get("job_salary_period", "")
    currency = job.get("job_salary_currency", "USD")

    if lo and hi:
        label = f"{lo:,.0f}–{hi:,.0f} {currency}"
        if period:
            label += f"/{period.lower()}"
        return label
    return ""
