"""Astek Polska career offers (added 2026-11-25, the owner's request: a referral is possible).

astek.pl/kariera and the single offer pages are behind a Cloudflare bot check (HTTP 403 for scripts), which we never
bypass. The site publishes an official sitemap of its job offers for search engines
(https://astek.pl/job_listing-sitemap.xml; robots.txt: "Disallow:" empty, i.e. everything allowed, Crawl-delay 10).
One request to that sitemap gives every offer URL with its last-change date. The title and location are read from the
URL itself (e.g. /job/regular-tester-manualny-bankowosc-warszawa-mazowieckie-polska-k-m/), so the Polish letters are
missing. Descriptions are read by the owner, or by the assistant in his Chrome during a session.
"""

import re
from datetime import date, timedelta

import requests

from tools.profiles import QA, Profile

SITEMAP = "https://astek.pl/job_listing-sitemap.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_AGE_DAYS = 30          # offers changed in the last 30 days; older ones are usually closed
COMPANY = "Astek Polska (możliwe polecenie)"
SOURCE = "Astek (strona kariery, mapa ogłoszeń)"

REGIONS = ("mazowieckie|malopolskie|dolnoslaskie|lodzkie|slaskie|pomorskie|wielkopolskie|zachodniopomorskie|"
           "kujawsko-pomorskie|lubelskie|podkarpackie|podlaskie|swietokrzyskie|warminsko-mazurskie|opolskie|lubuskie")
_CITIES2 = r"bielsko-biala|zielona-gora|gorzow-wielkopolski|nowy-sacz|jelenia-gora"
_LOC_PL = re.compile(rf"-({_CITIES2}|[a-z]+)-({REGIONS})-polska")
_LOC_EN = re.compile(r"-(warsaw|krakow|poznan|wroclaw|lodz|gdansk|szczecin|katowice)-poland")
_REMOTE = re.compile(r"praca-zdalna|full-remote|remote")
_TAIL = re.compile(r"(-(k-m|m-k|f-m|she-he|he-she|\d+))+$")

_cache: list | None = None

# Polish titles without Polish letters, per profile (the scanner's own keywords are English or use Polish letters)
EXTRA = {
    "QA": r"\btester\w*|\btesterk\w*|\bqa\b",
    "Consulting": r"\banalityk\w* (biznesow\w*|systemow\w*|procesow\w*)|\banalityczk\w* (biznesow\w*|systemow\w*)|\bbusiness (system )?analyst",
    "Implementation": r"\bwdrozen\w*|\bwdrozeniow\w*|\bkonsultant\w* (systemu|wdrozen\w*)",
}
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _matches(profile: Profile, title: str) -> bool:
    low = title.lower()
    if any(re.search(r"\b" + re.escape(k.lower().translate(_PL)) + r"\b", low) for k in profile.keywords):
        return True
    extra = EXTRA.get(profile.name)
    return bool(extra and re.search(extra, low))


def _sitemap() -> list[tuple[str, str]]:
    global _cache
    if _cache is None:
        xml = requests.get(SITEMAP, headers=HEADERS, timeout=60).text
        _cache = re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml)
    return _cache


def parse(url: str) -> tuple[str, str]:
    """(title, location) from an offer URL."""
    slug = url.rstrip("/").rsplit("/job/", 1)[-1]
    slug = _TAIL.sub("", slug)
    location = "tryb nieznany: sprawdź w ogłoszeniu"
    m = _LOC_PL.search(slug) or _LOC_EN.search(slug)
    if m:
        city = m.group(1).replace("-", " ").title()
        location = f"{city} (tryb nieznany; poza regionem: sprawdź ile dni w biurze)"
        slug = slug[:m.start()] + slug[m.end():]
    if _REMOTE.search(slug):
        location = "Zdalnie (wg tytułu; sprawdź w ogłoszeniu)"
        slug = re.sub(r"-?(praca-zdalna|full-remote)", "", slug)
    slug = _TAIL.sub("", slug)
    title = slug.replace("-", " ").strip()
    return (title[:1].upper() + title[1:], location)


def fetch(profile: Profile = QA) -> list[dict]:
    try:
        items = _sitemap()
    except Exception as e:
        print(f"  [Astek] Failed to fetch the sitemap: {e}")
        return []
    since = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    today = date.today().isoformat()
    jobs = []
    for url, lastmod in items:
        if lastmod[:10] < since:
            continue
        title, location = parse(url)
        if not title or not _matches(profile, title) or profile.excluded(title):
            continue
        jobs.append({"title": title, "company": COMPANY, "salary": "", "source": SOURCE, "url": url,
                     "found_date": today, "location": location})
    return jobs
