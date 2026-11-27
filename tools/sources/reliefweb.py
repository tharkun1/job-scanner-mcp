"""ReliefWeb jobs via the public RSS feed (added 2026-11-13).

The ReliefWeb API needs a pre-approved appname; the RSS feed of a search does not. Runs only for
profiles with `use_intl_dev=True` (the E-gov profile); results are filtered by the profile's title keywords.
"""

from datetime import date

import feedparser
import requests

RSS_URL = "https://reliefweb.int/jobs/rss.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 job-scanner"}


def fetch(profile) -> list[dict]:
    if not getattr(profile, "use_intl_dev", False):
        return []
    today = date.today().isoformat()
    seen, results = set(), []
    for query in profile.intl_queries:
        try:
            resp = requests.get(RSS_URL, params={"search": f'"{query}"'}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [ReliefWeb] '{query}' failed: {type(e).__name__}")
            continue
        for e in feedparser.parse(resp.content).entries:
            url, title = e.get("link", ""), (e.get("title") or "").strip()
            if not url or url in seen or not profile.matches(title) or profile.excluded(title):
                continue
            seen.add(url)
            results.append({"title": title, "company": (e.get("author") or "")[:60], "salary": "",
                            "source": "ReliefWeb", "url": url, "found_date": today, "location": ""})
    return results
