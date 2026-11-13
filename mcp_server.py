"""Job Scanner MCP server — lets Claude read and manage the job offers sheet.

Tools:
  ping            — health check
  list_new_jobs   — read offers from a sheet tab (read-only)
  get_job_details — fetch the full description of one offer from its link (read-only)
  mark_job        — set an offer's status and (optionally) a note about the company and role
  save_assessment — save a fit assessment (have / learnable quickly / barrier) next to an offer
  scan_jobs       — run the scanner for one search profile and add new offers to the sheet
  check_offers    — check live which offers are still open; optionally move closed ones to the archive
"""

import os
import sys

# The server is started from whatever folder the editor is in; anchor everything
# (relative paths in .env, imports) to this file's folder instead.
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, ".env"))

from fastmcp import FastMCP  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
from datetime import date  # noqa: E402

from tools import sheets  # noqa: E402
from tools.fetch_jobs import run_profile  # noqa: E402
from tools.job_details import fetch_details  # noqa: E402
from tools.profiles import PROFILES  # noqa: E402

# The live link check is shared with the dashboard (dashboard/linkcheck.py, one folder up) when it exists;
# the public repository ships its own copy in tools/linkcheck.py.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "dashboard"))
try:
    from linkcheck import check_many  # noqa: E402
except ImportError:
    from tools.linkcheck import check_many  # noqa: E402

mcp = FastMCP(
    "job-scanner",
    instructions=(
        "Tools for the job offers scanner and its Google Sheet. "
        "Sheet tabs: 'Consulting' (business analyst / AI-automation roles), 'Wdrozenia' (software "
        "implementation roles), 'Testing' (QA/testing) and 'low-code' (low-code platform offers). "
        "Write tools (mark_job, save_assessment, scan_jobs) change the shared sheet: confirm the "
        "row with the user first and report what was written."
    ),
)


def _check_row(sheet: str, row: int, expected_title: str) -> tuple[dict | None, str]:
    """Read the row and make sure it is the offer the caller means (rows move when old offers are archived)."""
    if row < 2:
        return None, "Row 1 is the header; offers start at row 2."
    offer = sheets.read_offer(sheet, row)
    if not offer["title"] and not offer["company"]:
        return None, f"Row {row} in sheet '{sheet}' is empty."
    if expected_title and expected_title.strip().lower() not in offer["title"].lower():
        return None, (f"Row {row} is '{offer['title']}' ({offer['company']}), not '{expected_title}'. "
                      "Rows may have moved; list the offers again.")
    return offer, ""


@mcp.tool()
def ping() -> str:
    """Check that the job-scanner server is alive. Returns 'pong'."""
    return "pong"


@mcp.tool()
def list_new_jobs(
    sheet: str = "Consulting",
    only_without_status: bool = True,
    limit: int = 20,
) -> dict:
    """List job offers from the scanner's Google Sheet. Read-only.

    Args:
        sheet: Sheet tab to read: 'Consulting' (default) or 'Testing'.
        only_without_status: If true, return only offers with an empty Status column
            (not yet applied/rejected/reviewed).
        limit: Maximum number of offers to return (newest first).

    Returns:
        dict with total (rows in the tab), matching (after filter), and jobs
        (row, title, company, salary, source, url, found_date, status).
    """
    rows = sheets.get_rows(sheet)
    matching = [r for r in rows if not (only_without_status and r.get("Status", "").strip())]
    newest_first = list(reversed(matching))[: max(limit, 0)]
    jobs = [
        {
            "row": r["row"],
            "title": r.get("Title", ""),
            "company": r.get("Company", ""),
            "salary": r.get("Salary", ""),
            "source": r.get("Source", ""),
            "url": r.get("URL", ""),
            "found_date": r.get("Found Date", ""),
            "status": r.get("Status", ""),
            # We Work Remotely asks job seekers for a paid subscription before applying (seen 2026-11-12)
            "paid_apply": "weworkremotely.com" in r.get("URL", ""),
        }
        for r in newest_first
    ]
    return {"sheet": sheet, "total": len(rows), "matching": len(matching), "jobs": jobs}


