"""UN family jobs — RSS feeds are decommissioned (all orgs now use SPA portals).

UNDP, ILO, and UN Careers all return HTML pages instead of RSS XML as of 2025.
UN system jobs with IT/QA requirements are best found via:
  - LinkedIn (covered by JSearch when RAPIDAPI_KEY is configured)
  - careers.un.org (Inspira portal — manual check for P-level ICT roles)
  - jobs.undp.org (manual search)
"""


def fetch(profile=None) -> list[dict]:
    print("  [UN RSS] Feeds decommissioned — all UN portals now require manual access. Skipped.")
    return []
