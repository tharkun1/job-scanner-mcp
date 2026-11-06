"""No Fluff Jobs source — uses the site's internal JSON API."""

import requests
from datetime import date

from tools.profiles import QA, Profile

API_URL = "https://nofluffjobs.com/api/posting"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def fetch(profile: Profile = QA) -> list[dict]:
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [NoFluffJobs] Failed to fetch: {e}")
        return []

    postings = data if isinstance(data, list) else data.get("postings", [])

    today = date.today().isoformat()
    # Key: (title, company) → best candidate job dict
    # Same job is posted once per Polish region; keep only one, preferring the "-remote" slug.
    best: dict[tuple[str, str], dict] = {}

    for post in postings:
        # Remote check — fullyRemote lives inside location (top-level is always False).
        # Profiles with regional_cities also accept on-site / hybrid offers in those cities.
        loc = post.get("location", {}) or {}
        cities = [str(p.get("city", "")).lower() for p in loc.get("places", []) if isinstance(p, dict)]
        remote = bool(loc.get("fullyRemote", False))
        regional = [c for c in cities if any(rc in c for rc in profile.regional_cities)]
        if not remote and not regional:
            continue
        location = "Zdalnie" if remote else ", ".join(sorted(set(c.title() for c in regional)))

        # 'name' = company name, 'title' = actual job title
        title = post.get("title", "")
        company = post.get("name", "")
        title_lower = title.lower()

        if not profile.matches(title):
            continue

        if profile.excluded(title):
            continue

        slug = post.get("url", "") or post.get("id", "")
        url = f"https://nofluffjobs.com/job/{slug}" if not slug.startswith("http") else slug
        salary = _format_salary(post)

        key = (title_lower, company.lower())
        existing = best.get(key)
        if existing is None:
            best[key] = {"title": title, "company": company, "salary": salary,
                         "source": "NoFluffJobs", "url": url, "found_date": today, "location": location}
        elif "remote" in slug.lower() and "remote" not in existing["url"].lower():
            # Upgrade to the remote-labelled URL
            best[key]["url"] = url

    return list(best.values())


def _format_salary(post: dict) -> str:
    salary = post.get("salary")
    if not salary:
        return ""
    lo = salary.get("from", "")
    hi = salary.get("to", "")
    currency = salary.get("currency", "PLN").upper()
    if lo and hi:
        return f"{int(lo):,}–{int(hi):,} {currency}"
    if lo:
        return f"{int(lo):,}+ {currency}"
    return ""
