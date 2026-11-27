"""Career pages of low-code companies (added 2026-11-10 for the 'low-code' tab).

Only pages whose offer list is in the plain HTML are read here (checked 2026-11-10):
DomData (Ferryt) and Asseco Data Systems. WEBCON, Bosflow, Madkom, Consdata, Nortal and Camunda
load offers with JavaScript or block automated reading: the owner checks those by hand
(links are in the 'low-code' tab).
"""

import html
import re
from datetime import date

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _text(fragment: str) -> list[str]:
    parts = re.split(r"<[^>]+>", fragment)
    return [html.unescape(re.sub(r"\s+", " ", p)).strip() for p in parts if p.strip()]


def _domdata() -> list[dict]:
    t = requests.get("https://domdata.pl/lista-ofert/", headers=HEADERS, timeout=30).text
    jobs = {}
    for m in re.finditer(r'<a[^>]+href="(https://domdata\.pl/lista-ofert/(?!feed)[^"#]+)"[^>]*>(.*?)</a>', t, re.S):
        title = " ".join(_text(m.group(2)))
        if title:
            jobs[m.group(1)] = {"title": title, "company": "DomData", "location": "Poznań / zdalnie (sprawdź w ogłoszeniu)",
                                "url": m.group(1), "source": "Strona kariery DomData"}
    return list(jobs.values())


def _asseco() -> list[dict]:
    t = requests.get("https://kariera.assecods.pl/", headers=HEADERS, timeout=30).text
    jobs = {}
    for m in re.finditer(r'<a href="(/Oferta/[0-9a-f-]{36})" class="job">(.*?)</a>', t, re.S):
        parts = [p for p in _text(m.group(2)) if p.lower() != "aplikuj teraz"]
        if not parts:
            continue
        url = "https://kariera.assecods.pl" + m.group(1)
        # parts: title, area, locations, experience
        jobs[url] = {"title": parts[0], "company": "Asseco Data Systems",
                     "location": parts[2] if len(parts) > 2 else "", "url": url,
                     "source": "Strona kariery Asseco DS", "note": parts[3] if len(parts) > 3 else ""}
    return list(jobs.values())


PAGES = [("DomData", _domdata), ("Asseco Data Systems", _asseco)]


def fetch(profile) -> list[dict]:
    today = date.today().isoformat()
    result = []
    for name, fn in PAGES:
        try:
            jobs = fn()
        except Exception as e:
            print(f"  [{name}] nie udało się odczytać strony kariery: {type(e).__name__}")
            continue
        jobs = [j for j in jobs if not profile.excluded(j["title"])]
        print(f"  [{name}] {len(jobs)} ofert na stronie kariery (po odfiltrowaniu)")
        for j in jobs:
            j.setdefault("salary", "")
            j["found_date"] = today
        result.extend(jobs)
    return result
