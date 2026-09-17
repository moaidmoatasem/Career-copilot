"""Read-only Gmail transport for job-alert and notification emails.

Two deliberate limits, mirroring the rule that feeds come from profile.toml:

1. **The model cannot choose what is read.** The Gmail search query is built here from a fixed
   sender allowlist (`ALERT_SENDERS`). Callers pass only a time window and a message cap, so an
   injected instruction can't widen the sync into the user's personal mail.
2. **Read-only scope, and authorisation never happens in the MCP server.** The OAuth flow runs
   from the CLI, where a person is present (`career-copilot gmail-auth`). The server can refresh
   an existing token but can never mint one.

Google's client libraries are an optional extra (`pip install 'career-copilot-mcp[gmail]'`) and
are imported lazily, so the rest of the copilot runs without them.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

# Read-only. Enough to read alert mail; not enough to send, modify, label or delete anything.
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

# The only senders a sync will ever read. Anything else in the mailbox is out of reach.
ALERT_SENDERS: tuple[str, ...] = (
    "linkedin.com",
    "bayt.com",
    "gulftalent.com",
    "naukrigulf.com",
    "wuzzuf.net",
)

MAX_MESSAGE_BYTES = 1_000_000
MAX_BODY_CHARS = 400_000
_INSTALL_HINT = (
    "Gmail sync needs Google's client libraries. Install them with:\n"
    "  uv sync --extra gmail        (or: pip install 'career-copilot-mcp[gmail]')"
)


class GmailError(ValueError):
    """An anticipated Gmail problem with a clear, user-facing message."""


@dataclass(frozen=True)
class FetchedMessage:
    """One message, reduced to what `ingest_email` already understands."""

    message_id: str
    sender: str
    subject: str
    body: str
    received_at: str


def credentials_file(home: Path) -> Path:
    """The Google OAuth *client* secrets the user downloads from Google Cloud."""
    raw = os.environ.get("CAREER_COPILOT_GMAIL_CREDENTIALS")
    return Path(raw).expanduser() if raw else home / "gmail-credentials.json"


def token_file(home: Path) -> Path:
    """The user's own refresh/access token. Never leaves this machine."""
    return home / "gmail-token.json"


def build_query(since_days: int = 7) -> str:
    """Build the Gmail search query from the sender allowlist only.

    Callers choose a window, never a sender or a free-text term.
    """
    if not 1 <= since_days <= 365:
        raise GmailError("since_days must be between 1 and 365")
    after = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y/%m/%d")
    senders = " OR ".join(f"from:{domain}" for domain in ALERT_SENDERS)
    return f"({senders}) after:{after}"


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:  # e.g. Windows or unusual filesystems
        pass


def _best_body(message: EmailMessage) -> str:
    """Prefer text/plain; fall back to text/html, which `emails.parse_email` also handles."""
    for subtype in ("plain", "html"):
        try:
            part = message.get_body(preferencelist=(subtype,))
        except Exception:  # malformed MIME trees raise a variety of errors
            part = None
        if part is None:
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):  # unknown charset
            payload = part.get_payload(decode=True) or b""
            content = payload.decode("utf-8", errors="replace")
        if isinstance(content, str) and content.strip():
            return content[:MAX_BODY_CHARS]
    return ""


def message_from_raw(message_id: str, raw: bytes) -> FetchedMessage | None:
    """Decode one RFC-822 message. Returns None when there's no usable body."""
    parsed = message_from_bytes(raw, policy=policy.default)
    body = _best_body(parsed)  # type: ignore[arg-type]
    if not body.strip():
        return None
    received = ""
    date_header = parsed.get("Date", "")
    if date_header:
        try:
            received = parsedate_to_datetime(date_header).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except (TypeError, ValueError):
            received = ""
    return FetchedMessage(
        message_id=message_id,
        sender=str(parsed.get("From", ""))[:500],
        subject=str(parsed.get("Subject", ""))[:500],
        body=body,
        received_at=received,
    )


def _sender_allowed(sender: str) -> bool:
    """Belt and braces: re-check the sender locally, in case the query is ever loosened."""
    match = re.search(r"[\w.+-]+@([\w.-]+)", sender or "")
    domain = (match.group(1) if match else "").lower().rstrip(".")
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in ALERT_SENDERS)


# ---------------------------------------------------------------- authorisation


def _google_modules():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise GmailError(_INSTALL_HINT) from exc
    return Request, Credentials, build


def authorize(home: Path, open_browser: bool = True) -> Path:
    """Run the OAuth consent flow and store the token. CLI only: a person must be present."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise GmailError(_INSTALL_HINT) from exc

    secrets = credentials_file(home)
    if not secrets.exists():
        raise GmailError(
            f"no Google OAuth client found at {secrets}.\n"
            "Create one (free): Google Cloud console → APIs & Services → enable the Gmail API →\n"
            "Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON,\n"
            f"then save it as {secrets}."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), scopes=[SCOPE])
    creds = flow.run_local_server(port=0, open_browser=open_browser)
    target = token_file(home)
    target.write_text(creds.to_json(), encoding="utf-8")
    _restrict(target)
    return target


def load_credentials(home: Path):
    """Load the stored token, refreshing it if it has expired. Never starts a new consent flow."""
    Request, Credentials, _ = _google_modules()
    path = token_file(home)
    if not path.exists():
        raise GmailError("Gmail is not connected yet. Run `career-copilot gmail-auth` in a terminal.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GmailError(f"{path} is unreadable; re-run `career-copilot gmail-auth`") from exc

    creds = Credentials.from_authorized_user_info(data, [SCOPE])
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # google raises several refresh errors
            raise GmailError(
                f"Gmail token could not be refreshed ({exc}). Re-run `career-copilot gmail-auth`."
            ) from exc
        path.write_text(creds.to_json(), encoding="utf-8")
        _restrict(path)
        return creds
    raise GmailError("Gmail token is no longer valid. Re-run `career-copilot gmail-auth`.")


# ---------------------------------------------------------------- fetching


def fetch_messages(home: Path, since_days: int = 7, max_messages: int = 50) -> list[FetchedMessage]:
    """Fetch recent alert emails. The query is built here, never supplied by a caller."""
    if not 1 <= max_messages <= 200:
        raise GmailError("max_messages must be between 1 and 200")
    _, _, build = _google_modules()
    creds = load_credentials(home)
    query = build_query(since_days)

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_messages)
            .execute()
        )
        out: list[FetchedMessage] = []
        for stub in (listing.get("messages") or [])[:max_messages]:
            message_id = str(stub.get("id", ""))
            if not message_id:
                continue
            payload = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="raw")
                .execute()
            )
            raw = payload.get("raw") or ""
            try:
                decoded = base64.urlsafe_b64decode(raw)
            except (binascii.Error, ValueError):
                continue
            if len(decoded) > MAX_MESSAGE_BYTES:
                continue
            message = message_from_raw(message_id, decoded)
            if message is not None and _sender_allowed(message.sender):
                out.append(message)
        return out
    except GmailError:
        raise
    except Exception as exc:  # googleapiclient raises HttpError and transport errors
        raise GmailError(f"Gmail request failed: {str(exc)[:300]}") from exc
