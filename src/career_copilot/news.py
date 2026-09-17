"""Industry news from RSS/Atom feeds the user configured (fixed list, https only).

The model can't make the server fetch arbitrary URLs: feeds come from profile.toml. That closes an
easy data-exfiltration path (an injected instruction can't smuggle data out in a query string).
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET

from . import __version__
from . import skills as sk
from .config import Profile
from .safety import clean_text, detect_flags, prepare_untrusted
from .scoring import profile_skill_sets
from .util import short_hash, strip_query, to_utc_iso

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_FEED_BYTES = 5 * 1024 * 1024


class NewsError(ValueError):
    pass


def fetch_feed(url: str, timeout: int = 15) -> bytes:
    if not url.lower().startswith("https://"):
        raise NewsError("only https feeds are allowed")
    request = urllib.request.Request(url, headers={
        "User-Agent": f"career-copilot/{__version__} (personal RSS reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced above
        if not response.geturl().lower().startswith("https://"):
            raise NewsError("feed redirected to a non-https URL")
        data = response.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise NewsError("feed is larger than 5 MB")
    return data


def _text(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def parse_feed(data: bytes, feed_name: str) -> list[dict]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError(f"could not parse feed '{feed_name}': {exc}") from exc
    raw_items: list[tuple[str, str, str, str]] = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = ""
            for candidate in entry.findall(f"{ATOM}link"):
                if candidate.get("rel", "alternate") == "alternate":
                    link = candidate.get("href", "")
                    break
            published = _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated"))
            summary = _text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content"))
            raw_items.append((_text(entry.find(f"{ATOM}title")), link, published, summary))
    else:
        channel = root.find("channel")
        for item in (channel.findall("item") if channel is not None else root.iter("item")):
            published = _text(item.find("pubDate")) or _text(item.find(f"{DC}date"))
            raw_items.append((_text(item.find("title")), _text(item.find("link")), published, _text(item.find("description"))))

    items = []
    for title, link, published, summary in raw_items:
        title = clean_text(title, 300)
        if not title:
            continue
        summary_text, flags = prepare_untrusted(summary, max_len=500)
        url = link.strip()
        items.append({
            "dedupe_key": f"feed:{short_hash(strip_query(url) if url else feed_name + title)}",
            "source": "rss",
            "feed": feed_name,
            "title": title,
            "url": url if url.startswith("https://") or url.startswith("http://") else "",
            "published": to_utc_iso(published),
            "summary": summary_text,
            "flags": flags + [f for f in detect_flags(title) if f["type"] not in {x["type"] for x in flags}],
        })
    return items


def score_item(title: str, summary: str, profile: Profile, gap_skills: set[str]) -> tuple[float, list[str]]:
    have, learning, extra = profile_skill_sets(profile)
    score = 0.0
    matched: set[str] = set()
    for keyword in profile.interests:
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", re.I)
        if pattern.search(title):
            score += 2.0
            matched.add(keyword)
        elif pattern.search(summary):
            score += 1.0
            matched.add(keyword)
    for skill in sk.extract_skills(f"{title}\n{summary}", extra) & (have | learning | gap_skills):
        score += 0.5
        matched.add(skill)
    return score, sorted(matched)

