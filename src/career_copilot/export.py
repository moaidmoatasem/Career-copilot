"""Read LinkedIn's own data export ("Settings → Data privacy → Get a copy of your data").

This is LinkedIn's sanctioned way to take your data out. We read only what the copilot needs and
minimise what we keep: connections without email addresses, and only the latest message preview
of conversations that are waiting on you.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import emails
from .safety import clean_text, prepare_untrusted
from .util import company_key, strip_query

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
WANTED = {"profile.csv", "positions.csv", "skills.csv", "education.csv", "certifications.csv",
          "messages.csv", "connections.csv", "saved jobs.csv"}

# LinkedIn splits large tables across numbered shards: "Saved Jobs.csv", "Saved Jobs_1.csv", …
_SHARD_RE = re.compile(r"^(?P<stem>.+?)_\d+(?P<suffix>\.csv)$")


class ExportError(ValueError):
    pass


def canonical_name(file_name: str) -> str:
    """Fold a shard name onto the table it belongs to: 'Saved Jobs_1.csv' -> 'saved jobs.csv'."""
    name = file_name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    match = _SHARD_RE.match(name)
    return match.group("stem") + match.group("suffix") if match else name


def read_export(path: Path) -> dict[str, list[str]]:
    """Return {canonical CSV name: [shard text, …]} for the files we use. Never extracts to disk."""
    files: dict[str, list[str]] = defaultdict(list)
    if path.is_dir():
        total = 0
        for csv_path in sorted(path.rglob("*.csv")):
            name = canonical_name(csv_path.name)
            if name not in WANTED:
                continue
            size = csv_path.stat().st_size
            total += size
            if size > MAX_FILE_BYTES:
                raise ExportError(f"{csv_path.name} is larger than {MAX_FILE_BYTES // 2**20} MB")
            if total > MAX_TOTAL_BYTES:
                raise ExportError("export folder is unexpectedly large; refusing to read it")
            files[name].append(csv_path.read_text(encoding="utf-8-sig", errors="replace"))
        return dict(files)
    if not zipfile.is_zipfile(path):
        raise ExportError("expected the LinkedIn export .zip (or a folder with its CSV files)")
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            name = canonical_name(info.filename)
            if info.is_dir() or name not in WANTED:
                continue
            total += info.file_size
            if info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ExportError("export archive is unexpectedly large; refusing to read it")
            with archive.open(info) as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise ExportError(f"{name} is larger than declared; refusing to read it")
            files[name].append(data.decode("utf-8-sig", errors="replace"))
    return dict(files)


def read_rows(text: str, required: set[str]) -> list[dict[str, str]]:
    """Parse a CSV that may start with note lines; the header is the first row containing `required`."""
    if not text:
        return []
    lines = text.splitlines()
    for index, line in enumerate(lines[:20]):
        cells = {c.strip().lower() for c in next(csv.reader([line]), [])}
        if required <= cells:
            reader = csv.DictReader(io.StringIO("\n".join(lines[index:])))
            return [
                {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
                for row in reader
            ]
    return []


def read_table(files: dict[str, list[str]], name: str, required: set[str]) -> list[dict[str, str]]:
    """Rows of one export table, read across every shard LinkedIn split it into."""
    rows: list[dict[str, str]] = []
    for text in files.get(name, []):
        rows.extend(read_rows(text, required))
    return rows


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_month_year(value: str) -> tuple[int, int] | None:
    value = value.strip()
    if not value:
        return None
    match = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", value)
    if match and match.group(1)[:3].lower() in _MONTHS:
        return int(match.group(2)), _MONTHS[match.group(1)[:3].lower()]
    match = re.match(r"^(\d{4})(?:[-/](\d{1,2}))?$", value)
    if match:
        return int(match.group(1)), int(match.group(2) or 1)
    match = re.match(r"^(\d{1,2})/(\d{4})$", value)
    if match:
        return int(match.group(2)), int(match.group(1))
    return None


def parse_message_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def profile_slug(url: str) -> str:
    match = re.search(r"linkedin\.com/in/([^/?#\s]+)", url or "", re.I)
    return match.group(1).lower().rstrip("/") if match else ""


def parse_profile(files: dict[str, list[str]]) -> dict:
    snapshot: dict = {}
    rows = read_table(files, "profile.csv", {"first name", "last name"})
    if rows:
        row = rows[0]
        snapshot["name"] = f"{row.get('first name', '')} {row.get('last name', '')}".strip()
        snapshot["headline"] = row.get("headline", "")
        snapshot["about"] = row.get("summary", "")
        snapshot["location"] = row.get("geo location", "")
    positions = read_table(files, "positions.csv", {"company name", "title"})
    if positions:
        snapshot["positions"] = [
            {
                "company": p.get("company name", ""),
                "title": p.get("title", ""),
                "description": p.get("description", ""),
                "location": p.get("location", ""),
                "started_on": p.get("started on", ""),
                "finished_on": p.get("finished on", ""),
            }
            for p in positions
        ]
    skills = [r["name"] for r in read_table(files, "skills.csv", {"name"}) if r.get("name")]
    if skills:
        snapshot["skills"] = skills
    education = read_table(files, "education.csv", {"school name"})
    if education:
        snapshot["education"] = [
            {"school": e.get("school name", ""), "degree": e.get("degree name", ""),
             "start": e.get("start date", ""), "end": e.get("end date", "")}
            for e in education
        ]
    certifications = read_table(files, "certifications.csv", {"name", "authority"})
    if certifications:
        snapshot["certifications"] = [
            {"name": c.get("name", ""), "authority": c.get("authority", ""),
             "started_on": c.get("started on", ""), "finished_on": c.get("finished on", "")}
            for c in certifications
        ]
    return snapshot


def conversations_awaiting_reply(
    files: dict[str, list[str]],
    me_url: str,
    me_name: str,
    lookback_days: int,
    now: datetime | None = None,
) -> tuple[list[dict], str | None]:
    """Conversations whose latest message is from someone else, within the lookback window."""
    rows = read_table(files, "messages.csv", {"conversation id", "from", "date"})
    if not rows:
        return [], None
    me_slug = profile_slug(me_url)
    me_name = me_name.strip().lower()
    if not me_slug and not me_name:
        return [], "set candidate.linkedin_url (or name) in profile.toml so your own messages can be recognised"
    now = now or datetime.now(timezone.utc)
    by_conversation: dict[str, list[tuple[datetime, dict]]] = defaultdict(list)
    for row in rows:
        if row.get("is message draft", "").lower() in {"yes", "true"}:
            continue
        sent = parse_message_date(row.get("date", ""))
        if sent and row.get("conversation id"):
            by_conversation[row["conversation id"]].append((sent, row))

    waiting: list[dict] = []
    for conversation_id, messages in by_conversation.items():
        messages.sort(key=lambda item: item[0])
        sent, last = messages[-1]
        if (now - sent).days > lookback_days:
            continue
        if last.get("folder", "").lower() in {"spam", "archive", "archived"}:
            continue
        sender_slug = profile_slug(last.get("sender profile url", ""))
        from_me = bool(me_slug and sender_slug == me_slug) or bool(me_name and last.get("from", "").strip().lower() == me_name)
        if from_me:
            continue
        preview, flags = prepare_untrusted(last.get("content", ""), max_len=400)
        waiting.append({
            "conversation_id": conversation_id,
            "sender": clean_text(last.get("from", "") or last.get("conversation title", ""), 120) or "(unknown)",
            "subject": clean_text(last.get("subject", "") or last.get("conversation title", ""), 200),
            "preview": preview,
            "received_at": sent.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            "message_count": len(messages),
            "flags": flags,
        })
    waiting.sort(key=lambda item: item["received_at"], reverse=True)
    return waiting, None


def parse_connections(files: dict[str, list[str]]) -> list[dict]:
    rows = read_table(files, "connections.csv", {"first name", "last name", "company"})
    connections = []
    for row in rows:
        name = clean_text(f"{row.get('first name', '')} {row.get('last name', '')}", 120)
        if not name:
            continue
        company = clean_text(row.get("company", ""), 160)
        url = row.get("url", "")
        connections.append({
            "name": name,
            "company": company,
            "company_key": company_key(company),
            "position": clean_text(row.get("position", ""), 160),
            "profile_url": strip_query(url) if url.startswith("http") else "",
            "connected_on": row.get("connected on", ""),
        })
    return connections


_SAVED_DATE_FORMATS = ("%m/%d/%y, %I:%M %p", "%m/%d/%Y, %I:%M %p", "%m/%d/%y", "%m/%d/%Y")


def parse_saved_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in _SAVED_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return parse_message_date(value)


def parse_saved_jobs(
    files: dict[str, list[str]],
    since_days: int = 365,
    now: datetime | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Jobs you saved on LinkedIn, newest first, plus a count of the rows left out and why.

    These are yours and come from LinkedIn's own export, so no scraping is involved. The export
    carries only the title, company and link — the description still has to be pasted in, which
    keeps the job capped at *promising* until you do. LinkedIn blanks the title and company of
    saved jobs whose posting has since been taken down; those rows are counted, not imported,
    because a job with no title cannot be scored.
    """
    skipped = {"older_than_window": 0, "without_title": 0}
    rows = read_table(files, "saved jobs.csv", {"job url", "job title"})
    if not rows:
        return [], skipped
    now = now or datetime.now(timezone.utc)
    jobs: dict[str, dict] = {}
    for row in rows:
        title = clean_text(row.get("job title", ""), 200)
        url = (row.get("job url", "") or "").strip()
        match = emails.LI_JOB_RE.search(url)
        if not match:
            continue
        if not title:
            skipped["without_title"] += 1
            continue
        saved_at = parse_saved_date(row.get("saved date", ""))
        if saved_at and (now - saved_at).days > since_days:
            skipped["older_than_window"] += 1
            continue
        job_id = match.group(1)
        entry = {
            "external_id": job_id,
            "title": title,
            "company": clean_text(row.get("company name", ""), 160),
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
            "saved_on": saved_at.date().isoformat() if saved_at else "",
        }
        # The same job can be saved in more than one shard; keep the most recent record of it.
        previous = jobs.get(job_id)
        if previous is None or entry["saved_on"] > previous["saved_on"]:
            jobs[job_id] = entry
    ordered = sorted(jobs.values(), key=lambda job: job["saved_on"], reverse=True)
    return ordered, skipped
