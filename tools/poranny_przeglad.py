"""Automatic morning offer review (the owner 2026-11-24).

After the 8:00 scan and the 8:10 low-code watch, Claude Code (headless, `claude -p`) assesses the new offers
by the owner's rules and the result shows up as the "Poranny przegląd" box at the top of the dashboard Kalendarz tab,
plus a Windows popup and an e-mail. It never changes the sheet, never applies, never changes the plan.

Usage:
    python tools/poranny_przeglad.py            wait for today's scan, pick offers, run Claude, rebuild dashboard, notify
    python tools/poranny_przeglad.py --dry-run  pick offers and write the input file only (no Claude, no notification)
    python tools/poranny_przeglad.py --force    skip the active-computer check and the waiting

Scheduled task 'PorannyPrzeglad' (daily 08:15). Log: przeglad.log. Prompt: tools/poranny_przeglad_prompt.md.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scanner folder
ROOT = os.path.dirname(HERE)  # project root
DASH = os.path.join(ROOT, "dashboard")
WORK = os.path.join(DASH, "_przeglad")
IN_FILE, OUT_FILE = os.path.join(WORK, "wejscie.json"), os.path.join(WORK, "wynik.json")
RESULT = os.path.join(DASH, "poranny-przeglad.json")      # shown by the dashboard
HISTORY = os.path.join(WORK, "przejrzane.json")           # URLs already reviewed, so each offer is assessed once
LOG = os.path.join(HERE, "przeglad.log")
PROMPT = os.path.join(HERE, "tools", "poranny_przeglad_prompt.md")
MAX_OFFERS = 35        # keeps one run to the size of a normal assessment conversation (25 until 2026-11-26)
MAX_ASTEK = 8          # Astek offers per run (2026-11-25)
MAX_LINKEDIN = 12      # LinkedIn alert offers per run (2026-11-26): no description, so they must not crowd out the rest
REFERRAL = ("astek.pl/", "jobs.codilime.com/")  # a referral is possible
MAX_TEXT = 6000
FIRST_RUN_DAYS = 3     # with no history yet, only offers found in the last 3 days
os.chdir(HERE)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, ".env"))


def log(msg: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        print(line)
    except Exception:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)


def _finished_today(path: str) -> bool:
    return _read_json(path, {}).get("finished", "").startswith(date.today().strftime("%d.%m.%Y"))


def wait_for_bots(max_minutes=90):
    """The scan (8:00) and the low-code watch (8:10) must finish first; after 90 min go on anyway."""
    for _ in range(max_minutes // 2):
        if _finished_today(os.path.join(DASH, "scan-status.json")) and _finished_today(os.path.join(DASH, "lowcode-status.json")):
            return True
        time.sleep(120)
    log("skan albo low-code nie skończył się dziś w 90 min; przeglądam to, co jest")
    return False


def load_dashboard_offers() -> dict:
    sys.path.insert(0, DASH)
    import build  # dashboard/build.py: the same offers (and the same automatic filters) as the dashboard

    return build.load_offers()


def carry_over(data: dict) -> list[dict]:
    """TAK / MOZE / SPRAWDZ offers from earlier reviews that are still undecided (2026-11-25, the owner: no offer may
    vanish without a decision). Decided = Status in the sheet, a click in the dashboard (state.offers), or gone from
    the low-code box. Expired offers drop out."""
    prev = _read_json(RESULT, {})
    old = [dict(o, since=o.get("since") or prev.get("date", "")) for o in (prev.get("items") or []) + (prev.get("carried") or [])
           if o.get("verdict") in ("TAK", "MOZE", "SPRAWDZ")]
    if not old:
        return []
    decided = set(data.get("decided", [])) | set(_read_json(os.path.join(DASH, "state.json"), {}).get("offers", {}))
    low_open = {o["url"] for o in data.get("lowcode", []) + data.get("lowcode_no", [])}
    keep, urls = [], set()
    for o in old:
        if o["url"] in urls or o["url"] in decided or (o.get("tab") == "low-code" and o["url"] not in low_open):
            continue
        urls.add(o["url"])
        keep.append(o)
    try:
        sys.path.insert(0, DASH)
        import linkcheck
        checks = linkcheck.check_many([o["url"] for o in keep])
        keep = [o for o in keep if checks.get(o["url"], {}).get("state") != "closed"]
    except Exception as e:  # no network: keep them, better one too many than a lost offer
        log(f"sprawdzanie zaległych ofert: {type(e).__name__}")
    return keep


def pick_offers(data: dict) -> list[dict]:
    seen = set(_read_json(HISTORY, {}).get("urls", []))
    since = (date.today() - timedelta(days=FIRST_RUN_DAYS)).isoformat() if not seen else ""
    picked = [dict(o, tab="low-code") for o in data.get("lowcode", []) if o["url"] not in seen]
    tabs = {"consulting": "Consulting", "impl": "Wdrozenia", "qa": "Testing", "egov": "E-gov"}
    rest = []
    for key, tab in tabs.items():
        for o in data.get(key, []):
            if o.get("kind") or o["url"] in seen or (since and o.get("found", "") < since):
                continue
            rest.append(dict(o, tab=tab))
    rest.sort(key=lambda o: -o.get("score", 0))
    # possible referral (right after low-code): Astek (2026-11-25), CodiLime (2026-11-26); capped so they never crowd out the rest
    astek = [o for o in rest if any(d in o["url"] for d in REFERRAL)][:MAX_ASTEK]
    # Round robin over the tabs (2026-11-26): ranking by score alone filled the review with testers (3 points)
    # and no implementation offer (2 points) was ever reviewed.
    queues = [[o for o in rest if o["tab"] == t and not any(d in o["url"] for d in REFERRAL)] for t in tabs.values()]
    mixed = []
    while any(queues):
        for q in queues:
            if q:
                mixed.append(q.pop(0))
    rest = astek + mixed
    urls, out, linkedin = set(), [], 0
    for o in picked + rest:
        if o["url"] in urls:
            continue
        if "linkedin.com/" in o["url"]:
            if linkedin >= MAX_LINKEDIN:
                continue  # stays in the dashboard and comes up in a later run (not in the history yet)
            linkedin += 1
        urls.add(o["url"])
        out.append(o)
    return out[:MAX_OFFERS]


def with_descriptions(offers: list[dict]) -> list[dict]:
    from tools.job_details import fetch_details

    out = []
    for i, o in enumerate(offers, 1):
        url = o["url"]
        if "pracuj.pl" in url:  # never fetched automatically (the owner's rule): he opens the link himself
            d = {"text": "", "note": "pracuj.pl: opisu nie pobieramy automatycznie"}
        elif "linkedin.com/" in url:  # never fetched automatically (2026-11-26): offers come from his alert e-mails
            d = {"text": "", "note": "LinkedIn (z alertu e-mail): opisu nie pobieramy automatycznie; oceń z tytułu, firmy i miejsca"}
        elif "astek.pl" in url:  # behind a Cloudflare bot check (2026-11-25): read in the owner's Chrome during a session
            d = {"text": "", "note": "Astek: strona za blokadą Cloudflare, opis do przeczytania w Chrome; możliwe polecenie"}
        else:
            try:
                d = fetch_details(url)
            except Exception as e:
                d = {"text": "", "note": f"błąd pobierania ({type(e).__name__})"}
        out.append({"id": str(i), "tab": o["tab"], "row": o.get("row"), "title": o.get("title", ""), "company": o.get("company", ""),
                    "location": o.get("location", ""), "salary": o.get("salary", ""), "source": o.get("source", o.get("platform", "")),
                    "url": url, "text": (d.get("text") or "")[:MAX_TEXT], "note": "" if d.get("ok") else d.get("note", "")})
    return out


def find_claude() -> str:
    for c in (shutil.which("claude.cmd"), shutil.which("claude"),
              os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")):
        if c and os.path.exists(c):
            return c
    return ""


def run_claude(n: int) -> dict:
    exe = find_claude()
    if not exe:
        raise RuntimeError("nie znaleziono programu claude (Claude Code CLI)")
    if os.path.exists(OUT_FILE):
        os.remove(OUT_FILE)
    prompt = open(PROMPT, encoding="utf-8").read()
    memory = os.path.join(os.path.expanduser("~"), ".claude", "projects", "d--AI-AI-ASSISTANT", "memory")
    cmd = [exe, "-p", "--allowedTools", "Read,Glob,Grep,Write", "--add-dir", memory, "--output-format", "text"]
    t0 = time.time()
    r = subprocess.run(cmd, input=prompt, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=45 * 60, creationflags=0x08000000 if os.name == "nt" else 0)
    log(f"claude: kod {r.returncode}, {int(time.time() - t0)} s")
    if r.returncode != 0:
        log("claude stderr: " + (r.stderr or "").strip()[:300])
    res = _read_json(OUT_FILE, None)
    if not isinstance(res, dict) or not isinstance(res.get("items"), list):
        raise RuntimeError("Claude nie zapisał poprawnego pliku wynik.json")
    return res


def notify(review: dict):
    from tools import lowcode_watch
    from tools.lowcode_watch import email, popup

    lowcode_watch.LOG = LOG  # popup/e-mail results go to przeglad.log, not lowcode.log
    items = review["items"]
    carried = review.get("carried") or []
    good = [o for o in items if o.get("verdict") in ("TAK", "MOZE")]
    head = (f"Poranny przegląd: {sum(o.get('verdict') == 'TAK' for o in items)} TAK, {sum(o.get('verdict') == 'MOZE' for o in items)} MOŻE, {len(items)} ocenionych"
            + (f"; {len(carried)} czeka z poprzednich dni" if carried else ""))
    popup(head, review.get("summary", "")[:200] or "Szczegóły w dashboardzie.")
    order = {"TAK": 0, "MOZE": 1, "SPRAWDZ": 2, "NIE": 3}
    lines = []
    for o in sorted(items, key=lambda o: (order.get(o.get("verdict"), 9), -(o.get("score") or 0))):
        lines.append(f"[{o.get('verdict')} {o.get('score', '')}/10] {o['title']} | {o['company']} | {o.get('mode', '')}\n"
                     f"  {o.get('why', '')}\n" + (f"  Braki: {'; '.join(o.get('gaps') or [])}\n" if o.get("gaps") else "") + f"  {o['url']}")
    if carried:
        lines.append("Z poprzednich dni, jeszcze bez decyzji:\n" + "\n".join(
            f"- [{o.get('verdict')}] {o['title']} | {o['company']} (z {o.get('since', '')})\n  {o['url']}" for o in carried))
    body = (review.get("summary", "") + "\n\n" + "\n\n".join(lines) +
            ("\n\nPropozycje nauki (poniedziałek):\n" + "\n".join(f"- {s['skill']} ({s.get('track', '')}, {s.get('pct', '')}% ofert): {s.get('why', '')}" for s in review.get("nauka", [])) if review.get("nauka") else "") +
            "\n\nDashboard: http://127.0.0.1:8765/\nNapisz asystentowi, które oferty bierzemy (np. 'aplikujemy 1 i 3').")
    if good or review.get("nauka"):
        email(head, body)
    else:
        log("e-mail pominięty: nic na TAK/MOŻE")


def rebuild_dashboard():
    from tools.lowcode_watch import rebuild_dashboard as rb
    rb()


def main():
    args = sys.argv[1:]
    dry, force = "--dry-run" in args, "--force" in args
    if not dry and not force:
        from tools.active_machine import allowed_to_run
        if not allowed_to_run(log):
            return
        wait_for_bots()
    log("=== start" + (" (próba na sucho)" if dry else ""))
    data = load_dashboard_offers()
    carried = carry_over(data)
    offers = with_descriptions(pick_offers(data))
    log(f"ofert do oceny: {len(offers)} (z opisem: {sum(bool(o['text']) for o in offers)}); zaległych z poprzednich dni: {len(carried)}")
    today = date.today()
    _write_json(IN_FILE, {"today": today.isoformat(), "monday": today.weekday() == 0, "offers": offers})
    if dry:
        for o in offers:
            log(f"  [{o['tab']}] {o['title']} | {o['company']} | opis: {'tak' if o['text'] else o['note']}")
        for o in carried:
            log(f"  zaległa z {o['since']}: [{o['verdict']}] {o['title']} | {o['company']}")
        return
    status = {"finished": datetime.now().strftime("%d.%m.%Y %H:%M"), "date": today.isoformat(), "ok": True, "items": [], "nauka": [], "summary": "",
              "carried": carried}
    if not offers and today.weekday() != 0:
        status["summary"] = "Brak nowych ofert do oceny."
    else:
        try:
            review = run_claude(len(offers))
            by_id = {str(o.get("id")): o for o in review["items"]}
            merged = []
            for o in offers:
                a = by_id.get(o["id"], {"verdict": "SPRAWDZ", "why": "Claude nie ocenił tej oferty.", "score": None})
                merged.append({k: o[k] for k in ("tab", "row", "title", "company", "location", "salary", "url")} |
                              {k: a.get(k) for k in ("verdict", "score", "why", "gaps", "mode")})
            status.update(items=merged, nauka=review.get("nauka") or [], summary=review.get("summary", ""))
            hist = _read_json(HISTORY, {"urls": []})
            hist["urls"] = sorted(set(hist["urls"]) | {o["url"] for o in offers})
            _write_json(HISTORY, hist)
            notify(status)
        except Exception as e:
            log(f"błąd: {e}")
            status.update(ok=False, summary=f"Przegląd się nie udał: {e}. Napisz asystentowi: poranny przegląd nie działa.")
    _write_json(RESULT, status)
    rebuild_dashboard()
    log("=== koniec")


if __name__ == "__main__":
    main()
