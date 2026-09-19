"""`career-copilot doctor`: does this install actually work?

Everything here is read-only and diagnostic. It creates nothing, repairs nothing and sends
nothing — it looks at what is on disk, optionally reaches the hosts the copilot is allowed to
reach, and reports. Checks that touch the network are skipped with `--offline`, but they are on by
default: whether the job boards let us read them, and whether Gmail still refreshes, are the two
things a fresh install most needs to learn, and they cannot be learned offline.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from . import __version__, boards, gmail, news
from .config import ConfigError, home_dir, load_profile, profile_file
from .store import SCHEMA

OK, WARN, FAIL = "ok", "warn", "fail"

# Representative job paths, used only to ask robots.txt whether such a page may be read.
SAMPLE_PATHS: dict[str, str] = {
    "bayt.com": "https://www.bayt.com/en/uae/jobs/senior-qa-engineer-1234567/",
    "gulftalent.com": "https://www.gulftalent.com/uae/jobs/senior-qa-engineer-123456",
    "naukrigulf.com": "https://www.naukrigulf.com/senior-qa-engineer-jobs-in-dubai-123456",
    "wuzzuf.net": "https://wuzzuf.net/jobs/p/123456-Senior-QA-Engineer",
}

PLACEHOLDERS = ("Your Name", "your-handle", "Senior QA Engineer, Senior Test Automation Engineer")


@dataclass(frozen=True)
class Check:
    status: str
    title: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _posix() -> bool:
    return os.name == "posix"


# ---------------------------------------------------------------- checks


def check_runtime() -> list[Check]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    status = OK if sys.version_info >= (3, 11) else FAIL
    return [
        Check(status, "Python", f"{version} (needs 3.11+)"),
        Check(OK, "Career Copilot", f"version {__version__}"),
    ]


def check_data_dir(home: Path) -> list[Check]:
    if not home.exists():
        return [Check(FAIL, "Data folder", f"{home} does not exist — run `career-copilot init`")]
    out = [Check(OK, "Data folder", str(home))]
    # Always check folder permissions (works on Windows and POSIX)
    mode = _mode(home)
    out.append(
        Check(OK if mode == 0o700 else WARN, "Data folder permissions",
              f"{oct(mode)}" + ("" if mode == 0o700 else " — expected 0o700; others can read your job search"))
    )
    imports = home / "imports"
    out.append(
        Check(OK if imports.is_dir() else WARN, "Imports folder",
              str(imports) if imports.is_dir() else f"{imports} missing — LinkedIn export imports will not work")
    )
    return out


def check_database(home: Path) -> list[Check]:
    path = home / "copilot.db"
    if not path.exists():
        return [Check(WARN, "Database", f"{path} not created yet — run `career-copilot init`")]
    out: list[Check] = []
    if _posix():
        mode = _mode(path)
        out.append(
            Check(OK if mode == 0o600 else FAIL, "Database permissions",
                  f"{oct(mode)}" + ("" if mode == 0o600 else " — expected 0o600; other users can read it"))
        )
    try:
        # Read-only: never create or migrate from a diagnostic.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [*out, Check(FAIL, "Database", f"cannot open {path}: {exc}")]
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        out.append(Check(OK if integrity == "ok" else FAIL, "Database integrity", integrity))

        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = set(_schema_names("TABLE"))
        missing = sorted(expected - names)
        out.append(
            Check(OK if not missing else FAIL, "Database schema",
                  f"{len(expected)} tables present" if not missing else f"missing: {', '.join(missing)}")
        )

        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        want_triggers = set(_schema_names("TRIGGER"))
        out.append(
            Check(OK if want_triggers <= triggers else FAIL, "Audit log is append-only",
                  "insert-only triggers installed" if want_triggers <= triggers
                  else f"missing: {', '.join(sorted(want_triggers - triggers))}")
        )
        out.extend(_work_state(conn))
    except sqlite3.Error as exc:
        out.append(Check(FAIL, "Database", f"query failed: {exc}"))
    finally:
        conn.close()
    return out


def _schema_names(kind: str) -> list[str]:
    """Object names declared in store.SCHEMA.

    A table name is followed by `(`, a trigger name by ` BEFORE ...`, so split on both.
    """
    marker = f"CREATE {kind} IF NOT EXISTS "
    names = []
    for line in SCHEMA.splitlines():
        if line.startswith(marker):
            names.append(line[len(marker):].replace("(", " ").split()[0])
    return names


def _work_state(conn: sqlite3.Connection) -> list[Check]:
    def count(sql: str) -> int:
        try:
            return int(conn.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return 0

    pending = count("SELECT COUNT(*) FROM drafts WHERE status = 'pending'")
    awaiting = count("SELECT COUNT(*) FROM drafts WHERE status = 'approved' AND executed_at IS NULL")
    undescribed = count("SELECT COUNT(*) FROM jobs WHERE description = '' AND status NOT IN ('rejected','archived')")
    return [
        Check(OK, "Drafts waiting for you",
              f"{pending} pending, {awaiting} approved but not yet done"
              + (" — run `career-copilot console` or `review`" if pending else "")),
        Check(OK if not undescribed else WARN, "Jobs without a description",
              f"{undescribed}" + (" — these cap at the promising tier; try `career-copilot fetch-descriptions`"
                                  if undescribed else "")),
    ]


def check_profile(home: Path) -> list[Check]:
    path = profile_file(home)
    if not path.exists():
        return [Check(FAIL, "Profile", f"{path} not found — run `career-copilot init`")]
    try:
        profile = load_profile(path)
    except ConfigError as exc:
        return [Check(FAIL, "Profile", f"{path} will not load: {exc}")]

    out: list[Check] = []
    if _posix():
        mode = _mode(path)
        out.append(Check(OK if mode == 0o600 else WARN, "Profile permissions", oct(mode)))

    raw = path.read_text(encoding="utf-8", errors="replace")
    left = [text for text in PLACEHOLDERS if text in raw]
    out.append(
        Check(WARN if left else OK, "Profile is yours",
              f"still has template values: {', '.join(left)} — scoring is only as good as this file"
              if left else "no template placeholders left")
    )
    out.append(
        Check(OK if profile.target_titles else FAIL, "Target titles",
              ", ".join(profile.target_titles[:4]) or "none set — nothing can be scored against")
    )
    out.append(
        Check(OK if profile.target_locations else WARN, "Target locations",
              ", ".join(profile.target_locations[:5]) or "none set")
    )
    skills = len(profile.skills_have)
    out.append(
        Check(OK if skills >= 3 else WARN, "Skills you have",
              f"{skills} listed" + ("" if skills >= 3 else " — too few to score jobs meaningfully"))
    )
    return out


def check_gmail(home: Path, network: bool) -> list[Check]:
    token = gmail.token_file(home)
    try:
        import googleapiclient  # noqa: F401
        extra = True
    except ImportError:
        extra = False

    out = [
        Check(OK if extra else WARN, "Gmail client libraries",
              "installed" if extra else "not installed — `uv sync --extra gmail` if you want Gmail sync")
    ]
    if not token.exists():
        out.append(Check(WARN, "Gmail connection",
                         "not connected — run `career-copilot gmail-auth` (optional; you can paste emails instead)"))
        return out
    if _posix():
        mode = _mode(token)
        out.append(Check(OK if mode == 0o600 else FAIL, "Gmail token permissions",
                         f"{oct(mode)}" + ("" if mode == 0o600 else " — this file can read your mail; expected 0o600")))
    try:
        data = json.loads(token.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*out, Check(FAIL, "Gmail token", f"unreadable ({exc}) — re-run `career-copilot gmail-auth`")]

    scopes = data.get("scopes") or []
    correct = list(scopes) == [gmail.SCOPE]
    out.append(
        Check(OK if correct else FAIL, "Gmail scope",
              gmail.SCOPE if correct else f"expected only {gmail.SCOPE}, found {scopes or 'none'}")
    )
    if not network:
        out.append(Check(OK, "Gmail token validity", "skipped (--offline)"))
        return out
    if not extra:
        out.append(Check(WARN, "Gmail token validity", "cannot check without the gmail extra"))
        return out
    try:
        gmail.load_credentials(home)
        out.append(Check(OK, "Gmail token validity", "valid (refreshed if it had expired)"))
    except gmail.GmailError as exc:
        out.append(Check(FAIL, "Gmail token validity", str(exc)))
    return out


def check_boards(network: bool) -> list[Check]:
    """Ask each board's robots.txt whether job pages may be read.

    Fetching robots.txt separately from parsing it matters: `RobotFileParser` turns an unreachable
    robots.txt into "everything is disallowed", which would report a blocked network or a transient
    503 as though the board had refused us. Those need different fixes, so they get different
    messages.
    """
    if not network:
        return [Check(OK, "Job boards", "skipped (--offline)")]
    out: list[Check] = []
    for domain in boards.FETCHABLE_DOMAINS:
        url = SAMPLE_PATHS.get(domain, f"https://www.{domain}/")
        origin = f"https://{urlsplit(url).netloc}"
        request = urllib.request.Request(f"{origin}/robots.txt", headers={"User-Agent": boards.USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - https literal above
                text = response.read(512_000).decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code == 404:  # no robots.txt at all means nothing is disallowed
                out.append(Check(OK, f"{domain} robots.txt", "not published, so nothing is disallowed"))
            else:
                out.append(Check(WARN, f"{domain} robots.txt",
                                 f"HTTP {exc.code} — treated as disallowed until it can be read"))
            continue
        except (URLError, OSError) as exc:
            out.append(Check(WARN, f"{domain} reachability",
                             f"could not be reached ({str(exc)[:90]}) — a network or proxy problem, "
                             "not a decision by the board"))
            continue

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(text.splitlines())
        allowed = parser.can_fetch(boards.ROBOTS_AGENT, url)
        out.append(
            Check(OK if allowed else WARN, f"{domain} robots.txt",
                  "allows reading job pages" if allowed
                  else "disallows job pages — descriptions from this board must be pasted by hand")
        )
    return out


def check_feeds(home: Path, network: bool) -> list[Check]:
    try:
        profile = load_profile(profile_file(home))
    except ConfigError:
        return []
    if not profile.feeds:
        return [Check(WARN, "News feeds", "none configured — add [[news.feeds]] entries to profile.toml")]
    out = [Check(OK, "News feeds", f"{len(profile.feeds)} configured")]
    if not network:
        out.append(Check(OK, "Feed reachability", "skipped (--offline)"))
        return out
    feed = profile.feeds[0]
    try:
        size = len(news.fetch_feed(feed.url))
        out.append(Check(OK, "Feed reachability", f"{feed.name} returned {size:,} bytes"))
    except Exception as exc:
        out.append(Check(WARN, "Feed reachability", f"{feed.name} failed: {str(exc)[:120]}"))
    return out


def desktop_config_paths() -> list[Path]:
    """Where Claude Desktop keeps claude_desktop_config.json, per platform."""
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library/Application Support/Claude/claude_desktop_config.json"]
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData/Roaming"
        return [base / "Claude/claude_desktop_config.json"]
    return [
        home / ".config/Claude/claude_desktop_config.json",
        home / ".config/claude/claude_desktop_config.json",
    ]


def check_desktop_config() -> list[Check]:
    found = next((path for path in desktop_config_paths() if path.exists()), None)
    if found is None:
        looked = ", ".join(str(path) for path in desktop_config_paths())
        return [Check(WARN, "Claude Desktop config",
                      f"not found (looked in {looked}) — run `career-copilot claude-config` for the block to add")]
    try:
        data = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Check(FAIL, "Claude Desktop config", f"{found} is not readable JSON: {exc}")]

    servers = data.get("mcpServers")
    entry = servers.get("career-copilot") if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        return [Check(WARN, "Claude Desktop config",
                      f"{found} has no 'career-copilot' server — run `career-copilot claude-config`")]
    out = [Check(OK, "Claude Desktop config", f"registered in {found}")]

    args = entry.get("args") or []
    if isinstance(args, list) and "--directory" in args:
        index = args.index("--directory")
        target = Path(str(args[index + 1])) if index + 1 < len(args) else None
        if target is not None:
            out.append(
                Check(OK if (target / "pyproject.toml").exists() else FAIL, "Configured project directory",
                      str(target) if (target / "pyproject.toml").exists()
                      else f"{target} no longer holds the project — Claude Desktop cannot start the server")
            )
    configured_home = ((entry.get("env") or {}).get("CAREER_COPILOT_HOME") or "").strip()
    if configured_home:
        actual = str(home_dir())
        out.append(
            Check(OK if Path(configured_home) == Path(actual) else WARN, "Configured data folder",
                  configured_home if Path(configured_home) == Path(actual)
                  else f"config says {configured_home}, this shell uses {actual}")
        )
    return out


# ---------------------------------------------------------------- runner


def run_checks(home: Path | None = None, *, network: bool = True) -> list[Check]:
    home = home or home_dir()
    checks: list[Check] = []
    checks += check_runtime()
    checks += check_data_dir(home)
    checks += check_database(home)
    checks += check_profile(home)
    checks += check_gmail(home, network)
    checks += check_boards(network)
    checks += check_feeds(home, network)
    checks += check_desktop_config()
    return checks


def summarise(checks: list[Check]) -> dict[str, int]:
    return {
        status: sum(1 for check in checks if check.status == status)
        for status in (OK, WARN, FAIL)
    }
