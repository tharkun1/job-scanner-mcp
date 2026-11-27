"""Import offers from the owner's own pracuj.pl recommendation e-mails into the sheet (2026-11-17).

Pracuj.pl is never fetched here: the input is offers taken from e-mails he received
(title, company, city, salary, link). Each offer goes to the tab of the first profile whose
title keywords match, marked "do zweryfikowania"; duplicates (sheet + archive) are skipped.

Input: his Gmail over IMAP (read-only, app password GMAIL_ADDRESS / GMAIL_APP_PASSWORD in .env),
or a JSON file with a list of {"title", "company", "city", "salary", "url"}.
Usage:  python -m tools.pracuj_mail_import --gmail [--days=5] [--dry-run]
        python -m tools.pracuj_mail_import offers.json [--dry-run]
maintain.py --scan runs it with --gmail (Mon/Thu, last 5 days).
"""

import email
import imaplib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from tools import sheets
from tools.profiles import PROFILES, LOWCODE

SOURCE = "Pracuj.pl (e-mail): do zweryfikowania"
REGION = ("koszalin", "szczecin", "gdańsk", "gdansk", "gdynia", "sopot", "poznań", "poznan", "zdaln")
# order matters: low-code first (top priority), then implementation, consulting, QA, e-gov
ORDER = [LOWCODE] + [p for name in ("Implementation", "Consulting", "QA", "EGov")
                     for p in PROFILES if p.name == name]


def canonical(url: str) -> str:
    """Offer link without e-mail tracking parameters."""
    url = url.split("?")[0].replace("://pracuj.pl", "://www.pracuj.pl")
    return url


# Looser Polish title words, used only here ("z grubsza pasują, do zweryfikowania", the owner 2026-11-17)
LOOSE = [
    ("Wdrozenia", ("wdroże", "wdroze", "wdraża", "konsultant erp", "konsultant/ka erp", "konsultantka erp")),
    ("Consulting", ("procesów biznesowych", "projektowania procesów", "automatyzacji procesów", "automatyzacj",
                    "procesów i systemów", "system analyst", "business - system", "systemów biznesowych",
                    "aplikacji biznesowych", "integracji system", "it analyst", "cyfryzacj")),
    ("Testing", ("tester", "testerka", "testów")),
]
# sales / unrelated roles that the profile keywords (e.g. "opiekun klienta") would otherwise let through
NOISE = ("pentest", "plc", "kosmety", "sprzedaż", "opiekun klienta", "drzwi")
# "analityk" alone also means finance or sales analysts: only IT / business / process analysts count
ANALYST = re.compile(r"anality(k|czk)\w*\W+(\w+\W+)?(biznes|system|proces|it\b|projektant)", re.IGNORECASE)
SKIP_WORDS = ("kosmety", "pentest", "plc", "sap fi", "sap ", "/sap", "senior", "starszy", "kierownik", "lead",
              "finansow", "sprzedaży", "danych")


def pick_profile(title: str):
    low = title.lower()
    if any(w in low for w in NOISE):
        return None
    for p in ORDER:
        if p.matches(title) and not p.excluded(title):
            return p.sheet
    if any(w in low for w in SKIP_WORDS):
        return None
    if ANALYST.search(title):
        return "Consulting"
    for sheet, words in LOOSE:
        if any(w in low for w in words):
            return sheet
    return None


OFFER_ID = re.compile(r",oferta,(\d+)")
COMPANY_TAIL = re.compile(r"\s+(s\.?a\.?|sp\.? z o\.? ?o\.?.*|spółka.*)$", re.IGNORECASE)


def _company(name: str) -> str:
    return COMPANY_TAIL.sub("", name.strip().lower()).strip()


def offer_keys(j: dict) -> set[str]:
    keys = {f"{j['title'].strip().lower()}|{_company(j['company'])}"}
    keys |= {f"pracuj:{m}" for m in OFFER_ID.findall(j["url"])}
    return keys | sheets.offer_keys(j["url"], j["title"], j["company"])


def known_everywhere() -> set[str]:
    """Keys of every offer in every tab (whole rows are searched, so the low-code layout works too)."""
    svc, sid = sheets._get_service()
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    keys: set[str] = set()
    for s in meta["sheets"]:
        tab = s["properties"]["title"]
        rows = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"'{tab}'!A:M").execute().get("values", [])
        for r in rows[1:]:
            line = " ".join(r)
            keys |= {f"pracuj:{m}" for m in OFFER_ID.findall(line)}
            if tab == LOWCODE.sheet and len(r) > 4:      # Firma | ... | Stanowisko
                keys.add(f"{r[4].strip().lower()}|{_company(r[0])}")
            elif len(r) > 1:                              # Stanowisko | Firma | ...
                keys.add(f"{r[0].strip().lower()}|{_company(r[1])}")
            for cell in r:
                if cell.startswith("http"):
                    keys |= sheets.offer_keys(cell, "", "")
    return keys


