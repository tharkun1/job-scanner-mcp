"""Import offers from the owner's own LinkedIn job-alert e-mails into the sheet (2026-11-26).

Why: his LinkedIn alerts (about 45 e-mails and 200+ offers a week, Poland, EU and US) were never scanned; the
good offers reached him only when he read the e-mails himself.

LinkedIn is never fetched here (no scraping, no login): the input is the plain-text part of the alert e-mails
he received (title, company, location, link, and "N kontakty" / "były pracownik" hints). Links in the e-mails
carry a one-time sign-in token (otpToken), so only the bare offer address https://www.linkedin.com/jobs/view/<id>/
is stored. Each offer goes to the tab of the first profile whose title words match, marked "do zweryfikowania";
duplicates (any tab, archive) are skipped. The morning review judges these from title, company and location only.

Input: his Gmail over IMAP (read-only, the same app password as the pracuj.pl import: GMAIL_ADDRESS /
GMAIL_APP_PASSWORD in .env).
Usage:  python -m tools.linkedin_mail_import [--days=3] [--dry-run] [--all]
maintain.py --scan runs it every day (last 3 days, so weekends and missed runs are covered).
"""

import email
import imaplib
import os
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from tools import sheets
from tools.profiles import LOWCODE
from tools.pracuj_mail_import import known_everywhere, pick_profile

SOURCE = "LinkedIn (e-mail): do zweryfikowania"
SENDER = "jobalerts-noreply@linkedin.com"
JOB = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")
HEADER = ("Twój alert", "Your job alert", "Wyświetl", "View job")
# lines under a job card that are hints, not location
HINT = re.compile(r"kontakt|absolwent|pracownik|connection|alumni|employee", re.IGNORECASE)
NOISE_LINE = ("Ta firma prowadzi intensywną rekrutację", "Aplikuj z CV i profilem", "Aktywna rekrutacja",
              "Easy Apply", "Actively recruiting")

# English title words the Polish-oriented profile keywords miss (checked on 218 offers from 19-26.11)
LOOSE_EN = [
    ("Wdrozenia", ("implementation", "implementatie", "onboarding", "deployment specialist", "solutions engineer",
                   "solution engineer", "technical consultant", "services consultant", "application specialist",
                   "functional specialist", "technical support consultant")),
    ("Consulting", ("business analys", "business consultant", "systems analyst", "it analyst", "junior consultant",
                    "associate consultant", "process consultant", "automation specialist", "ai adoption",
                    "copilot")),
    ("Testing", ("tester", "testing", "test analyst", "test engineer", "user acceptance", "uat", "quality assurance",
                 "qa ")),
]
# roles above his level or closed to him by title alone (never silently: counted and listed in the log)
TOO_SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|vp)\b"
                        r"|top secret|clearance|\bts/sci\b", re.IGNORECASE)
US_CITY = re.compile(r",\s*[A-Z]{2}$|,\s*Stany Zjednoczone$")   # "Arlington, VA", "Dystrykt Kolumbii, Stany Zjednoczone"
REGION = ("koszalin", "szczecin", "gdańsk", "gdansk", "gdynia", "sopot", "trójmiasto", "poznań", "poznan")
COUNTRY_LEVEL = ("polska", "poland", "unia europejska", "european union", "europa", "europe", "emea", "zdaln", "remote",
                 "stany zjednoczone", "united states", "niemcy", "hiszpania", "portugalia", "holandia", "irlandia",
                 "dania", "węgry", "bułgaria", "czechy", "rumunia", "litwa", "łotwa", "estonia", "austria", "belgia",
                 "francja", "włochy", "szwecja", "finlandia", "norwegia", "słowacja", "grecja", "chorwacja", "wielka brytania")


def canonical(job_id: str) -> str:
    """Bare offer address: the e-mail links carry a one-time sign-in token that must never be stored."""
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def parse(text: str) -> list[dict]:
    """Job cards in the plain-text part of an alert: title, company, location, optional hint lines, link."""
    offers = []
    text = re.sub(r"\r+\n", "\n", text)   # the e-mails use Windows line ends
    for chunk in re.split(r"\n-{10,}\n", text):
        m = JOB.search(chunk)
        if not m:
            continue
        lines = [ln.strip() for ln in chunk[:m.start()].splitlines() if ln.strip()]
        lines = [ln for ln in lines if not ln.startswith(HEADER) and ln not in NOISE_LINE]
        if len(lines) < 2:
            continue
        hints = [ln for ln in lines[3:] if HINT.search(ln)]
        offers.append({"id": m.group(1), "title": lines[0], "company": lines[1],
                       "location": lines[2] if len(lines) > 2 else "", "hints": hints})
    return offers


