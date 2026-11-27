"""RocketJobs.pl (added 2026-11-26 for profiles outside IT; the non-IT sister site of JustJoin.it).

Allowed and polite access only (robots.txt checked 2026-11-26: offer pages /oferta-pracy/... and the sitemaps are
allowed; /api/ and filtered lists /oferty-pracy/*,* are not, so neither is used):
  1. the official sitemap of active offers (about 14,000 URLs, one or two requests) gives every offer address;
     the address carries company, title, city and category without Polish letters;
  2. addresses whose words match the profile and whose city is in the profile region (or say "zdalnie"/"remote")
     are opened one by one (at most MAX_FETCH per run, one per second) and read from the page's own
     schema.org JobPosting data plus the work mode ("office" / "hybrid" / "remote");
  3. what was read is kept in rocketjobs-cache.json, so an offer page is opened once, not on every scan.
Enabled per profile with use_pl_general_boards=True; other profiles get nothing from here.
"""

import json
import os
import re
import time
from datetime import date

import requests

from tools.profiles import Profile, QA

SITEMAP = "https://rocketjobs.pl/sitemaps/active-jobs.xml"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "pl"}
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rocketjobs-cache.json")
MAX_FETCH = 120   # offer pages opened per run; the rest come in the next run
DELAY = 1.0
REMOTE_WORDS = ("zdalnie", "zdalna", "zdalny", "remote")
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _ascii(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower().translate(_PL)).strip()


def _slug_ok(profile: Profile, words: str) -> bool:
    if not any(re.search(r"\b" + re.escape(_ascii(k)) + r"\b", words) for k in profile.keywords if _ascii(k)):
        return False
    if any(_ascii(e) and _ascii(e) in words
           and not any(_ascii(w) in words for w in profile.exclude_lifted_by.get(e, ())) for e in profile.exclude):
        return False
    return any(re.search(r"\b" + re.escape(_ascii(c)) + r"\b", words) for c in profile.regional_cities) or \
        any(w in words.split() for w in REMOTE_WORDS)


def _load_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _read_offer(url: str) -> dict:
    page = requests.get(url, headers=HEADERS, timeout=40)
    if page.status_code != 200:
        return {"gone": True}
    s = page.text
    post = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', s, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            post = d
            break
    if not post:
        return {"gone": True}
    mode = re.search(r'\\?"workplaceType\\?":\{\\?"label\\?":\\?"(\w+)', s)  # the offer's own mode (similar offers use a plain string)
    sal, salary = (post.get("baseSalary") or {}).get("value") or {}, ""
    if sal.get("minValue") or sal.get("maxValue"):
        unit = {"MONTH": "/mies.", "HOUR": "/godz.", "DAY": "/dzień"}.get(sal.get("unitText", ""), "")
        lo, hi = sal.get("minValue"), sal.get("maxValue")
        salary = (f"{int(lo):,}–{int(hi):,}" if lo and hi else f"{int(lo or hi):,}").replace(",", " ") + \
            f" {(post.get('baseSalary') or {}).get('currency', 'PLN')}{unit}"
    addr = ((post.get("jobLocation") or {}).get("address") or {}) if isinstance(post.get("jobLocation"), dict) else {}
    return {"title": post.get("title", ""), "company": (post.get("hiringOrganization") or {}).get("name", ""),
            "city": addr.get("addressLocality", ""), "mode": mode.group(1) if mode else ("remote" if post.get("jobLocationType") == "TELECOMMUTE" else ""),
            "salary": salary, "valid": (post.get("validThrough") or "")[:10]}


def fetch(profile: Profile = QA) -> list[dict]:
    if not getattr(profile, "use_pl_general_boards", False):
        return []
    try:
        index = requests.get(SITEMAP, headers=HEADERS, timeout=60).text
        urls = []
        for part in re.findall(r"<loc>([^<]+)</loc>", index):
            urls += re.findall(r"<loc>([^<]+)</loc>", requests.get(part, headers=HEADERS, timeout=90).text)
    except Exception as e:
        print(f"  [RocketJobs] Failed to read the sitemap: {e}")
        return []
    candidates = [u for u in urls if _slug_ok(profile, _ascii(u.rsplit("/", 1)[-1]))]
    # the offer address ends with the category ("...-szczecin-consulting-it-telekomunikacja"); profiles can keep only
    # some categories (2026-11-26: the owner's profiles got mechanics, drivers and fitness trainers otherwise)
    cats = getattr(profile, "rocket_categories", [])
    if cats:
        candidates = [u for u in candidates if any(f"-{c}" in u.rsplit("/", 1)[-1] for c in cats)]
    cache = _load_cache()
    cache = {u: v for u, v in cache.items() if u in set(urls)}  # offers gone from the sitemap are closed
    todo = [u for u in candidates if u not in cache][:MAX_FETCH]
    print(f"  [RocketJobs] {len(urls)} active offers, {len(candidates)} match the address, opening {len(todo)} new")
    for u in todo:
        try:
            cache[u] = _read_offer(u)
        except Exception as e:
            print(f"  [RocketJobs] {u}: {type(e).__name__}")
        time.sleep(DELAY)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    today = date.today().isoformat()
    jobs = []
    for u in candidates:
        o = cache.get(u) or {}
        title = o.get("title", "")
        if not title or o.get("gone") or not profile.matches(title) or profile.excluded(title):
            continue
        if o.get("valid") and o["valid"] < today:
            continue
        city, mode = o.get("city", ""), o.get("mode", "")
        in_region = any(c in city.lower() for c in profile.regional_cities)
        if mode == "remote":
            location = "Zdalnie"
        elif in_region and (mode == "hybrid" or getattr(profile, "office_in_region", True)):
            location = f"{city} ({'hybrydowo' if mode == 'hybrid' else 'stacjonarnie' if mode == 'office' else 'tryb nieznany'})"
        elif mode == "hybrid" and not in_region and getattr(profile, "hybrid_elsewhere", True):
            location = f"{city} (hybrydowo; poza regionem: sprawdź ile dni w biurze)"
        else:
            continue
        jobs.append({"title": title, "company": o.get("company", ""), "salary": o.get("salary", ""), "source": "RocketJobs",
                     "url": u, "found_date": today, "location": location})
    return jobs
