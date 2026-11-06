"""We Work Remotely — remote-jobs RSS (QA-filtered client-side).

The dedicated QA category feed returns 301 and feedparser doesn't follow it,
so we use the general feed and filter by QA keywords in the title.
"""

import feedparser
from datetime import date

from tools.profiles import QA, Profile

RSS_URL = "https://weworkremotely.com/remote-jobs.rss"

def fetch(profile: Profile = QA) -> list[dict]:
    try:
        feed = feedparser.parse(RSS_URL)
    except Exception as e:
        print(f"  [WeWorkRemotely] Failed: {e}")
        return []

    results = []
    today = date.today().isoformat()
    seen_urls: set[str] = set()

    for entry in feed.entries:
        title = entry.get("title", "")

        if not profile.matches(title):
            continue

        if profile.excluded(title):
            continue

        url = entry.get("link", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # WWR title format: "Company: Job Title"
        company, _, clean_title = title.partition(": ")
        if not clean_title:
            clean_title = title
            company = ""

        results.append({
            "title": clean_title.strip(),
            "company": company.strip(),
            "salary": "",
            "source": "WeWorkRemotely",
            "url": url,
            "found_date": today,
        })

    return results