def from_gmail(days: int) -> list[dict]:
    """Offers from LinkedIn alert e-mails of the last `days` days. Read-only: nothing is marked as read."""
    addr, pwd = os.environ.get("GMAIL_ADDRESS"), (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    if not addr or not pwd:
        raise RuntimeError("brak GMAIL_ADDRESS / GMAIL_APP_PASSWORD w .env")
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(addr, pwd)
    try:
        boxes = [b.decode() for b in m.list()[1] if rb"\All" in b]
        m.select(boxes[0].split(' "/" ')[-1] if boxes else "INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        ids = m.search(None, f'(FROM "{SENDER}" SINCE {since})')[1][0].split()
        offers = []
        for i in ids:
            msg = email.message_from_bytes(m.fetch(i, "(BODY.PEEK[])")[1][0][1])
            try:
                day = parsedate_to_datetime(msg["Date"]).date().isoformat()
            except Exception:
                day = date.today().isoformat()
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    offers += [dict(o, date=day) for o in parse(body)]
        print(f"Gmail: {len(ids)} alertów LinkedIn z {days} dni, {len(offers)} ofert w treści")
        return offers
    finally:
        m.logout()


def pick(title: str):
    sheet = pick_profile(title)
    if sheet:
        return sheet
    low = f"{title.lower()} "
    for sheet, words in LOOSE_EN:
        if any(w in low for w in words):
            return sheet
    return None


def location_note(loc: str) -> str:
    low = loc.lower()
    if any(r in low for r in REGION):
        return f"{loc} (region; sprawdź tryb pracy)"
    if "warszaw" in low or "warsaw" in low:
        return f"{loc} (sprawdź dni w biurze: limit tydzień w miesiącu)"
    if any(c == low.strip() or low.strip().startswith(c) for c in COUNTRY_LEVEL):
        return f"{loc} (alert LinkedIn: zwykle zdalnie, sprawdź; przy USA sprawdź prawo do pracy)"
    return f"{loc} (poza regionem: sprawdź tryb pracy; zdalnie OK, biuro NIE)"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry_run = "--dry-run" in sys.argv
    days = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--days=")), 3)
    try:
        offers = from_gmail(days)
    except Exception as e:
        reason = "Google odrzuca hasło aplikacji (nowe hasło do aplikacji w .env)" if "AUTHENTICATIONFAILED" in str(e) \
            else f"{type(e).__name__}: {str(e)[:120]}"
        print(f"BŁĄD Gmail: {reason}")
        sys.exit(1)
    offers = list({o["id"]: o for o in reversed(offers)}.values())[::-1]   # same offer in several e-mails

    by_sheet: dict[str, list[dict]] = {}
    no_match, senior, us_onsite = [], [], []
    for o in offers:
        if US_CITY.search(o["location"]) and not re.search(r"remote|wfh|zdaln", o["title"], re.IGNORECASE):
            us_onsite.append(f"{o['title']} ({o['location']})")
            continue
        if TOO_SENIOR.search(o["title"]):
            senior.append(o["title"])
            continue
        sheet = pick(o["title"])
        if not sheet:
            no_match.append(o["title"])
            continue
        source = SOURCE + (f"; {', '.join(o['hints'])} w firmie (możliwe polecenie)" if o["hints"] else "")
        by_sheet.setdefault(sheet, []).append({
            "title": o["title"], "company": o["company"], "salary": "", "source": source,
            "url": canonical(o["id"]), "found_date": o.get("date", date.today().isoformat()),
            "location": location_note(o["location"]),
        })

    seen = known_everywhere()   # read-only, so the dry run shows real duplicates too
    total = 0
    for sheet, jobs in by_sheet.items():
        new = []
        for j in jobs:
            keys = {f"{j['title'].strip().lower()}|{j['company'].strip().lower()}"} | sheets.offer_keys(j["url"], j["title"], j["company"])
            if keys & seen:
                continue
            seen |= keys
            new.append(j)
        for j in new:
            print(f"  [{sheet}] NOWA: {j['title']} | {j['company']} | {j['location']}")
        if new and not dry_run:
            if sheet == LOWCODE.sheet:  # the low-code tab has its own column layout
                from tools import lowcode_watch
                lowcode_watch.add_rows([dict(j, note="") for j in new])
            else:
                sheets.append_jobs(new, sheet)
        total += len(new)
        print(f"{sheet}: {len(new)} dopisanych{' (próba, nic nie zapisano)' if dry_run else ''}")

    print(f"\nLinkedIn: {total} nowych w arkuszu")
    print(f"Pominięte (nie znikają po cichu, lista w logu): na miejscu w USA {len(us_onsite)}, "
          f"seniorskie/kierownicze {len(senior)}, nie pasuje do profili {len(no_match)}")
    for label, items in (("USA na miejscu", us_onsite), ("seniorskie", senior), ("bez profilu", no_match)):
        if items:
            print(f"  {label}: " + "; ".join(items))


if __name__ == "__main__":
    main()
