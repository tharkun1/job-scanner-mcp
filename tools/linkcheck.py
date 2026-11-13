"""Live check of job offer links: is the offer still open, can it be opened from Poland, how many
years of experience does it ask for.

check_many(urls) returns {url: {"state", "years", "language", "note", "checked"}} where state is
  ok       page loaded and no "closed" / "not available" signals
  closed   offer removed or expired (404/410, redirect to a "closed job" page, or closed wording)
  region   the page says it is not available in this region
  unknown  could not decide (site blocks bots, needs JavaScript, timeout) — kept, shown with a "?"

Results are cached in dashboard/link-cache.json: closed offers are never re-checked, others are
re-checked after a few hours.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

CACHE = Path(__file__).resolve().parent / "link-cache.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en,pl;q=0.8",
}
RECHECK_SECONDS = 4 * 3600          # open / unknown offers
RECHECK_REGION_SECONDS = 24 * 3600  # region-blocked pages

CLOSED_PHRASES = [
    "no longer available", "no longer accepting", "no longer open", "job has expired", "has expired", "position has been filled",
    "this job is closed", "job is closed", "job posting is closed", "posting has closed", "listing has expired",
    "this position is no longer", "this job posting is no longer", "job not found", "page not found", "offer has expired",
    "oferta wygasła", "oferta jest już nieaktualna", "ogłoszenie wygasło", "nieaktualne",
]
REGION_PHRASES = ["not available in your region", "not available in your country", "niedostępne w Twoim regionie"]
CLOSED_URL_PARTS = ["closedjob", "/expired", "job-expired", "jobclosed"]
LANGUAGES = ["german", "deutsch", "french", "danish", "dutch", "spanish", "italian", "swedish", "norwegian", "finnish", "czech"]


STACK = {"java": r"\bjava\b(?!script)", "selenium": r"\bselenium\b", "csharp": r"c#|\.net\b", "playwright": r"\bplaywright\b"}


# the owner's rule (2026-10-25): an offer that asks for ADVANCED / EXPERT knowledge of one named platform
# (e.g. "practical, advanced knowledge of Shopify") is a barrier, not something to learn in a few weeks.
try:
    from scoring import PLATFORM_SPECIFIC as _PLATFORMS
except ImportError:  # run from another folder
    _PLATFORMS = ["shopify", "salesforce", "servicenow", "workday", "sap", "dynamics", "d365", "veeva"]
# The level word must be followed by a "knowledge / experience / skills" word, so menu text like
# "Advanced Search" or "build advanced reports" near a platform name does not count.
_ADV = r"(?:advanced|expert\w*|zaawansowan\w*|eksperck\w*|biegł\w*|in-depth)"
_KNOW = r"(?:practical\s+|hands-on\s+|deep\s+)?(?:knowledge|experience|skills?|proficiency|understanding|command|expertise|znajomo\w*|doświadczeni\w*|umiejętno\w*)"
_PLAT = r"(" + "|".join(re.escape(p) for p in _PLATFORMS) + r")"
ADVANCED_RX = re.compile(_ADV + r"[,\s]+" + _KNOW + r"[^.\n]{0,40}?\b" + _PLAT + r"\b|\bexpert\s+(?:in|with|at|on)\s+(?:the\s+)?" + _PLAT + r"\b")


# Developer / infrastructure stack named in the posting (3+ of these = a developer job, not implementation work)
DEVSTACK = {"java": r"\bjava\b(?!script)", "python": r"\bpython\b", "csharp": r"c#|\.net\b", "go": r"\bgolang\b", "kotlin": r"\bkotlin\b",
            "ruby": r"\bruby\b", "php": r"\bphp\b", "docker": r"\bdocker\b", "k8s": r"\bkubernetes\b|\bk8s\b", "terraform": r"\bterraform\b",
            "react": r"\breact\b", "angular": r"\bangular\b", "node": r"\bnode\.?js\b", "scala": r"\bscala\b"}

# Region limits that the page states in words: "hiring in AZ, CO, CT", "anywhere in the US or Canada", "applicants must live in the UK"
_PLACES = r"(?:us|u\.s\.|usa|united states|uk|u\.k\.|united kingdom|canada|australia)"
REGION_RX = re.compile(
    r"(?:must|need to|required to)\s+(?:be\s+)?(?:located|reside|live|based)\s+in\s+(?:the\s+)?(?:" + _PLACES + r"|one of the following states)"
    r"|\banywhere in the " + _PLACES + r"\b"
    r"|authori[sz]ed to work in the " + _PLACES + r"\b"
    r"|currently hiring in (?:[a-z]{2},\s*){2,}"
    r"|(?:us|u\.s\.) (?:residents|citizens) only"
    r"|(?:right|eligib\w+) to work in the (?:uk|united kingdom|us|united states)\b")


def _advanced_platform(low: str):
    """Name of a platform the text asks to know at an advanced/expert level, else None."""
    m = ADVANCED_RX.search(low)
    return (m.group(1) or m.group(2)) if m else None


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


def _years(text: str):
    """Highest 'N years' figure that appears in a sentence about experience (None if none)."""
    best = None
    for sentence in re.split(r"(?<=[.!?\n])\s+|\s[-•·]\s", text):
        low = sentence.lower()
        has_years = any(w in low for w in ("year", " lat", "lata", "roku"))
        has_experience = any(w in low for w in ("experience", "exp.", "doświadczen", "staż"))  # English and Polish ads
        if not (has_years and has_experience):
            continue
        for m in re.finditer(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs|year|lat|lata|roku)\b", low):
            n = int(m.group(2) or m.group(1))
            if 1 <= n <= 20:
                best = n if best is None else max(best, n)
    return best


# NoFluffJobs answered 429 (too many requests) on 2026-10-25 after a burst of checks: one request at a time
# per host, with a pause, and stop for the rest of the run after a 429.
_HOST_LOCKS: dict = {}
_HOST_PAUSE = {"nofluffjobs.com": 1.5}
_BLOCKED_HOSTS: set = set()


def _polite_get(url: str):
    import threading
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.")
    lock = _HOST_LOCKS.setdefault(host, threading.Lock())
    with lock:
        if host in _BLOCKED_HOSTS:
            class _R:  # pretend 429 without sending anything
                status_code = 429
                url = ""
                ok = False
                text = ""
            return _R()
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code == 429:
            _BLOCKED_HOSTS.add(host)
        time.sleep(_HOST_PAUSE.get(host, 0.2))
        return r


def _check_one(url: str) -> dict:
    out = {"state": "unknown", "years": None, "language": None, "stack": [], "note": "", "checked": datetime.now().isoformat(timespec="minutes")}
    try:
        r = _polite_get(url)
    except Exception as e:
        out["note"] = type(e).__name__
        return out
    if r.status_code == 429:  # rate limited: say so, and do not cache this result (retried on the next build)
        out.update(note="HTTP 429 (limit zapytań, sprawdzę później)", nocache=True)
        return out
    final = r.url.lower()
    if r.status_code in (404, 410):
        out.update(state="closed", note=f"HTTP {r.status_code}")
        return out
    if any(p in final for p in CLOSED_URL_PARTS):
        out.update(state="closed", note="przekierowanie na stronę zamkniętej oferty")
        return out
    if not r.ok:
        out["note"] = f"HTTP {r.status_code}"
        return out
    text = _strip_html(r.text)
    low = text.lower()
    if any(p.lower() in low for p in REGION_PHRASES):
        out.update(state="region", note="oferta niedostępna w Twoim regionie")
        return out
    if len(low) > 400 and REGION_RX.search(low):
        out.update(state="region", note="oferta tylko dla mieszkańców USA/UK/Kanady (z opisu)", advanced=None, devstack=[])
        return out
    # closed wording only counts when the page is short or the phrase is near the top (avoids matching boilerplate)
    head = low[:1500]
    if any(p in head for p in CLOSED_PHRASES):
        out.update(state="closed", note="strona mówi, że oferta wygasła")
        return out
    if len(low) > 400:
        out["state"] = "ok"
        out["years"] = _years(text)
        out["stack"] = [name for name, rx in STACK.items() if re.search(rx, low)]
        out["advanced"] = _advanced_platform(low)
        out["devstack"] = [k for k, rx in DEVSTACK.items() if re.search(rx, low)]
        out["language"] = next((l for l in LANGUAGES if re.search(rf"\b{l}\b", low) and re.search(rf"{l}[^.]{{0,40}}(speak|fluen|proficien|native|language)|(fluent|proficien|native)[^.]{{0,25}}{l}", low)), None)
    else:
        out["note"] = "za mało tekstu (strona wymaga JavaScriptu lub blokuje boty)"
    return out


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fresh(entry: dict) -> bool:
    if entry.get("state") == "closed":
        return True
    if entry.get("state") == "ok" and ("stack" not in entry or "advanced" not in entry or "devstack" not in entry):
        return False  # cached before the stack / advanced-platform checks existed
    try:
        age = time.time() - datetime.fromisoformat(entry["checked"]).timestamp()
    except (KeyError, ValueError):
        return False
    return age < (RECHECK_REGION_SECONDS if entry.get("state") == "region" else RECHECK_SECONDS)


def check_many(urls: list[str], workers: int = 8) -> dict:
    cache = load_cache()
    todo = [u for u in dict.fromkeys(urls) if not (u in cache and _fresh(cache[u]))]
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for url, res in zip(todo, ex.map(_check_one, todo)):
                if res.pop("nocache", False):
                    continue  # rate limited: keep whatever is cached (or nothing) and retry on the next build
                cache[url] = res
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return {u: cache[u] for u in urls if u in cache}
