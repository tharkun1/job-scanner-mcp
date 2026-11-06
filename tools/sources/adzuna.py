"""Adzuna source — official API, free tier (250 req/day). Covers Poland + EU + US."""

import os
import requests
from datetime import date

from tools.profiles import QA, Profile

BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# (country_code, currency_symbol)
COUNTRIES = [
    ("pl", "PLN"),
    ("gb", "GBP"),
    # ("us", "USD") removed 2026-10-25: Adzuna US ads say "not available in your region" from Poland
]

def fetch(profile: Profile = QA) -> list[dict]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("[Adzuna] ADZUNA_APP_ID or ADZUNA_APP_KEY not set — skipping")
        return []

    # Dedup by (title, company) — same job posted with slightly different salaries
    seen_jobs: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    results = []
    today = date.today().isoformat()

    searches = [(q, c, cur, None) for q in profile.adzuna_queries for c, cur in COUNTRIES]
    searches += [(q, "pl", "PLN", city) for q in profile.regional_queries for city in profile.regional_where]
    for query, country, currency, where in searches:
        if True:
            try:
                jobs = _search(app_id, app_key, query, country, where)
            except Exception as e:
                # str(e) contains the request URL with app_key — print only the error type/status
                status = getattr(getattr(e, "response", None), "status_code", "")
                print(f"  [Adzuna/{country}] Query '{query}' failed: {type(e).__name__} {status}")
                continue

            for job in jobs:
                url = job.get("redirect_url", "")
                if not url or url in seen_urls:
                    continue

                title = job.get("title", "")
                company = job.get("company", {}).get("display_name", "")
                title_lower = title.lower()

                if not profile.matches(title):
                    continue

                # Adzuna has no remote flag — require remote wording (English or Polish) in the title itself,
                # except for the city searches (on-site / hybrid roles near home, chosen by the owner)
                if where is None and not any(w in title_lower for w in ("remote", "zdaln", "home office")):
                    continue

                if profile.excluded(title):
                    continue

                dedup_key = (title_lower, company.lower())
                if dedup_key in seen_jobs:
                    continue

                seen_urls.add(url)
                seen_jobs.add(dedup_key)
                salary = _format_salary(job, currency)

                results.append({
                    "title": title,
                    "company": company,
                    "salary": salary,
                    "source": "Adzuna",
                    "url": url,
                    "found_date": today,
                    "location": (job.get("location") or {}).get("display_name", ""),
                })

    return results


def _search(app_id: str, app_key: str, query: str, country: str, where: str | None = None) -> list[dict]:
    url = f"{BASE_URL}/{country}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "content-type": "application/json",
        "results_per_page": 20,
        "sort_by": "date",
        "max_days_old": 14,
    }
    if where:
        params["where"] = where
        params["distance"] = 30
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _format_salary(job: dict, currency: str) -> str:
    lo = job.get("salary_min")
    hi = job.get("salary_max")
    if lo and hi and lo != hi:
        return f"{lo:,.0f}–{hi:,.0f} {currency}"
    if lo:
        return f"{lo:,.0f}+ {currency}"
    return ""
