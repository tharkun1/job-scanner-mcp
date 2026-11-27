"""SOLID.Jobs source (added 2026-11-18, the owner's request).

The site's own offer list (the JSON its offer pages load): one request returns all current IT offers
(about 1,400). robots.txt allows automated access ("Allow: /", only /management/ and /admin/ are closed).
The API answers only with its own Accept type, so the header below is required.

Rules (same as the other sources and the owner's limits):
  - fully remote offers are kept;
  - offers in his home region (profile.regional_cities) are kept whatever the work mode;
  - hybrid / partly remote offers elsewhere are kept with a "check the office days" note (every offer counts);
  - on-site offers outside the region, senior-level offers and internships are dropped.
"""

from datetime import date

import requests

from tools.profiles import QA, Profile

API_URL = "https://solid.jobs/api/offers?division={division}&sortOrder=default"  # it, sales, marketing, hr, logistics, engineering, other
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/vnd.solidjobs.jobofferlist+json, application/json",
}
REMOTE = {"w całości", "możliwa w całości", "dowolnie", "stacjonarnie lub zdalnie"}
PARTLY = {"hybrydowo", "możliwa częściowo"}
SKIP_LEVELS = {"senior", "staż"}

_cache: dict[str, list] = {}  # one download per section per run, shared by all profiles


def _offers(division: str = "it") -> list[dict]:
    if division not in _cache:
        resp = requests.get(API_URL.format(division=division), headers=HEADERS, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        _cache[division] = data if isinstance(data, list) else []
    return _cache[division]


def _salary(o: dict) -> str:
    s = o.get("salaryRange") or {}
    lo, hi = s.get("lowerBound"), s.get("upperBound")
    if not lo and not hi:
        return ""
    cur = s.get("currency") or "PLN"
    kind = s.get("employmentType") or ""
    period = {"Month": "/mies.", "Hour": "/godz.", "Day": "/dzień"}.get(s.get("salaryPeriod") or "", "")
    rng = f"{int(lo):,}–{int(hi):,}".replace(",", " ") if lo and hi else f"{int(lo or hi):,}".replace(",", " ")
    return f"{rng} {cur}{period} {kind}".strip()


def fetch(profile: Profile = QA) -> list[dict]:
    offers = []
    for division in getattr(profile, "solid_divisions", ["it"]):
        try:
            offers += _offers(division)
        except Exception as e:
            print(f"  [SOLID.Jobs] Failed to fetch '{division}': {e}")

    today = date.today().isoformat()
    jobs = []
    for o in offers:
        title = o.get("jobTitle") or ""
        if not title or not profile.matches(title) or profile.excluded(title):
            continue
        if (o.get("experienceLevel") or "").lower() in SKIP_LEVELS:
            continue
        if (o.get("validTo") or "9999")[:10] < today:
            continue
        mode = (o.get("remotePossible") or "").lower()
        city = o.get("companyCity") or ""
        in_region = any(rc in city.lower() for rc in profile.regional_cities)
        if mode in REMOTE:
            location = "Zdalnie"
        elif in_region and (mode in PARTLY or getattr(profile, "office_in_region", True)):
            location = f"{city} ({o.get('remotePossible') or 'tryb nieznany'})"
        elif mode in PARTLY and not in_region and getattr(profile, "hybrid_elsewhere", True):
            location = f"{city} ({o.get('remotePossible')}; poza regionem: sprawdź ile dni w biurze)"
        else:
            continue  # on-site (or unknown) outside the region
        jobs.append({
            "title": title,
            "company": o.get("companyName") or "",
            "salary": _salary(o),
            "source": "SOLID.Jobs",
            "url": f"https://solid.jobs/offer/{o.get('id')}/{o.get('jobOfferUrl')}",
            "found_date": today,
            "location": location,
        })
    # The scanner treats offers with the same title and company as one; when a company posts the same role
    # twice (remote and hybrid), keep the remote one first so it is the one that reaches the sheet (2026-11-19, Connectis).
    jobs.sort(key=lambda j: 0 if j["location"] == "Zdalnie" else 1 if "poza regionem" not in j["location"] else 2)
    return jobs
