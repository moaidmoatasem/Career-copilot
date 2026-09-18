"""Fetch full job descriptions from the job boards the user already receives alerts from.

Job-alert emails carry a title and a link, not a description — and the description is what the
skills half of the score is computed from, so jobs without one are capped at *promising*. This
closes that gap for the Gulf boards without changing what the copilot is willing to do.

Four rules keep it that way:

1. **Never LinkedIn.** LinkedIn job pages are refused by name, not merely left off a list. The
   whole premise of this project is that it does not fetch from LinkedIn; descriptions for
   LinkedIn jobs stay paste-only.
2. **A fixed domain allowlist**, https only. The model cannot pass an arbitrary URL: it names a
   job the copilot already stored, and the URL comes from the database.
3. **robots.txt is honoured** at fetch time, per host, with the same user-agent that does the
   fetching. If a board disallows the path, the fetch does not happen and the job is left alone.
4. **Structured data only.** The description is read from the page's `JobPosting` JSON-LD — the
   data these boards publish precisely so machines can read it (it is what Google for Jobs
   consumes). Pages without it are reported, not scraped for prose: page furniture in a
   description would poison the skill scoring it feeds.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from . import __version__
from .safety import clean_text, html_to_text

# Boards whose job pages may be fetched. Everything else is refused.
FETCHABLE_DOMAINS: tuple[str, ...] = ("bayt.com", "gulftalent.com", "naukrigulf.com", "wuzzuf.net")

# Refused by name, with an explanation, rather than silently missing from the allowlist.
REFUSED_DOMAINS: dict[str, str] = {
    "linkedin.com": (
        "Career Copilot never fetches from LinkedIn — that is the point of the project. "
        "Open the job in your browser and paste its description with add_job or update_job."
    ),
}

USER_AGENT = (
    f"career-copilot/{__version__} (personal job-search assistant; "
    "+https://github.com/moaidmoatasem/Career-copilot)"
)
ROBOTS_AGENT = "career-copilot"
MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_DESCRIPTION_CHARS = 60_000

_JSON_LD = re.compile(
    r"<script[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
    re.I | re.S,
)


class BoardError(ValueError):
    """An anticipated problem fetching a job page, with a user-facing message."""


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def check_url(url: str) -> None:
    """Raise BoardError unless this is an https URL on a board we're allowed to fetch."""
    if not url or not url.lower().startswith("https://"):
        raise BoardError("only https job URLs can be fetched")
    host = host_of(url)
    if not host:
        raise BoardError(f"no hostname in {url!r}")
    for domain, reason in REFUSED_DOMAINS.items():
        if _matches(host, domain):
            raise BoardError(reason)
    if not any(_matches(host, domain) for domain in FETCHABLE_DOMAINS):
        raise BoardError(
            f"{host} is not a job board this fetches from "
            f"(allowed: {', '.join(FETCHABLE_DOMAINS)}). Paste the description instead."
        )


_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    """Fetch and cache a host's robots.txt.

    RobotFileParser's own conventions apply: an unreachable 401/403 means treat everything as
    disallowed, a 404 means nothing is disallowed.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots_cache.get(origin)
    if cached is not None:
        return cached
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    try:
        parser.read()
    except (HTTPError, URLError, OSError, ValueError):
        # Couldn't read robots.txt at all: assume we're not welcome.
        parser.disallow_all = True
    _robots_cache[origin] = parser
    return parser


def robots_allows(url: str) -> bool:
    return bool(robots_for(url).can_fetch(ROBOTS_AGENT, url))


def fetch_page(url: str, timeout: int = 20) -> str:
    """Fetch one job page. Checks the allowlist and robots.txt before making any request."""
    check_url(url)
    if not robots_allows(url):
        raise BoardError(f"{host_of(url)}/robots.txt disallows this page, so it was not fetched")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced in check_url
            final = response.geturl()
            check_url(final)  # a redirect must land somewhere we're still allowed to be
            data = response.read(MAX_PAGE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise BoardError(f"{host_of(url)} returned HTTP {exc.code}") from exc
    except (URLError, OSError) as exc:
        raise BoardError(f"could not reach {host_of(url)}: {str(exc)[:150]}") from exc
    if len(data) > MAX_PAGE_BYTES:
        raise BoardError("job page is larger than 3 MB")
    return data.decode(charset, errors="replace")


def _json_ld_objects(html: str):
    """Yield every object in the page's JSON-LD blocks, flattening @graph and lists."""
    for block in _JSON_LD.findall(html):
        try:
            parsed = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        pending = [parsed]
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, dict):
                yield item
                graph = item.get("@graph")
                if isinstance(graph, (list, dict)):
                    pending.append(graph)


def _is_job_posting(obj: dict) -> bool:
    types = obj.get("@type")
    if isinstance(types, str):
        types = [types]
    return isinstance(types, list) and any(str(t).lower() == "jobposting" for t in types)


def extract_job_posting(html: str) -> dict | None:
    """Return the page's JobPosting JSON-LD object, if it publishes one."""
    for obj in _json_ld_objects(html):
        if _is_job_posting(obj):
            return obj
    return None


def _text(value: object) -> str:
    """JSON-LD descriptions are usually HTML in a string."""
    if not isinstance(value, str) or not value.strip():
        return ""
    visible, _hidden = html_to_text(value)
    return clean_text(visible or value, MAX_DESCRIPTION_CHARS)


def _first_name(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list) and value:
        return _first_name(value[0])
    return str(value or "") if isinstance(value, str) else ""


def _location(posting: dict) -> str:
    place = posting.get("jobLocation")
    if isinstance(place, list) and place:
        place = place[0]
    if not isinstance(place, dict):
        return ""
    address = place.get("address")
    if isinstance(address, list) and address:
        address = address[0]
    if not isinstance(address, dict):
        return ""
    parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
    names = [_first_name(part) for part in parts]
    return clean_text(", ".join(name for name in names if name), 160)


def parse_job_page(html: str) -> dict:
    """Pull description, company and location out of a fetched job page."""
    posting = extract_job_posting(html)
    if posting is None:
        raise BoardError(
            "this page publishes no JobPosting structured data, so there is nothing to read "
            "reliably; open it and paste the description instead"
        )
    description = _text(posting.get("description"))
    if len(description) < 200:
        raise BoardError("the structured data on this page has no usable description")
    return {
        "description": description,
        "company": clean_text(_first_name(posting.get("hiringOrganization")), 160),
        "location": _location(posting),
        "title": clean_text(str(posting.get("title") or ""), 200),
    }


def fetch_job_details(url: str, timeout: int = 20) -> dict:
    """Fetch one job page and return its structured details."""
    return parse_job_page(fetch_page(url, timeout))
