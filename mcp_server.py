"""Job Scanner MCP server — lets Claude read and manage the job offers sheet.

Tools:
  ping            — health check
  list_new_jobs   — read offers from a sheet tab (read-only)
  get_job_details — fetch the full description of one offer from its link (read-only)
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

from tools import sheets  # noqa: E402
from tools.job_details import fetch_details  # noqa: E402

mcp = FastMCP(
    "job-scanner",
    instructions=(
        "Tools for the job offers scanner and its Google Sheet. "
        "Sheet tabs: 'Consulting' (implementation/AI-automation roles) and 'Testing' (QA/testing)."
    ),
)


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


if __name__ == "__main__":
    mcp.run()