@mcp.tool()
def get_job_details(row: int, sheet: str = "Consulting") -> dict:
    """Fetch the full description of one job offer from its link. Read-only.

    Args:
        row: Row number of the offer in the sheet (the 'row' field from list_new_jobs).
        sheet: Sheet tab: 'Consulting' (default) or 'Testing'.

    Returns:
        dict with title, company, url, ok (text found?), method (how it was read),
        text (offer description / requirements, up to ~8000 characters) and note
        (why it failed, if it did — some sites block bots or need JavaScript).
    """
    job = next((r for r in sheets.get_rows(sheet) if r["row"] == row), None)
    if job is None:
        return {"ok": False, "note": f"No row {row} in sheet '{sheet}'."}
    details = fetch_details(job.get("URL", ""))
    return {
        "row": row,
        "title": job.get("Title", ""),
        "company": job.get("Company", ""),
        "url": job.get("URL", ""),
        **details,
    }


@mcp.tool()
def mark_job(
    row: int,
    status: str,
    sheet: str = "Consulting",
    note: str = "",
    expected_title: str = "",
) -> dict:
    """Set the Status of one offer and optionally save a note about the company and role. Writes to the sheet.

    Status conventions used by the dashboard: 'Applied DD.MM' (application sent), 'TAK' (want to apply),
    'NIE (reason)' (rejected, hidden), 'WYGASŁO' (expired, hidden).

    Args:
        row: Row number of the offer (the 'row' field from list_new_jobs).
        status: New status text, e.g. 'Applied 12.11' or 'NIE (3 years of SAP required)'.
        sheet: Sheet tab: 'Consulting' (default), 'Wdrozenia', 'Testing' or 'low-code'.
        note: Optional short description of the company and role, to read before an interview.
            Leave empty to keep the existing note.
        expected_title: Optional part of the offer title; the write is refused if the row holds
            a different offer (protects against rows that moved).

    Returns:
        dict with ok, the offer (title, company), previous and new status and note.
    """
    offer, error = _check_row(sheet, row, expected_title)
    if error:
        return {"ok": False, "note": error}
    values = {"status": status.strip()}
    if note.strip():
        values["note"] = note.strip()
    sheets.write_cells(sheet, row, values)
    return {
        "ok": True,
        "sheet": sheet,
        "row": row,
        "title": offer["title"],
        "company": offer["company"],
        "previous_status": offer["status"],
        "new_status": values["status"],
        "previous_note": offer["note"],
        "new_note": values.get("note", offer["note"]),
    }


@mcp.tool()
def save_assessment(
    row: int,
    score: int,
    have: str,
    learnable: str,
    barriers: str,
    region: str = "",
    sheet: str = "Consulting",
    expected_title: str = "",
) -> dict:
    """Save a fit assessment of one offer in the sheet (column 'Ocena dopasowania'). Writes to the sheet.

    Read the full offer first (get_job_details) and rate each requirement as one of: have / learnable
    quickly / barrier. Saving again replaces the previous assessment of that row.

    Args:
        row: Row number of the offer (the 'row' field from list_new_jobs).
        score: Overall fit from 0 (no chance) to 10 (perfect fit).
        have: Requirements the candidate already meets.
        learnable: Requirements that can be learned quickly (a short course or a few days).
        barriers: Real barriers, e.g. years of experience in a specific platform or domain. 'none' if none.
        region: Optional: can the job be done from Poland (e.g. 'remote EU', 'US only').
        sheet: Sheet tab: 'Consulting' (default), 'Wdrozenia', 'Testing' or 'low-code'.
        expected_title: Optional part of the offer title, as in mark_job.

    Returns:
        dict with ok, the offer (title, company) and the saved text.
    """
    if not 0 <= score <= 10:
        return {"ok": False, "note": "score must be between 0 and 10."}
    offer, error = _check_row(sheet, row, expected_title)
    if error:
        return {"ok": False, "note": error}
    parts = [
        date.today().isoformat(),
        f"{score}/10",
        f"Masz: {have.strip() or '-'}",
        f"Do nauczenia szybko: {learnable.strip() or '-'}",
        f"Bariera: {barriers.strip() or 'brak'}",
    ]
    if region.strip():
        parts.append(f"Region: {region.strip()}")
    text = " | ".join(parts)
    sheets.write_cells(sheet, row, {"assessment": text})
    return {
        "ok": True,
        "sheet": sheet,
        "row": row,
        "title": offer["title"],
        "company": offer["company"],
        "previous_assessment": offer["assessment"],
        "saved": text,
    }