class _OfferParser(HTMLParser):
    """Offers in a pracuj.pl e-mail: title link (class 'anchor'), salary link ('salary_color'),
    company link ('employer_color'), then a city span ('workplace'); all links carry ',oferta,<id>'."""

    def __init__(self):
        super().__init__()
        self.stack, self.offers, self.last = [], {}, None

    def handle_starttag(self, tag, attrs):
        if tag in ("a", "span"):
            a = dict(attrs)
            self.stack.append([tag, a.get("class") or "", a.get("href") or "", []])

    def handle_endtag(self, tag):
        if tag not in ("a", "span") or not self.stack:
            return
        t, cls, href, parts = self.stack.pop()
        text = " ".join("".join(parts).split())
        if self.stack:
            self.stack[-1][3].append("".join(parts))
        m = OFFER_ID.search(href)
        if t == "a" and m and text:
            o = self.offers.setdefault(m.group(1), {"url": href, "title": "", "company": "", "salary": "", "city": ""})
            self.last = o
            classes = cls.split()
            if "employer_color" in classes:
                o["company"] = text
            elif "salary_color" in classes:
                o["salary"] = text
            elif classes == ["anchor"] and not o["title"]:
                o["title"] = text.lstrip("! ").strip()
        elif t == "span" and "workplace" in cls and self.last is not None and not self.last["city"]:
            self.last["city"] = text

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][3].append(data)


def from_gmail(days: int) -> list[dict]:
    """Offers from pracuj.pl e-mails of the last `days` days (recommendations and saved-search alerts;
    application-status e-mails are skipped). Read-only: nothing is marked as read."""
    addr, pwd = os.environ.get("GMAIL_ADDRESS"), (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    if not addr or not pwd:
        raise RuntimeError("brak GMAIL_ADDRESS / GMAIL_APP_PASSWORD w .env")
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(addr, pwd)
    try:
        boxes = [b.decode() for b in m.list()[1] if rb"\All" in b]
        m.select(boxes[0].split(' "/" ')[-1] if boxes else "INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        ids = m.search(None, f'(FROM "pracuj.pl" SINCE {since})')[1][0].split()
        offers = []
        for i in ids:
            msg = email.message_from_bytes(m.fetch(i, "(BODY.PEEK[])")[1][0][1])
            sender = (msg.get("From") or "").lower()
            if "aplikacje.pracuj.pl" in sender:   # status of his own applications, not new offers
                continue
            try:
                day = parsedate_to_datetime(msg["Date"]).date().isoformat()
            except Exception:
                day = date.today().isoformat()
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    p = _OfferParser()
                    p.feed(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
                    offers += [dict(o, date=day) for o in p.offers.values() if o["title"]]
        print(f"Gmail: {len(ids)} e-maili od pracuj.pl z {days} dni, {len(offers)} ofert w treści")
        return offers
    finally:
        m.logout()


def in_region(city: str) -> bool:
    return any(r in city.lower() for r in REGION)


def location_note(city: str) -> str:
    if in_region(city):
        return city
    # the e-mail gives the company's city, not the work mode (EMSYS "Wrocław" was 100% remote, 2026-11-17)
    return f"{city} (poza regionem: sprawdź tryb pracy; zdalnie lub hybrydowo OK, stacjonarnie NIE)"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    if "--gmail" in sys.argv:
        days = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--days=")), 5)
        try:
            offers = from_gmail(days)
        except Exception as e:  # shown in the dashboard's red box (maintain.write_gmail_status), 2026-11-21
            reason = "Google odrzuca hasło aplikacji (nowe hasło do aplikacji w .env)" if "AUTHENTICATIONFAILED" in str(e) \
                else f"{type(e).__name__}: {str(e)[:120]}"
            print(f"BŁĄD Gmail: {reason}")
            sys.exit(1)
    else:
        offers = json.load(open(args[0], encoding="utf-8"))
    today = date.today().isoformat()
    # the same offer comes in several e-mails: keep the first one
    offers = list({OFFER_ID.search(o["url"]).group(1) if OFFER_ID.search(o["url"]) else o["url"]: o
                   for o in reversed(offers)}.values())[::-1]

    by_sheet: dict[str, list[dict]] = {}
    skipped, far = [], []
    for o in offers:
        sheet = pick_profile(o["title"])
        if not sheet:
            skipped.append(o["title"])
            continue
        # offers outside the home region are kept with a "check the work mode" note: the e-mail shows only the
        # company's city, and the owner wants remote and hybrid ones (2026-11-17); on-site ones he marks NIE
        if not in_region(o.get("city", "")):
            far.append(f"{o['title']} ({o.get('city', '')})")
        by_sheet.setdefault(sheet, []).append({
            "title": o["title"].strip(),
            "company": o.get("company", "").strip(),
            "salary": o.get("salary", ""),
            "source": SOURCE,
            "url": canonical(o["url"]),
            "found_date": o.get("date", today),
            "location": location_note(o.get("city", "")),
        })

    # an offer already anywhere in the sheet (any tab, archive) is skipped: same pracuj.pl offer number,
    # same link, or same title + company
    seen = known_everywhere()   # read-only, so the dry run shows real duplicates too
    for sheet, jobs in by_sheet.items():
        new = []
        for j in jobs:
            keys = offer_keys(j)
            if keys & seen:
                print(f"  [{sheet}] już jest: {j['title']} ({j['company']})")
                continue
            seen |= keys
            new.append(j)
        for j in new:
            print(f"  [{sheet}] NOWA: {j['title']} | {j['company']} | {j['location']} | {j['salary']}")
        if new and not dry_run:
            if sheet == LOWCODE.sheet:  # the low-code tab has its own column layout
                from tools import lowcode_watch
                lowcode_watch.add_rows([dict(j, note=j["salary"]) for j in new])
            else:
                sheets.append_jobs(new, sheet)
        print(f"{sheet}: {len(new)} dopisanych{' (próba, nic nie zapisano)' if dry_run else ''}")

    print(f"\nW tym spoza regionu (z dopiskiem: sprawdź tryb pracy): {len(far)}")
    print(f"Nie pasuje do żadnego profilu: {len(skipped)} ofert" + (": " + "; ".join(skipped) if "--all" in sys.argv else ""))


if __name__ == "__main__":
    main()
