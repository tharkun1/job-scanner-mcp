"""Daily low-code watch (added 2026-11-10): new low-code / no-code offers go to the 'low-code' tab and
the owner is notified at once (dashboard red box, Windows popup, e-mail).

Usage:
    python tools/lowcode_watch.py              search, add new offers to the tab, notify, rebuild the dashboard
    python tools/lowcode_watch.py --dry-run    search and print only (no sheet, no notification)
    python tools/lowcode_watch.py --test-notify   send a test popup and test e-mail, nothing else

Runs every morning from the scheduled task 'LowCodeCodziennie'. Log: lowcode.log.
E-mail needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (Google "app password"); without them it is skipped.
"""

import json
import os
import smtplib
import subprocess
import sys
from datetime import date, datetime
from email.message import EmailMessage
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
os.chdir(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, ".env"))
from tools import sheets  # noqa: E402
from tools.profiles import LOWCODE, LOWCODE_COMPANIES  # noqa: E402
from tools.sources import adzuna, astek, career_pages, jsearch, nofluffjobs, remoteok, remotive, solidjobs, weworkremotely  # noqa: E402

TAB = "low-code"
LOG = os.path.join(HERE, "lowcode.log")
DASHBOARD = "http://127.0.0.1:8765/"
OTHER_TABS = ("Consulting", "Wdrozenia", "Testing", "Archiwum")


def log(msg: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        print(line)
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def platform_of(job: dict) -> str:
    """Which low-code word or company made the offer qualify (shown in column B)."""
    for p, word in zip(LOWCODE.patterns, LOWCODE.keywords):
        if p.search(job.get("title", "")):
            return word
    company = job.get("company", "").lower()
    for c in LOWCODE_COMPANIES:
        if c in company:
            return f"firma: {c}"
    return ""


def qualifies(job: dict) -> bool:
    return bool(platform_of(job)) and not LOWCODE.excluded(job.get("title", ""))


class AnyTitle:
    """LOWCODE profile that lets every title through, so offers can also be picked by company name."""

    def __getattr__(self, name):
        return getattr(LOWCODE, name)

    def matches(self, title):
        return True


def collect() -> list[dict]:
    sources = [
        ("Strony kariery", lambda: career_pages.fetch(LOWCODE), False),  # whole career page of a low-code company
        ("NoFluffJobs", lambda: nofluffjobs.fetch(AnyTitle()), True),
        ("SOLID.Jobs", lambda: solidjobs.fetch(AnyTitle()), True),  # added 2026-11-18
        ("Astek", lambda: astek.fetch(LOWCODE), False),  # added 2026-11-25; already filtered by LOWCODE titles
        ("Adzuna", lambda: adzuna.fetch(LOWCODE), True),
        ("LinkedIn/Indeed (JSearch)", lambda: jsearch.fetch(LOWCODE), True),
        ("RemoteOK", lambda: remoteok.fetch(LOWCODE), True),
        ("Remotive", lambda: remotive.fetch(LOWCODE), True),
        ("WeWorkRemotely", lambda: weworkremotely.fetch(LOWCODE), True),
    ]
    # JSearch (200 requests/month) only on Mondays and Wednesdays (the owner, 2026-11-12); the other sources run daily
    if date.today().weekday() not in (0, 2):
        sources = [s for s in sources if "JSearch" not in s[0]]
        log("JSearch pominięty (tylko poniedziałek i środa)")
    found = []
    for name, fn, need_match in sources:
        try:
            jobs = fn()
        except Exception as e:
            log(f"{name}: błąd {type(e).__name__}")
            continue
        if need_match:
            jobs = [j for j in jobs if qualifies(j)]
        log(f"{name}: {len(jobs)} ofert low-code")
        found.extend(jobs)
    return found


def known_keys() -> set[str]:
    keys = set()
    for tab in OTHER_TABS:
        try:
            keys |= sheets.get_existing_urls(tab, url_only=(tab == sheets.ARCHIVE_SHEET))
        except Exception as e:
            log(f"{tab}: nie udało się odczytać ({type(e).__name__})")
    svc, sid = sheets._get_service()
    rows = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"'{TAB}'!A2:F").execute().get("values", [])
    for r in rows:
        r = r + [""] * (6 - len(r))
        if r[5]:
            keys |= sheets.offer_keys(r[5], r[4], r[0])
    return keys


