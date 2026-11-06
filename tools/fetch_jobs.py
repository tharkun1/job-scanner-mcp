"""
Job Scanner — main entrypoint.

Usage:
    python tools/fetch_jobs.py                  # all profiles (QA + Consulting)
    python tools/fetch_jobs.py consulting      # one profile only
    python tools/fetch_jobs.py --dry-run       # fetch and print, write nothing

Fetches jobs for each search profile (tools/profiles.py) from all sources, deduplicates
against that profile's sheet tab, and appends only new jobs. Prints a summary to stdout.

Required env vars (see .env):
    GOOGLE_SERVICE_ACCOUNT_EMAIL
    GOOGLE_PRIVATE_KEY
    GOOGLE_SPREADSHEET_ID
    ADZUNA_APP_ID / ADZUNA_APP_KEY    (optional — skipped if missing)
    RAPIDAPI_KEY                        (optional — skipped if missing)
"""

import sys
import os

# Allow running from project root: python tools/fetch_jobs.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows terminal may default to cp1250 — force UTF-8 for job titles with accents
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from tools import sheets
from tools.profiles import PROFILES
from tools.sources import (
    justjoinit,
    nofluffjobs,
    pracujwit,
    adzuna,
    jsearch,
    undp,
    remoteok,
    weworkremotely,
    remotive,
)


SOURCES = [
    # ── Polish IT job boards ──────────────────────────────────────────────────
    ("JustJoin.it",         justjoinit.fetch),
    ("NoFluffJobs",         nofluffjobs.fetch),
    ("Pracuj.pl IT",        pracujwit.fetch),

    # ── International organisations ───────────────────────────────────────────
    # UN RSS feeds decommissioned — UN orgs covered via JSearch (LinkedIn)
    ("UN/UNDP/ILO (RSS)",   undp.fetch),

    # ── Western remote-first boards (EU/US companies, EUR/USD pay) ───────────
    ("RemoteOK",            remoteok.fetch),
    ("WeWorkRemotely",      weworkremotely.fetch),
    ("Remotive",            remotive.fetch),

    # ── Aggregators (LinkedIn, Indeed, Glassdoor, Adzuna) ────────────────────
    ("Adzuna",              adzuna.fetch),
    ("LinkedIn/Indeed (JSearch)", jsearch.fetch),
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    profiles = [p for p in PROFILES if not args or p.name.lower() in {a.lower() for a in args}]
    if not profiles:
        print(f"Unknown profile {args}. Available: {[p.name for p in PROFILES]}")
        sys.exit(1)

    for profile in profiles:
        run_profile(profile, dry_run)


def run_profile(profile, dry_run: bool):
    print(f"=== Job Scanner — {profile.name} -> sheet '{profile.sheet}'"
          f"{' (dry run)' if dry_run else ''} ===\n")

    existing_urls: set[str] = set()
    if dry_run:
        print("Dry run: skipping Google Sheets.\n")
    else:
        print("Connecting to Google Sheets...")
        try:
            sheets.ensure_header(profile.sheet)
        except Exception as e:
            print(f"ERROR: Could not connect to Google Sheets: {e}")
            print("Check GOOGLE_SERVICE_ACCOUNT_EMAIL, GOOGLE_PRIVATE_KEY, GOOGLE_SPREADSHEET_ID in .env")
            sys.exit(1)

        existing_urls = sheets.get_existing_urls(profile.sheet)
        print(f"Found {len(existing_urls)} existing jobs in sheet.\n")

    all_new_jobs: list[dict] = []

    for name, fetch_fn in SOURCES:
        print(f"Fetching from {name}...")
        try:
            jobs = fetch_fn(profile)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        new_jobs = []
        for j in jobs:
            keys = sheets.offer_keys(j.get("url", ""), j.get("title", ""), j.get("company", ""))
            if j.get("url") and not (keys & existing_urls):
                new_jobs.append(j)
                existing_urls |= keys

        print(f"  {len(jobs)} fetched, {len(new_jobs)} new")
        all_new_jobs.extend(new_jobs)

    print(f"\nTotal new jobs found: {len(all_new_jobs)}")

    if all_new_jobs and dry_run:
        _print_summary(all_new_jobs)
    elif all_new_jobs:
        print("Writing to Google Sheets...")
        added = sheets.append_jobs(all_new_jobs, profile.sheet)
        print(f"Added {added} rows to the sheet.\n")
        _print_summary(all_new_jobs)
    else:
        print("No new jobs this run — sheet is up to date.")

    print("\nDone.")


def _print_summary(jobs: list[dict]):
    print("\n--- New jobs added ---")

    by_source: dict[str, list[dict]] = {}
    for j in jobs:
        by_source.setdefault(j["source"], []).append(j)

    for source, source_jobs in by_source.items():
        print(f"\n[{source}] — {len(source_jobs)} new")
        for j in source_jobs:
            salary = f" | {j['salary']}" if j['salary'] else ""
            print(f"  {j['title']} — {j['company']}{salary}")
            print(f"  {j['url']}")

    print("\n----------------------")


if __name__ == "__main__":
    main()
