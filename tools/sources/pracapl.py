"""Praca.pl (added 2026-11-26 for profiles outside IT). Not to be confused with pracuj.pl, which blocks scripts.

Allowed access only (robots.txt checked 2026-11-26: search result pages are allowed; /api/, /apply/, /kandydat/ and
the like are not, and are not used). The search result pages are plain HTML: title, company, place and tags
(work mode "Stacjonarna" / "Hybrydowa" / "Zdalna", contract, salary). One page per search phrase and city
(profile.regional_queries x profile.regional_where), plus the second page, one request per second.
Enabled per profile with use_pl_general_boards=True; other profiles get nothing from here.
"""

import html
import re
import time
from datetime import date

import requests

from tools.profiles import Profile, QA

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "pl"}
DELAY = 1.0
PAGES = 2
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _slug(text: str, sep: str) -> str:
    return sep.join(re.findall(r"[a-z0-9]+", text.lower().translate(_PL)))


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _page(url: str) -> list[dict]:
    r = requests.get(url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        return []
    out = []
    for item in re.split(r'<li class="listing-v2__item', r.text)[1:]:
        a = re.search(r'class="listing-v2__title" href="([^"#]+)[^"]*" title="([^"]+)"', item)
        if not a:
            continue
        comp = re.search(r'class="listing-v2__employer"[^>]*>(.*?)</', item, re.S)
        loc = re.search(r'class="listing-v2__location"[^>]*>(.*?)</(?:span|div)', item, re.S)
        tags = [html.unescape(t).strip() for t in re.findall(r'class="listing-v2__tag-text"[^>]*>([^<]+)<', item)]
        out.append({"title": html.unescape(a.group(2)).strip(), "url": a.group(1), "company": _clean(comp.group(1)) if comp else "",
                    "place": _clean(loc.group(1)) if loc else "", "tags": tags})
    return out


def fetch(profile: Profile = QA) -> list[dict]:
    if not getattr(profile, "use_pl_general_boards", False):
        return []
    found: dict[str, dict] = {}
    for q in profile.regional_queries:
        for city in profile.regional_where:
            for n in range(1, PAGES + 1):
                url = f"https://www.praca.pl/s-{_slug(q, ',')}_m-{_slug(city, '-')}{'' if n == 1 else f'_{n}'}.html"
                try:
                    items = _page(url)
                except Exception as e:
                    print(f"  [Praca.pl] {url}: {type(e).__name__}")
                    items = []
                time.sleep(DELAY)
                for o in items:
                    found.setdefault(o["url"], o)
                if len(items) < 20:  # no next page
                    break
    today = date.today().isoformat()
    jobs = []
    for o in found.values():
        title = o["title"]
        if not profile.matches(title) or profile.excluded(title):
            continue
        tags = " / ".join(o["tags"]).lower()
        remote, hybrid, office = "zdalna" in tags, "hybrydowa" in tags, "stacjonarna" in tags or "mobilna" in tags
        place = o["place"] if not o["place"].startswith("Oferta pojawiła") else ""
        in_region = any(c in place.lower() for c in profile.regional_cities)
        if remote:
            location = "Zdalnie" + (f" ({place})" if place else "")
        elif in_region and (hybrid or getattr(profile, "office_in_region", True)):
            location = f"{place} ({'hybrydowo' if hybrid else 'stacjonarnie' if office else 'tryb nieznany'})"
        elif hybrid and not in_region and getattr(profile, "hybrid_elsewhere", True):
            location = f"{place} (hybrydowo; poza regionem: sprawdź ile dni w biurze)"
        else:
            continue
        salary = next((t for t in o["tags"] if "zł" in t), "")
        jobs.append({"title": title, "company": o["company"], "salary": salary, "source": "Praca.pl", "url": o["url"],
                     "found_date": today, "location": location})
    return jobs
