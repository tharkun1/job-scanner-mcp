"""Remotive.com — free public API, no auth. Remote-only tech jobs globally."""

import requests
from datetime import date

from tools.profiles import QA, Profile

API_URL = "https://remotive.com/api/remote-jobs"

HEADERS = {"User-Agent": "JobScanner/1.0"}


def fetch(profile: Profile = QA) -> list[dict]:
    seen_ids: set[int] = set()
    results = []
    today = date.today().isoformat()

    for category in profile.remotive_categories:
        try:
            resp = requests.get(
                API_URL,
                params={"category": category, "limit": 100},
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            print(f"  [Remotive/{category}] Failed: {e}")
            continue

        for job in jobs:
            job_id = job.get("id")
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = job.get("title", "")

            # Apply keyword filter to ALL categories (Remotive categories are broad)
            if not profile.matches(title):
                continue

            if profile.excluded(title):
                continue

            salary = job.get("salary", "")
            url = job.get("url", "")

            results.append({
                "title": title,
                "company": job.get("company_name", ""),
                "salary": salary,
                "source": "Remotive",
                "url": url,
                "found_date": today,
            })

    return results
