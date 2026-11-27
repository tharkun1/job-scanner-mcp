"""Which computer runs the automatic bots (job scanner, low-code watch). Added 2026-11-15.

the owner works on two computers (desktop at home, laptop when away). Both have the same scheduled
tasks, but only ONE may run them, otherwise offers are added twice and popups/e-mails come twice.
The name of the active computer is kept in the Google Sheet (tab 'Sterowanie', cell B1), so both
computers see the same answer even when the other one is switched off.

    python tools/active_machine.py           show which computer is active
    python tools/active_machine.py --take    make THIS computer the active one

The scheduled bots call `allowed_to_run()` first and stop quietly when another computer is active.
If the sheet cannot be read (no internet), the bots also stop: they could not work anyway.
"""

import os
import socket
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TAB = "Sterowanie"


def this_machine() -> str:
    return (os.environ.get("COMPUTERNAME") or socket.gethostname()).upper()


def _service():
    from tools import sheets

    return sheets._get_service()


def _ensure_tab(svc, sid):
    meta = svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties.title").execute()
    if TAB not in [s["properties"]["title"] for s in meta.get("sheets", [])]:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"addSheet": {"properties": {"title": TAB}}}]}).execute()


def get_active() -> tuple[str, str]:
    """(computer name, since when) from the sheet; ('', '') when nothing is set yet."""
    svc, sid = _service()
    _ensure_tab(svc, sid)
    vals = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"'{TAB}'!B1:B2").execute().get("values", [])
    name = vals[0][0].strip().upper() if len(vals) > 0 and vals[0] else ""
    since = vals[1][0] if len(vals) > 1 and vals[1] else ""
    return name, since


def take() -> str:
    svc, sid = _service()
    _ensure_tab(svc, sid)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    body = {"values": [
        ["Aktywny komputer (tylko on uruchamia boty)", this_machine()],
        ["Od kiedy", now],
        ["Jak zmienić", "Na komputerze, który ma przejąć: python tools/active_machine.py --take (albo skrypt przeprowadzki 2_PRZEJMIJ)"],
    ]}
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"'{TAB}'!A1:B3", valueInputOption="RAW", body=body).execute()
    return now


def allowed_to_run(log=print) -> bool:
    """True only when this computer is the active one in the sheet."""
    import time
    for attempt in range(3):  # 2026-11-21: the 19.11 morning scan died on one network hiccup; retry twice, 5 min apart
        try:
            name, since = get_active()
            break
        except Exception as e:  # no internet, bad credentials: the bot could not work anyway
            if attempt == 2:
                log(f"nie da się sprawdzić aktywnego komputera ({type(e).__name__}); przerywam po 3 próbach")
                return False
            log(f"nie da się sprawdzić aktywnego komputera ({type(e).__name__}); ponowna próba za 5 min")
            time.sleep(300)
    if not name:
        log("w arkuszu nie ustawiono aktywnego komputera; przerywam (ustaw: python tools/active_machine.py --take)")
        return False
    if name != this_machine():
        log(f"aktywny jest inny komputer: {name} (od {since}); ten komputer ({this_machine()}) nic nie robi")
        return False
    return True


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.chdir(HERE)  # credentials path in .env is relative to the scanner folder
    from dotenv import load_dotenv

    load_dotenv(os.path.join(HERE, ".env"))
    if "--take" in sys.argv:
        when = take()
        print(f"Ten komputer ({this_machine()}) jest teraz aktywny (od {when}). Boty na drugim komputerze nic nie zrobią.")
    else:
        name, since = get_active()
        me = this_machine()
        if not name:
            print(f"Nie ustawiono aktywnego komputera. Ten komputer: {me}.")
        else:
            print(f"Aktywny komputer: {name} (od {since}). Ten komputer: {me} -> " + ("AKTYWNY" if name == me else "boty wyłączone"))
