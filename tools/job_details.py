"""Fetch the full text of a job offer from its URL (best effort).

Order of attempts:
  1. NoFluffJobs posting API (structured requirements)
  2. schema.org JobPosting JSON-LD embedded in the page
  3. visible text of the page
Many job boards render with JavaScript or block bots; in that case an explanatory
message is returned instead of text.
"""

import json
import re
from html.parser import HTMLParser

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en,pl;q=0.8",
}
MAX_CHARS = 8000


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "header", "footer", "nav", "form"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.ld: list[str] = []
        self._skip = 0
        self._ld = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and ("type", "application/ld+json") in attrs:
            self._ld = True
        elif tag in self.SKIP:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "div", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
        if tag in self.SKIP and tag != "script" and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._ld:
            self.ld.append(data)
        elif not self._skip:
            self.parts.append(data)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return _clean("".join(p.parts))


def _job_posting_from_ld(blocks: list[str]) -> str:
    def walk(node):
        if isinstance(node, list):
            for n in node:
                yield from walk(n)
        elif isinstance(node, dict):
            if str(node.get("@type", "")).lower() == "jobposting":
                yield node
            for v in node.values():
                if isinstance(v, (list, dict)):
                    yield from walk(v)

    for raw in blocks:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for job in walk(data):
            desc = job.get("description", "")
            if desc:
                return _html_to_text(desc)
    return ""


def _nofluff(url: str) -> str:
    m = re.search(r"nofluffjobs\.com/(?:[a-z]{2}/)?job/([^/?#]+)", url)
    if not m:
        return ""
    resp = requests.get(f"https://nofluffjobs.com/api/posting/{m.group(1)}",
                        headers={**HEADERS, "Accept": "application/json"}, timeout=30)
    if not resp.ok:
        return ""
    data = resp.json()
    lines = []
    req = data.get("requirements", {}) or {}
    for key, label in (("musts", "Required"), ("nices", "Nice to have")):
        names = [x.get("value", "") for x in req.get(key, []) or [] if isinstance(x, dict)]
        if names:
            lines.append(f"{label}: " + ", ".join(names))
    if req.get("description"):
        lines.append(_html_to_text(req["description"]))
    details = data.get("details", {}) or {}
    if details.get("description"):
        lines.append(_html_to_text(details["description"]))
    for key in ("responsibilities", "tasks"):
        val = data.get(key) or details.get(key)
        if val:
            lines.append("Responsibilities: " + (", ".join(val) if isinstance(val, list) else str(val)))
    return "\n".join(l for l in lines if l)


def fetch_details(url: str) -> dict:
    if not re.match(r"^https?://", url or ""):
        return {"ok": False, "method": None, "text": "", "note": "Not an http(s) URL."}

    try:
        text = _nofluff(url)
        if text:
            return {"ok": True, "method": "nofluffjobs-api", "text": text[:MAX_CHARS], "note": ""}
    except Exception as e:  # fall through to generic fetch
        print(f"[job_details] NoFluffJobs API failed: {type(e).__name__}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    except Exception as e:
        return {"ok": False, "method": None, "text": "", "note": f"Request failed: {type(e).__name__}"}
    if not resp.ok:
        return {"ok": False, "method": None, "text": "",
                "note": f"HTTP {resp.status_code} (the site may block automated access; open the link manually)."}

    p = _Text()
    p.feed(resp.text)
    text = _job_posting_from_ld(p.ld)
    method = "json-ld"
    if not text:
        text = _clean("".join(p.parts))
        method = "page-text"
    if len(text) < 300:
        return {"ok": False, "method": method, "text": text,
                "note": "Very little text found (the page probably needs JavaScript or a login). Open the link manually."}
    return {"ok": True, "method": method, "text": text[:MAX_CHARS], "note": f"final_url={resp.url}"}
