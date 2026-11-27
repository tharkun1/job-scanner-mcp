"""CodiLime career offers (added 2026-11-26, the owner's request: a referral is possible).

CodiLime's job board (jobs.codilime.com) runs on Teamtailor, which publishes a public JSON feed of all open offers
with full descriptions: https://jobs.codilime.com/jobs.json (robots.txt allows /jobs; no bot check, tested 2026-11-26).
One request per scan. Offers posted for several countries appear once per country; only the Polish ones are kept.

Most CodiLime roles are network / software engineering. Because a referral raises the chance that someone reads the
CV, the title filter is wider than the profile keywords (any tester, analyst, specialist, consultant, coordinator or
support title); the morning review then judges each one from its description.
"""

import html
import re
from datetime import date

import requests

from tools.profiles import QA, Profile

FEED = "https://jobs.codilime.com/jobs.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
COMPANY = "CodiLime (możliwe polecenie)"
SOURCE = "CodiLime (strona kariery, Teamtailor)"

# Wider title filter per profile (on top of the profile keywords), see the module docstring
_QA_EXTRA = r"\btest\w*|\bqa\b|\bquality\b|\bvalidation\b"
EXTRA = {
    "QA": _QA_EXTRA,
    "Consulting": r"\banalyst\b|\bconsultant\b|\bspecialist\b|\bcoordinator\b|\bcompliance\b|\bsupport\b|\bproject manager\b",
    "Implementation": r"\bimplementation\b|\bonboarding\b|\btrainer\b|\bcustomer success\b",
}

_cache: list | None = None


def _feed() -> list[dict]:
    global _cache
    if _cache is None:
        _cache = requests.get(FEED, headers=HEADERS, timeout=60).json().get("items", [])
    return _cache


def _text(item: dict) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", item.get("content_html", ""))).lower()


def _location(item: dict) -> str | None:
    """Location label for the sheet, or None when the offer is not posted for Poland."""
    jp = item.get("_jobposting") or {}
    places = jp.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    if not any(((p or {}).get("address") or {}).get("addressCountry") == "PL" for p in places):
        return None
    text = _text(item)
    if "travel to denmark" in text or "travels to denmark" in text:
        return "Warszawa / wyjazdy do Danii (sprawdź w ogłoszeniu)"
    if jp.get("jobLocationType") == "TELECOMMUTE" or "fully remote" in text:
        return "Zdalnie (Polska) lub biuro Warszawa"
    return "Warszawa (tryb pracy: sprawdź w ogłoszeniu)"


def _matches(profile: Profile, title: str) -> bool:
    if profile.matches(title):
        return True
    low = title.lower()
    if profile.name != "QA" and re.search(_QA_EXTRA, low):
        return False  # testing titles go to the Testing tab only
    extra = EXTRA.get(profile.name)
    return bool(extra and re.search(extra, low))


def fetch(profile: Profile = QA) -> list[dict]:
    try:
        items = _feed()
    except Exception as e:
        print(f"  [CodiLime] Failed to fetch the job feed: {e}")
        return []
    today = date.today().isoformat()
    jobs, titles = [], set()
    for item in items:
        title = (item.get("title") or "").strip()
        url = item.get("url") or ""
        if not title or not url or title.lower() in titles:
            continue
        location = _location(item)
        if location is None or not _matches(profile, title) or profile.excluded(title):
            continue
        titles.add(title.lower())  # the same offer is often posted twice for Warsaw
        jobs.append({"title": title, "company": COMPANY, "salary": "", "source": SOURCE, "url": url,
                     "found_date": today, "location": location})
    return jobs
