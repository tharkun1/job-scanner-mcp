"""Impactpool source — aggregator of UN, World Bank, EU and NGO jobs and consultancies (added 2026-11-13).

Runs only for profiles that set `use_intl_dev=True` (the E-gov profile). The public search page is
server-rendered, so the job links can be read without logging in. Search is fuzzy, so every result
is filtered by the profile's title keywords.
"""

import re
from datetime import date
from html.parser import HTMLParser

import requests

SEARCH_URL = "https://www.impactpool.org/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
# the link text is "<title> <ORG> - <organisation name> <place> <grade>"; the organisation acronym splits it
ORG_RX = re.compile(r"\s([A-Z]{2,10})\s-\s")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.buf = ""
        self.items = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and re.match(r"^/jobs/\d+$", a.get("href") or ""):
            self.href, self.buf = a["href"], ""

    def handle_data(self, data):
        if self.href:
            self.buf += data

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.items.append((self.href, " ".join(self.buf.split())))
            self.href = None


def fetch(profile) -> list[dict]:
    if not getattr(profile, "use_intl_dev", False):
        return []
    today = date.today().isoformat()
    seen, results = set(), []
    for query in profile.intl_queries:
        try:
            resp = requests.get(SEARCH_URL, params={"q": query}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [Impactpool] '{query}' failed: {type(e).__name__}")
            continue
        parser = _Links()
        parser.feed(resp.text)
        for href, text in parser.items:
            if not text or href in seen:
                continue
            seen.add(href)
            text = re.sub(r"^(New job|Closing tomorrow|Closing today):\s*", "", text).strip()
            m = ORG_RX.search(text)
            title = text[: m.start()].strip() if m else text[:120]
            org = m.group(1) if m else ""
            rest = text[m.end():] if m else ""
            if not profile.matches(title) or profile.excluded(title):
                continue
            results.append({"title": title, "company": org, "salary": "", "source": "Impactpool",
                            "url": "https://www.impactpool.org" + href, "found_date": today,
                            "location": rest[:80]})
    return results
