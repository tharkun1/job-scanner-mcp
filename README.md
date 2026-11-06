# job-scanner-mcp

A personal MCP server (Python, FastMCP) that lets an AI assistant read job offers collected in a Google Sheet and pull the full text of each offer, so I can ask in plain language: "show me the newest offers" or "what does this one actually require?".

Built with [Claude Code](https://claude.com/claude-code) (AI-assisted development) as a learning project. Status: work in progress, three tools are done, three more are planned and three are ideas.

## Why

Job boards produce long lists. Reading every posting to check requirements and whether the role is open to candidates in my country takes hours. This project splits the work:

1. A scanner collects offers from several sources into a Google Sheet, one tab per search profile.
2. An MCP server exposes the sheet to the assistant as tools.
3. The assistant reads the full description and compares requirements with my profile (have / quick to learn / barrier), and I decide what to apply for.

## Tools

| Tool | What it does | Status |
|---|---|---|
| `ping` | Health check, returns `pong` | done |
| `list_new_jobs` | Lists offers from a sheet tab (read-only), newest first; optional filter for offers without a status | done |
| `get_job_details` | Fetches the full description of one offer from its link (read-only); reports clearly when a site blocks bots or needs JavaScript | done |
| `save_assessment` | Writes the fit assessment back to the sheet | planned |
| `scan_jobs` | Runs the scanner from the conversation | planned |
| `mark_job` | Changes an offer's status (applied, rejected, ...) and saves a short note about the company and role | planned |
| `list_applied` | Lists offers I applied to with notes, dates and follow-up reminders | idea |
| `check_offer` | Live check whether an offer is still open, available from my country and how many years it asks for | idea |
| `cleanup_sheet` | Removes duplicates and archives old offers, with a preview before any change | idea |

## How it works

- `tools/fetch_jobs.py` fetches offers for each search profile from NoFluffJobs, Adzuna, JSearch (RapidAPI), RemoteOK, We Work Remotely and Remotive, removes duplicates already in the sheet and appends new rows.
- Search profiles (keywords, queries, exclusions) are defined in `tools/profiles.py`.
- `tools/sheets.py` talks to the Google Sheets API with a service account.
- `tools/job_details.py` reads a posting's text (structured data first, then the page text).
- `mcp_server.py` registers the tools with FastMCP.

## Setup

Requires Python 3.10+.

```
pip install fastmcp python-dotenv google-api-python-client google-auth requests feedparser
```

Create a `.env` file (never commit it):

```
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json
GOOGLE_SPREADSHEET_ID=<id from the sheet URL>
ADZUNA_APP_ID=...        # optional
ADZUNA_APP_KEY=...       # optional
RAPIDAPI_KEY=...         # optional (JSearch)
```

Share the Google Sheet with the service account's e-mail address. Sheet columns: Title, Company, Salary, Source, URL, Found Date, Status, Location.

Run the scanner once:

```
python tools/fetch_jobs.py --dry-run
```

Register the server in Claude Code (project scope), then start a new conversation so it loads:

```
claude mcp add --scope project job-scanner -- python mcp_server.py
```

## Lessons learned

- MCP servers load when a conversation starts; after adding one, open a new conversation.
- Paths must be anchored to the server file's folder, because the editor starts the process from wherever it happens to be.
- Error logs must never include URLs that contain API keys.
- Many "remote" postings are limited to specific countries, so region eligibility has to be checked from the description, not the title.

## Roadmap

- `save_assessment`, `scan_jobs`, `mark_job`.
- Scoring from the full description instead of the title alone.

## License

Add a license before publishing (for example MIT).
