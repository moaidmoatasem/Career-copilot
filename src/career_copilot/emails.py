"""Turn notification emails (LinkedIn, Bayt, GulfTalent, NaukriGulf, Wuzzuf, …) into structured records.

This is the compliant replacement for reading LinkedIn directly: LinkedIn already emails you job
alerts, message notifications and digests. The parser is heuristic because email layouts change;
anything it can't read is reported, and jobs can always be added by hand with add_job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from urllib.parse import urlsplit

from . import geo
from .safety import clean_text, detect_flags, has_warning, prepare_untrusted
from .util import short_hash, strip_query, to_utc_iso

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
LI_JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#\s<>]*?-)?(\d{6,})", re.I)
LI_THREAD_RE = re.compile(r"linkedin\.com/(?:comm/)?messaging/thread/([^/?#\s<>]+)", re.I)
LI_POST_RE = re.compile(r"linkedin\.com/(?:comm/)?(?:posts|feed/update|pulse)/[^\s<>?#]+", re.I)

JOB_BOARD_DOMAINS = ("bayt.com", "gulftalent.com", "naukrigulf.com", "wuzzuf.net", "indeed.com",
                     "glassdoor.com", "laimoon.com", "drjobpro.com")
_JOB_BOARD_PATH = re.compile(r"/(?:jobs?|vacanc(?:y|ies)|careers?)/|-jid-|/job-listing", re.I)
_NON_JOB_PATH = re.compile(r"unsubscribe|alert|setting|preference|login|signin|sign-in|/help|privacy|terms", re.I)

_BOILERPLATE = re.compile(
    r"^(?:view job|view jobs|view all|apply(?: now)?|easy apply|see all jobs|see more jobs|see jobs|promoted"
    r"|actively (?:recruiting|hiring)|be an early applicant|new|save|saved|unsubscribe|help|get the app"
    r"|manage (?:your )?(?:job )?alerts?|linkedin|this email was intended for.*|you are receiving.*"
    r"|you're receiving.*|©.*|\d+ (?:connections?|alumni|applicants?|school alumni|company alumni)(?: work here)?"
    r"|\d+ new jobs?.*|learn why we included this.*|top job picks for you|your job alert.*|jobs? similar to.*"
    r"|reply|view message|view profile|accept|ignore|see all|read more|·|\|)$",
    re.I,
)

_RECRUITER = re.compile(
    r"\b(opportunit(?:y|ies)|role|position|vacanc(?:y|ies)|hiring|interview|recruit(?:er|ing|ment)?"
    r"|talent acquisition|headhunt\w*|job|offer|salary|package|cv|resume|relocat\w*|notice period)\b",
    re.I,
)
_SALES = re.compile(
    r"\b(demo|partnership|our services|outsourc\w*|offshore|lead generation|pricing|discount"
    r"|webinar|investment opportunity|free trial)\b",
    re.I,
)
_NETWORKING = re.compile(r"\b(congrat\w*|thanks for connecting|great to connect|nice to meet|catch up|coffee chat)\b", re.I)

_NAME_PATTERNS = [
    re.compile(r"^(?P<name>.+?) (?:has )?sent you (?:a |an )?(?:new )?(?:message|inmail)", re.I),
    re.compile(r"^(?:you have )?(?:a )?new message from (?P<name>.+)$", re.I),
    re.compile(r"^message from (?P<name>.+)$", re.I),
    re.compile(r"^(?P<name>.+?) (?:messaged|replied to) you", re.I),
    re.compile(r"^(?P<name>.+?) (?:wants to connect|invited you to connect|sent you an invitation)", re.I),
    re.compile(r"^(?:accept|respond to) (?P<name>.+?)['’]s invitation", re.I),
]


@dataclass
class EmailParseResult:
    kind: str
    jobs: list[dict] = field(default_factory=list)
    inbox_items: list[dict] = field(default_factory=list)
    news_items: list[dict] = field(default_factory=list)
    job_ids_mentioned: list[str] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def classify(sender: str, subject: str, text: str) -> str:
    s, subj = sender.lower(), subject.lower()
    address = parseaddr(sender)[1].lower()
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    if "jobalerts" in s:
        return "job_alert"
    if "messages-noreply" in s or "inmail" in s or re.search(
        r"(?:sent|has sent) you (?:a |an )?(?:new )?(?:message|inmail)|new messages?\b|messaged you"
        r"|replied to (?:your|you)|\binmail\b",
        subj,
    ):
        return "message"
    if "invitations" in s or re.search(r"invitation|wants to connect|invited you to connect|connection request", subj):
        return "invitation"
    if "jobs-noreply" in s or re.search(
        r"your application|application (?:was )?(?:sent|viewed|submitted|received)|you applied|update on your application",
        subj,
    ):
        return "application_update"
    if (
        re.search(r"job alert|new jobs? (?:for|match|in|similar)|jobs? (?:you|that) (?:may|might) (?:be interested|like)"
                  r"|is hiring|recommended jobs?|jobs? similar to|top job picks", subj)
        or len(set(LI_JOB_RE.findall(text))) >= 2
        or (any(domain.endswith(d) for d in JOB_BOARD_DOMAINS) and re.search(r"jobs?|vacanc|opportunit|hiring", subj))
    ):
        return "job_alert"
    if re.search(r"viewed your profile|appeared in \d+ searches|search appearances|profile views?", subj):
        return "profile_activity"
    if "newsletters" in s or "updates-noreply" in s or "digest" in s or re.search(
        r"top posts|trending|newsletter|digest|posted|shared a post|commented|what's new|recommended for you|new post",
        subj,
    ):
        return "digest"
    return "other"


def _is_noise(line: str) -> bool:
    stripped = line.strip().strip("<>").rstrip(":").strip()
    return (
        len(stripped) < 2
        or len(stripped) > 160
        or URL_RE.fullmatch(stripped) is not None
        or _BOILERPLATE.match(stripped) is not None
    )


def _meaningful_before(lines: list[str], index: int, limit: int) -> list[str]:
    found: list[str] = []
    for i in range(index - 1, -1, -1):
        line = lines[i]
        if URL_RE.search(line):
            break
        if not _is_noise(line):
            found.append(line.strip())
            if len(found) == limit:
                break
    return list(reversed(found))


def _meaningful_after(lines: list[str], index: int, limit: int) -> list[str]:
    found: list[str] = []
    for line in lines[index + 1:]:
        if URL_RE.search(line):
            break
        if not _is_noise(line):
            found.append(line.strip())
            if len(found) == limit:
                break
    return found


def _segments(line: str) -> list[str]:
    return [s.strip() for s in re.split(r"\s+[|·•]\s+", line) if s.strip() and not _is_noise(s)]


def _company_location(segments: list[str]) -> tuple[str, str]:
    segments = [s for s in segments if not _is_noise(s)]
    if len(segments) >= 2:
        return segments[0], segments[1]
    if len(segments) == 1:
        return ("", segments[0]) if geo.looks_like_location(segments[0]) else (segments[0], "")
    return "", ""


def _job_url(url: str) -> tuple[str, str, str] | None:
    """Return (source, external_id, canonical_url) for job links, else None."""
    match = LI_JOB_RE.search(url)
    if match:
        job_id = match.group(1)
        return "linkedin", job_id, f"https://www.linkedin.com/jobs/view/{job_id}/"
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    if any(host == d or host.endswith("." + d) for d in JOB_BOARD_DOMAINS):
        if _JOB_BOARD_PATH.search(parts.path) and not _NON_JOB_PATH.search(parts.path):
            canonical = strip_query(url)
            return host, short_hash(canonical), canonical
    return None


def extract_jobs(text: str) -> tuple[list[dict], int]:
    """Return (jobs with titles, number of job links whose title could not be read)."""
    lines = text.splitlines()
    found: dict[str, dict] = {}
    for index, line in enumerate(lines):
        for match in URL_RE.finditer(line):
            parsed = _job_url(match.group(0).rstrip(".,;>"))
            if not parsed:
                continue
            source, external_id, canonical = parsed
            anchor = line[: match.start()].rstrip(" <").strip()
            anchor = URL_RE.sub("", anchor).strip(" -:|")
            if anchor and not _is_noise(anchor):
                segments = _segments(anchor) or [anchor]
                title = segments[0]
                following = [seg for later in _meaningful_after(lines, index, 2) for seg in (_segments(later) or [later])]
                company, location = _company_location(segments[1:] or following)
            else:
                before = _meaningful_before(lines, index, 3)
                if len(before) >= 3:
                    title, company, location = before[-3], before[-2], before[-1]
                elif len(before) == 2:
                    title = before[0]
                    company, location = _company_location(_segments(before[1]) or [before[1]])
                elif len(before) == 1:
                    segments = _segments(before[0]) or [before[0]]
                    title = segments[0]
                    company, location = _company_location(segments[1:])
                else:
                    title, company, location = "", "", ""
            key = f"{source}:{external_id}"
            candidate = {
                "source": source,
                "external_id": external_id,
                "url": canonical,
                "title": clean_text(title, 200),
                "company": clean_text(company, 160),
                "location": clean_text(location, 160),
            }
            richness = sum(1 for k in ("title", "company", "location") if candidate[k])
            current = found.get(key)
            if current is None or richness > sum(1 for k in ("title", "company", "location") if current[k]):
                found[key] = candidate
    jobs = [job for job in found.values() if job["title"]]
    return jobs, len(found) - len(jobs)


def categorize(text: str, flags: list[dict]) -> tuple[str, str]:
    if has_warning(flags, {"scam_signal", "credential_request", "hidden_instruction_override",
                           "instruction_override", "hidden_agent_action_request", "agent_action_request"}):
        return "suspicious", "normal"
    recruiter_hits = len(_RECRUITER.findall(text))
    sales_hits = len(_SALES.findall(text))
    if recruiter_hits and recruiter_hits > sales_hits:
        return "recruiter", "high"
    if sales_hits:
        return "sales_pitch", "low"
    if _NETWORKING.search(text):
        return "networking", "normal"
    return "other", "normal"


def _sender_name(sender: str, subject: str) -> str:
    display = parseaddr(sender)[0].strip().strip('"')
    via = re.match(r"^(?P<name>.+?)\s+via\s+linkedin$", display, re.I)
    if via:
        return via.group("name").strip()
    for pattern in _NAME_PATTERNS:
        match = pattern.match(subject.strip())
        if match:
            return match.group("name").strip(' "')
    return display if display and "linkedin" not in display.lower() else ""


def _preview(text: str, limit: int = 400) -> str:
    kept = [line.strip() for line in text.splitlines() if line.strip() and not _is_noise(line) and not URL_RE.search(line)]
    return clean_text(" ".join(kept[:8]), limit)


def parse_email(sender: str, subject: str, body: str, received_at: str | None = None) -> EmailParseResult:
    text, flags = prepare_untrusted(body)
    subject_clean = clean_text(subject or "", 300)
    flags = flags + [f for f in detect_flags(subject_clean) if f["type"] not in {x["type"] for x in flags}]
    kind = classify(sender or "", subject_clean, text)
    received = to_utc_iso(received_at)
    result = EmailParseResult(kind=kind, flags=flags)

    if kind == "job_alert":
        jobs, untitled = extract_jobs(text)
        result.jobs = jobs
        if untitled:
            result.notes.append(f"{untitled} job link(s) had no readable title; open the email or add them with add_job")
        if not jobs:
            result.notes.append("no jobs could be read from this alert; paste the jobs with add_job instead")

    elif kind in ("message", "invitation"):
        name = clean_text(_sender_name(sender or "", subject_clean), 120)
        thread = LI_THREAD_RE.search(text)
        preview = _preview(text)
        category, priority = categorize(f"{subject_clean} {preview}", flags)
        if kind == "invitation":
            url = "https://www.linkedin.com/mynetwork/invitation-manager/"
            dedupe = f"li-invite:{short_hash((name or subject_clean).lower())}"
        elif thread:
            url = f"https://www.linkedin.com/messaging/thread/{thread.group(1)}/"
            dedupe = f"li-thread:{thread.group(1)}"
        else:
            url = "https://www.linkedin.com/messaging/"
            dedupe = f"email:{short_hash(f'{sender}|{subject_clean}|{received}')}"
        result.inbox_items.append({
            "dedupe_key": dedupe,
            "source": "email",
            "kind": kind,
            "sender": name or "(unknown sender)",
            "subject": subject_clean,
            "preview": preview,
            "url": url,
            "received_at": received,
            "category": category,
            "priority": priority,
            "flags": flags,
        })

    elif kind == "application_update":
        result.job_ids_mentioned = sorted(set(LI_JOB_RE.findall(text)))
        result.inbox_items.append({
            "dedupe_key": f"email:{short_hash(f'{sender}|{subject_clean}|{received}')}",
            "source": "email",
            "kind": "application_update",
            "sender": "LinkedIn Jobs",
            "subject": subject_clean,
            "preview": _preview(text),
            "url": "https://www.linkedin.com/my-items/saved-jobs/?cardType=APPLIED",
            "received_at": received,
            "category": "application",
            "priority": "normal",
            "flags": flags,
        })

    elif kind == "digest":
        lines = text.splitlines()
        seen: set[str] = set()
        for index, line in enumerate(lines):
            for match in LI_POST_RE.finditer(line):
                url = strip_query("https://www." + match.group(0))
                if url in seen:
                    continue
                seen.add(url)
                anchor = URL_RE.sub("", line[: match.start()]).strip(" <-:|")
                title = anchor if anchor and not _is_noise(anchor) else " ".join(_meaningful_before(lines, index, 1))
                if not title:
                    continue
                result.news_items.append({
                    "dedupe_key": f"li-post:{short_hash(url)}",
                    "source": "linkedin_email",
                    "feed": "LinkedIn digest email",
                    "title": clean_text(title, 300),
                    "url": url,
                    "published": received,
                    "summary": "",
                    "flags": detect_flags(title),
                })
        if not result.news_items:
            result.notes.append("no post links found in this digest")
    else:
        result.notes.append(f"ignored: '{kind}' emails aren't stored")
    return result
