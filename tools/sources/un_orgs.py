"""
WHO, UNICEF, World Bank, OSCE, Council of Europe — HTML page scraping.

These orgs use proprietary ATS systems (Workday, Taleo, SAP SuccessFactors)
with no public RSS or API. We scrape their public job listing pages instead.
Note: more fragile than API-based sources — may need URL updates if sites redesign.
"""

import requests
from datetime import date
from html.parser import HTMLParser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

QA_KEYWORDS = {
    "qa", "quality assurance", "test", "information systems", "ict",
    "information technology", "digital", "systems officer", "software",
    "data analyst", "web", "application", "developer",
}

EXCLUDE_KEYWORDS = {"intern", "driver", "cook", "security", "cleaner", "receptionist", "nurse", "doctor"}


# ─── Source definitions ───────────────────────────────────────────────────────

SOURCES = [
    {
        "name": "UNICEF",
        "source_label": "UNICEF Careers",
        "url": "https://www.unicef.org/careers/search?keywords=information+systems&contract_type=FTA%2CLCA%2CTEMPORARY",
        "link_prefix": "https://www.unicef.org",
        "parser": "unicef",
    },
    {
        "name": "WHO",
        "source_label": "WHO Careers",
        "url": "https://careers.who.int/careersection/ex/jobsearch.ftl?lang=en",
        "link_prefix": "https://careers.who.int",
        "parser": "generic_table",
    },
    {
        "name": "World Bank / IFC",
        "source_label": "World Bank Group",
        "url": "https://jobs.worldbank.org/en/jobs/all-jobs?context=&term=information+systems",
        "link_prefix": "https://jobs.worldbank.org",
        "parser": "worldbank",
    },
    {
        "name": "OSCE",
        "source_label": "OSCE Jobs",
        "url": "https://vacancies.osce.org/",
        "link_prefix": "https://vacancies.osce.org",
        "parser": "osce",
    },
    {
        "name": "Council of Europe",
        "source_label": "Council of Europe",
        "url": "https://www.coe.int/en/web/jobs/vacancies",
        "link_prefix": "https://www.coe.int",
        "parser": "generic_links",
    },
]


def fetch() -> list[dict]:
    results = []
    today = date.today().isoformat()

    for source in SOURCES:
        try:
            jobs = _fetch_source(source, today)
            print(f"    {source['name']}: {len(jobs)} matches")
            results.extend(jobs)
        except Exception as e:
            print(f"    {source['name']}: failed ({e})")

    return results


def _fetch_source(source: dict, today: str) -> list[dict]:
    resp = requests.get(source["url"], headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    parser_name = source["parser"]
    if parser_name == "worldbank":
        raw_jobs = _parse_worldbank(html, source["link_prefix"])
    elif parser_name == "osce":
        raw_jobs = _parse_osce(html, source["link_prefix"])
    else:
        raw_jobs = _parse_generic(html, source["link_prefix"])

    results = []
    for title, url in raw_jobs:
        title_lower = title.lower()
        if not any(kw in title_lower for kw in QA_KEYWORDS):
            continue
        if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
            continue
        results.append({
            "title": title,
            "company": source["source_label"],
            "salary": "",
            "source": "UN/International",
            "url": url,
            "found_date": today,
        })

    return results


# ─── Parsers ──────────────────────────────────────────────────────────────────

class _LinkParser(HTMLParser):
    """Generic parser: collect all anchor text + href pairs."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.jobs: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._capture = False
        self._text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            if href and not href.startswith("#") and not href.startswith("javascript"):
                self._current_href = href if href.startswith("http") else self.base_url + href
                self._capture = True
                self._text = ""

    def handle_endtag(self, tag):
        if tag == "a" and self._capture:
            text = self._text.strip()
            if text and self._current_href and len(text) > 5:
                self.jobs.append((text, self._current_href))
            self._capture = False
            self._current_href = None

    def handle_data(self, data):
        if self._capture:
            self._text += data


def _parse_generic(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = _LinkParser(base_url)
    parser.feed(html)
    # Filter out navigation/footer links (too short or too generic)
    return [(t, u) for t, u in parser.jobs if len(t) > 10 and len(t) < 200]


def _parse_worldbank(html: str, base_url: str) -> list[tuple[str, str]]:
    return _parse_generic(html, base_url)


def _parse_osce(html: str, base_url: str) -> list[tuple[str, str]]:
    return _parse_generic(html, base_url)