def add_rows(jobs: list[dict]):
    svc, sid = sheets._get_service()
    head = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"'{TAB}'!M1").execute().get("values")
    if not head:
        svc.spreadsheets().values().update(spreadsheetId=sid, range=f"'{TAB}'!M1", valueInputOption="RAW",
                                           body={"values": [["Źródło"]]}).execute()
    rows = [[j.get("company", ""), platform_of(j) or "strona kariery", "", "", j.get("title", ""), j.get("url", ""), "",
             j.get("location", ""), "", j.get("note", "") or j.get("salary", ""), "", date.today().isoformat(),
             j.get("source", "")] for j in jobs]
    svc.spreadsheets().values().append(spreadsheetId=sid, range=f"'{TAB}'!A1", valueInputOption="RAW",
                                       insertDataOption="INSERT_ROWS", body={"values": rows}).execute()


def popup(title: str, text: str):
    """Windows notification in the corner of the screen; a click opens the dashboard."""
    xml = (f'<toast activationType="protocol" launch="{DASHBOARD}"><visual><binding template="ToastGeneric">'
           f"<text>{escape(title)}</text><text>{escape(text)}</text></binding></visual></toast>")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml($env:TOAST_XML);"
        "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=dict(os.environ, TOAST_XML=xml),
                           capture_output=True, text=True, timeout=60, creationflags=0x08000000 if os.name == "nt" else 0)
        log("okienko Windows: " + ("wysłane" if r.returncode == 0 else f"błąd {r.stderr.strip()[:200]}"))
    except Exception as e:
        log(f"okienko Windows: błąd {type(e).__name__}")


def email(subject: str, body: str):
    addr, pwd = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not pwd:
        log("e-mail pominięty: brak GMAIL_ADDRESS / GMAIL_APP_PASSWORD w .env")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = addr, os.environ.get("NOTIFY_EMAIL", addr), subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(addr, pwd.replace(" ", ""))
            s.send_message(msg)
        log("e-mail: wysłany")
    except Exception as e:
        log(f"e-mail: błąd {type(e).__name__}")  # never log the password or the message details of the error


def notify(jobs: list[dict]):
    n = len(jobs)
    head = f"Nowe ogłoszenia low-code: {n}"
    popup(head, "; ".join(f"{j['title']} ({j['company']})" for j in jobs[:3]) + (" ..." if n > 3 else ""))
    lines = [f"- {j['title']} | {j['company']} | {j.get('location', '')}\n  {j['url']}" for j in jobs]
    email(head, "Nowe ogłoszenia w zakładce low-code arkusza ofert:\n\n" + "\n".join(lines) +
          f"\n\nDashboard: {DASHBOARD}\nWpisz w arkuszu status (TAK / NIE), a ogłoszenie zniknie z czerwonej ramki.")


def rebuild_dashboard():
    python = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([python, os.path.join(ROOT, "dashboard", "build.py")], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                       creationflags=0x08000000 if os.name == "nt" else 0)
    log(f"dashboard przebudowany (kod {r.returncode})")


def main():
    args = sys.argv[1:]
    if "--test-notify" in args:
        notify([{"title": "To jest test powiadomienia", "company": "Asystent", "url": DASHBOARD, "location": "-"}])
        return
    dry = "--dry-run" in args
    # two computers (2026-11-15): only the one named in the sheet runs the daily watch; --force skips the check
    from tools.active_machine import allowed_to_run
    if not dry and "--force" not in args and not allowed_to_run(log):
        return
    log("=== start" + (" (próba na sucho)" if dry else ""))
    jobs = collect()
    keys = known_keys()
    new = []
    for j in jobs:
        k = sheets.offer_keys(j.get("url", ""), j.get("title", ""), j.get("company", ""))
        if j.get("url") and not (k & keys):
            new.append(j)
            keys |= k
    log(f"nowe: {len(new)}")
    for j in new:
        log(f"  {j['title']} | {j['company']} | {j['url']}")
    status = {"finished": datetime.now().strftime("%d.%m.%Y %H:%M"), "new": len(new)}
    if not dry:
        if new:
            add_rows(new)
            notify(new)
        with open(os.path.join(ROOT, "dashboard", "lowcode-status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False)
        rebuild_dashboard()


if __name__ == "__main__":
    main()