@mcp.tool()
def scan_jobs(profile: str, dry_run: bool = False) -> dict:
    """Run the job scanner for one search profile and add new offers to its sheet tab. Writes to the sheet.

    Takes about a minute. Each run uses a few calls of the monthly JSearch quota (200 per month,
    also used by the automatic Monday/Thursday scan), so do not run it in a loop.

    Args:
        profile: Search profile: 'QA' (tab Testing), 'Consulting' (tab Consulting)
            or 'Implementation' (tab Wdrozenia).
        dry_run: If true, only show what would be added, without writing to the sheet.

    Returns:
        dict with ok, profile, sheet, added (number of new offers), new_jobs (title, company, url,
        up to 20) and log (per-source counts and errors).
    """
    chosen = next((p for p in PROFILES if p.name.lower() == profile.strip().lower()), None)
    if chosen is None:
        return {"ok": False, "note": f"Unknown profile '{profile}'. Available: {[p.name for p in PROFILES]}"}
    # The scanner prints progress; stdout is the MCP channel, so capture it instead of letting it through.
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            new_jobs = run_profile(chosen, dry_run) or []
    except Exception as e:
        return {"ok": False, "profile": chosen.name, "note": str(e), "log": _scan_log(buffer.getvalue())}
    if dry_run:
        # The scanner's dry run does not read the sheet; drop offers that are already there (read-only).
        existing = sheets.get_existing_urls(chosen.sheet) | sheets.get_existing_urls(sheets.ARCHIVE_SHEET)
        new_jobs = [j for j in new_jobs
                    if not (sheets.offer_keys(j.get("url", ""), j.get("title", ""), j.get("company", "")) & existing)]
    return {
        "ok": True,
        "profile": chosen.name,
        "sheet": chosen.sheet,
        "dry_run": dry_run,
        "added": 0 if dry_run else len(new_jobs),
        "found_new": len(new_jobs),
        "new_jobs": [{"title": j.get("title", ""), "company": j.get("company", ""), "url": j.get("url", "")}
                     for j in new_jobs[:20]],
        "log": _scan_log(buffer.getvalue()),
    }


@mcp.tool()
def check_offers(sheet: str = "Consulting", archive_closed: bool = False) -> dict:
    """Check live whether the offers without a status are still open; optionally archive the closed ones.

    Opens each offer link (results are cached for a few hours). An offer counts as closed only on clear
    signals: HTTP 404/410, a redirect to a 'closed job' page, or 'expired' wording at the top of the page.
    Pages that block bots or need JavaScript stay 'unknown' and are never archived.

    Args:
        sheet: Sheet tab: 'Consulting' (default), 'Wdrozenia', 'Testing' or 'low-code'.
        archive_closed: If true, move closed offers to the 'Archiwum' tab (copied first, then removed
            from the tab; nothing is lost). Row numbers in the tab change afterwards.

    Returns:
        dict with counts per state (ok / closed / region / unknown), the closed and region-limited offers
        (row, title, company, note), and how many rows were archived.
    """
    cols = sheets.layout(sheet)
    service, spreadsheet_id = sheets._get_service()
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{sheet}'!A1:N").execute().get("values", [])
    idx = {k: ord(c) - ord("A") for k, c in cols.items()}
    offers = []
    for number, raw in enumerate(values[1:], start=2):
        row = raw + [""] * (14 - len(raw))
        url = row[idx["url"]].strip()
        if url.startswith("http") and not row[idx["status"]].strip():
            offers.append({"row": number, "title": row[idx["title"]], "company": row[idx["company"]], "url": url})
    results = check_many([o["url"] for o in offers])
    counts = {"ok": 0, "closed": 0, "region": 0, "unknown": 0}
    closed, region = [], []
    for o in offers:
        res = results.get(o["url"], {})
        state = res.get("state", "unknown")
        counts[state] = counts.get(state, 0) + 1
        item = {"row": o["row"], "title": o["title"], "company": o["company"], "note": res.get("note", "")}
        if state == "closed":
            closed.append(item)
        elif state == "region":
            region.append(item)
    archived = 0
    if archive_closed and closed:
        archived = sheets.archive_rows(sheet, [c["row"] for c in closed], date.today().isoformat())
    return {"sheet": sheet, "checked": len(offers), "counts": counts, "closed": closed,
            "region_limited": region, "archived": archived}


def _scan_log(text: str) -> list[str]:
    """Keep only the per-source lines of the scanner output (no URLs: some contain API keys)."""
    keep = ("Fetching from", "fetched,", "ERROR", "Total new jobs")
    return [line.strip() for line in text.splitlines() if line.strip().startswith(keep) or "fetched," in line]


if __name__ == "__main__":
    mcp.run()
