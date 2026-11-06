"""Google Sheets helper — read existing URLs and append new job rows."""

import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_SHEET = "Testing"
HEADER = ["Title", "Company", "Salary", "Source", "URL", "Found Date", "Status", "Location"]


def _get_service():
    spreadsheet_id = os.environ["GOOGLE_SPREADSHEET_ID"]

    # Prefer a JSON key file (most reliable — avoids .env escaping issues)
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_file:
        creds = service_account.Credentials.from_service_account_file(
            key_file, scopes=SCOPES
        )
    else:
        # Fallback: individual env vars (GOOGLE_SERVICE_ACCOUNT_EMAIL + GOOGLE_PRIVATE_KEY)
        email = os.environ["GOOGLE_SERVICE_ACCOUNT_EMAIL"]
        key = os.environ["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n")
        creds = service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "client_email": email,
                "private_key": key,
                "token_uri": "https://oauth2.googleapis.com/token",
            },
            scopes=SCOPES,
        )

    service = build("sheets", "v4", credentials=creds)
    return service, spreadsheet_id


def ensure_header(sheet_name: str = DEFAULT_SHEET):
    """Create the sheet tab and write header row if not already there."""
    service, spreadsheet_id = _get_service()
    sheets = service.spreadsheets()

    meta = sheets.get(spreadsheetId=spreadsheet_id).execute()
    sheet_names = [s["properties"]["title"] for s in meta["sheets"]]

    if sheet_name not in sheet_names:
        sheets.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        ).execute()

    result = (
        sheets.values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:G1")
        .execute()
    )
    # older tabs have no Location header yet
    h1 = sheets.values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!H1").execute().get("values")
    if result.get("values") and not h1:
        sheets.values().update(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!H1", valueInputOption="RAW",
                               body={"values": [["Location"]]}).execute()
    if not result.get("values"):
        sheets.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [HEADER]},
        ).execute()


def canonical_url(url: str) -> str:
    """Adzuna puts a random "?se=..." token into every link, so the same ad gets a new URL on each scan;
    the ad id in the path identifies the offer. Other links are used as they are."""
    from urllib.parse import urlsplit
    p = urlsplit(url or "")
    return f"{p.scheme}://{p.netloc}{p.path}" if "adzuna." in p.netloc else (url or "")


def offer_keys(url: str, title: str, company: str) -> set[str]:
    """Identity of an offer for duplicate detection: its canonical URL and, when both are known, 'title|company'
    (the same posting is often listed once per city or per US state)."""
    keys = {canonical_url(url)}
    if title.strip() and company.strip():
        keys.add(f"{title.strip().lower()}|{company.strip().lower()}")
    return keys


def get_existing_urls(sheet_name: str = DEFAULT_SHEET) -> set[str]:
    """Return the identity keys (canonical URL and title|company) of every offer already in the sheet."""
    service, spreadsheet_id = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A2:E")
        .execute()
    )
    keys: set[str] = set()
    for row in result.get("values", []):
        row = row + [""] * (5 - len(row))
        keys |= offer_keys(row[4], row[0], row[1])
    return keys


def append_jobs(jobs: list[dict], sheet_name: str = DEFAULT_SHEET) -> int:
    """Append a list of job dicts to the sheet. Returns number of rows added."""
    if not jobs:
        return 0

    service, spreadsheet_id = _get_service()
    rows = [
        [
            job.get("title", ""),
            job.get("company", ""),
            job.get("salary", ""),
            job.get("source", ""),
            job.get("url", ""),
            job.get("found_date", ""),
            "",  # Status — filled in manually by user
            job.get("location", ""),
        ]
        for job in jobs
    ]

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()

    return len(rows)


def get_rows(sheet_name: str = DEFAULT_SHEET) -> list[dict]:
    """Return all data rows of a sheet tab as dicts keyed by the header (plus 'row' number)."""
    service, spreadsheet_id = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:H")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []
    header = values[0]
    rows = []
    for i, row in enumerate(values[1:], start=2):
        padded = row + [""] * (len(header) - len(row))
        rows.append({"row": i, **dict(zip(header, padded))})
    return rows


ARCHIVE_SHEET = "Archiwum"
ARCHIVE_HEADER = ["Title", "Company", "Salary", "Source", "URL", "Found Date", "Status", "Archived Date", "From Tab"]


def _sheet_id(service, spreadsheet_id: str, name: str):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == name:
            return s["properties"]["sheetId"]
    return None


def archive_rows(sheet_name: str, row_numbers: list[int], archived_date: str) -> int:
    """Copy the given rows of a tab to the 'Archiwum' tab, then remove them from the source tab.

    Nothing is lost: rows are appended to the archive first and only removed after that succeeded.
    Row numbers are 1-based sheet rows (as returned by get_rows). Returns the number of rows moved.
    """
    if not row_numbers:
        return 0
    service, spreadsheet_id = _get_service()
    sheets_api = service.spreadsheets()

    if _sheet_id(service, spreadsheet_id, ARCHIVE_SHEET) is None:
        sheets_api.batchUpdate(spreadsheetId=spreadsheet_id,
                               body={"requests": [{"addSheet": {"properties": {"title": ARCHIVE_SHEET}}}]}).execute()
        sheets_api.values().update(spreadsheetId=spreadsheet_id, range=f"{ARCHIVE_SHEET}!A1", valueInputOption="RAW",
                                   body={"values": [ARCHIVE_HEADER]}).execute()

    wanted = set(row_numbers)
    values = sheets_api.values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:G").execute().get("values", [])
    moved = []
    for number in sorted(wanted):
        if 2 <= number <= len(values):
            row = values[number - 1] + [""] * (7 - len(values[number - 1]))
            moved.append(row[:7] + [archived_date, sheet_name])
    if not moved:
        return 0

    sheets_api.values().append(spreadsheetId=spreadsheet_id, range=f"{ARCHIVE_SHEET}!A1", valueInputOption="RAW",
                               insertDataOption="INSERT_ROWS", body={"values": moved}).execute()

    sid = _sheet_id(service, spreadsheet_id, sheet_name)
    requests = [{"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": n - 1, "endIndex": n}}}
                for n in sorted(wanted, reverse=True) if 2 <= n <= len(values)]  # bottom to top keeps indexes valid
    sheets_api.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
    return len(moved)
