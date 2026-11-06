"""RemoteOK — free public API, no auth. Best source for remote QA jobs at western tech companies."""

import requests
from datetime import date

from tools.profiles import QA, Profile

API_BASE = "https://remoteok.com/api?tags="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobScanner/1.0)",
    "Accept": "application/json",
}


def fetch(profile: Profile = QA) -> list[dict]:
    seen_ids: set[str] = set()
    results = []
    today = date.today().isoformat()

    for tag in profile.remoteok_tags:
        url = API_BASE + tag
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [RemoteOK/{tag}] Failed: {e}")
            continue

        # First element is metadata, skip it
        jobs = [item for item in data if isinstance(item, dict) and "id" in item]

        for job in jobs:
            job_id = str(job.get("id", ""))
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = job.get("position", "")

            if not profile.matches(title):
                continue

            if profile.excluded(title):
                continue

            url_link = job.get("url", "")
            if not url_link:
                slug = job.get("slug", "")
                url_link = f"https://remoteok.com/remote-jobs/{job_id}-{slug}" if slug else ""

            salary = _format_salary(job)
            company = job.get("company", "")

            results.append(
                {
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "source": "RemoteOK",
                    "url": url_link,
                    "found_date": today,
                }
            )

    return results


def _format_salary(job: dict) -> str:
    lo = job.get("salary_min") or job.get("salary")
    hi = job.get("salary_max")
    if lo and hi and lo != hi:
        return f"${int(lo):,}–${int(hi):,}/yr"
    if lo:
        return f"${int(lo):,}+/yr"
    return ""
