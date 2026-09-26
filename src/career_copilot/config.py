"""Paths, LinkedIn field limits, and the user's career profile (profile.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

# LinkedIn character limits, cross-checked against several 2026 references.
# LinkedIn can change these; the server rejects drafts that exceed them.
LIMITS: dict[str, int] = {
    "headline": 220,
    "about": 2600,
    "position_description": 2000,
    "skill": 80,
    "post": 3000,
    "comment": 1250,
    "message": 8000,
    "connection_note_basic": 200,
    "connection_note_premium": 300,
}

SENIORITY_RANK: dict[str, int] = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "manager": 4,
    "principal": 5,
    "head": 5,
    "director": 6,
}


class ConfigError(ValueError):
    """profile.toml is missing a value or has an invalid one."""


def home_dir() -> Path:
    raw = os.environ.get("CAREER_COPILOT_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".career-copilot"


def profile_file(home: Path) -> Path:
    raw = os.environ.get("CAREER_COPILOT_PROFILE")
    return Path(raw).expanduser() if raw else home / "profile.toml"


def template_text() -> str:
    return (
        resources.files("career_copilot")
        .joinpath("templates/profile.example.toml")
        .read_text(encoding="utf-8")
    )


@dataclass(frozen=True)
class Feed:
    name: str
    url: str


@dataclass
class Profile:
    name: str = ""
    linkedin_url: str = ""
    seniority: str = "senior"
    acceptable_seniority: list[str] = field(default_factory=list)
    premium: bool = False
    target_titles: list[str] = field(default_factory=list)
    target_locations: list[str] = field(default_factory=list)
    remote_ok: bool = False
    exclude_title_keywords: list[str] = field(default_factory=list)
    skills_have: list[str] = field(default_factory=list)
    skills_learning: list[str] = field(default_factory=list)
    skill_aliases: dict[str, list[str]] = field(default_factory=dict)
    tier_matched: int = 75
    tier_promising: int = 55
    tier_close: int = 35
    interests: list[str] = field(default_factory=list)
    feeds: list[Feed] = field(default_factory=list)
    hours_per_week: int = 6
    retention_days: int = 90
    configured: bool = False


def _str_list(section: dict, key: str) -> list[str]:
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"'{key}' must be a list of strings")
    return [v.strip() for v in value if v.strip()]


def _int(section: dict, key: str, default: int, low: int, high: int) -> int:
    value = section.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ConfigError(f"'{key}' must be a whole number between {low} and {high}")
    return value


def _bool(section: dict, key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}' must be true or false")
    return value


def load_profile(path: Path) -> Profile:
    """Load and validate profile.toml. A missing file yields an unconfigured default profile."""
    if not path.exists():
        return Profile()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML ({exc})") from exc

    cand = data.get("candidate", {})
    targets = data.get("targets", {})
    skills = data.get("skills", {})
    tiers = data.get("tiers", {})
    news = data.get("news", {})
    learning = data.get("learning", {})
    privacy = data.get("privacy", {})

    seniority = str(cand.get("seniority", "senior")).strip().lower()
    if seniority not in SENIORITY_RANK:
        raise ConfigError(f"candidate.seniority must be one of: {', '.join(SENIORITY_RANK)}")
    acceptable = [s.lower() for s in _str_list(cand, "acceptable_seniority")]
    unknown = [s for s in acceptable if s not in SENIORITY_RANK]
    if unknown:
        raise ConfigError(f"unknown levels in acceptable_seniority: {', '.join(unknown)}")

    aliases_raw = skills.get("aliases", {})
    if not isinstance(aliases_raw, dict):
        raise ConfigError("[skills.aliases] must map a skill name to a list of aliases")
    aliases: dict[str, list[str]] = {}
    for canon, values in aliases_raw.items():
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ConfigError(f"skills.aliases.{canon} must be a list of strings")
        aliases[canon.strip().lower()] = [v.strip() if v.strip().startswith("re:") else v.strip().lower() for v in values if v.strip()]

    feeds: list[Feed] = []
    for entry in news.get("feeds", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise ConfigError("each [[news.feeds]] entry needs a url")
        url = entry["url"].strip()
        if not url.lower().startswith("https://"):
            raise ConfigError(f"feed URLs must use https:// ({url})")
        feeds.append(Feed(name=str(entry.get("name", url)).strip(), url=url))

    matched = _int(tiers, "matched", 75, 1, 100)
    promising = _int(tiers, "promising", 55, 1, 100)
    close = _int(tiers, "close", 35, 0, 100)
    if not matched > promising > close:
        raise ConfigError("tier thresholds must satisfy matched > promising > close")

    return Profile(
        name=str(cand.get("name", "")).strip(),
        linkedin_url=str(cand.get("linkedin_url", "")).strip(),
        seniority=seniority,
        acceptable_seniority=acceptable,
        premium=_bool(cand, "premium", False),
        target_titles=_str_list(targets, "titles"),
        target_locations=_str_list(targets, "locations"),
        remote_ok=_bool(targets, "remote_ok", False),
        exclude_title_keywords=_str_list(targets, "exclude_title_keywords"),
        skills_have=[s.lower() for s in _str_list(skills, "have")],
        skills_learning=[s.lower() for s in _str_list(skills, "learning")],
        skill_aliases=aliases,
        tier_matched=matched,
        tier_promising=promising,
        tier_close=close,
        interests=_str_list(news, "interests"),
        feeds=feeds,
        hours_per_week=_int(learning, "hours_per_week", 6, 1, 60),
        retention_days=_int(privacy, "retention_days", 90, 7, 3650),
        configured=True,
    )


def _toml_str(value: str) -> str:
    """A TOML basic string. Escapes backslash, quote and control characters."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_str_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def profile_to_toml(profile: Profile) -> str:
    """Serialize a Profile back to profile.toml, in the same section order as the template.

    This is a writer scoped to this one dataclass, not a general TOML library: the shape of
    Profile is fixed and small, so a general writer would be more code, not less. The one thing
    it cannot do that a human editor can is keep comments — every '#' in the file is lost on the
    first save from here, which is why the caller always keeps a .bak of what this replaces.
    """
    saved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    aliases_lines = "\n".join(
        f"{_toml_str(canon)} = {_toml_str_list(values)}" for canon, values in profile.skill_aliases.items()
    )
    feeds_blocks = "\n\n".join(
        f"[[news.feeds]]\nname = {_toml_str(feed.name)}\nurl = {_toml_str(feed.url)}" for feed in profile.feeds
    )
    return f"""# Written by Career Copilot Settings on {saved}.
# Comments are not preserved when this file is saved from the Console — see profile.toml.bak
# for the version before this save.

[candidate]
name = {_toml_str(profile.name)}
linkedin_url = {_toml_str(profile.linkedin_url)}
seniority = {_toml_str(profile.seniority)}
acceptable_seniority = {_toml_str_list(profile.acceptable_seniority)}
premium = {_toml_bool(profile.premium)}

[targets]
titles = {_toml_str_list(profile.target_titles)}
locations = {_toml_str_list(profile.target_locations)}
remote_ok = {_toml_bool(profile.remote_ok)}
exclude_title_keywords = {_toml_str_list(profile.exclude_title_keywords)}

[skills]
have = {_toml_str_list(profile.skills_have)}
learning = {_toml_str_list(profile.skills_learning)}

[skills.aliases]
{aliases_lines + chr(10) if aliases_lines else ""}
[tiers]
matched = {profile.tier_matched}
promising = {profile.tier_promising}
close = {profile.tier_close}

[learning]
hours_per_week = {profile.hours_per_week}

[privacy]
retention_days = {profile.retention_days}

[news]
interests = {_toml_str_list(profile.interests)}

{feeds_blocks}
""".rstrip() + "\n"
