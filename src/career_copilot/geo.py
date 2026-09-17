"""Location normalisation for GCC and Egypt job markets (extend as needed)."""

from __future__ import annotations

import re

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "united arab emirates": ("uae", "u.a.e", "dubai", "abu dhabi", "sharjah", "ajman",
                             "ras al khaimah", "fujairah", "al ain"),
    "saudi arabia": ("ksa", "saudi", "riyadh", "jeddah", "dammam", "khobar", "al khobar", "dhahran",
                     "neom", "makkah", "mecca", "madinah", "medina"),
    "qatar": ("doha", "lusail"),
    "kuwait": ("kuwait city",),
    "bahrain": ("manama",),
    "oman": ("muscat", "sohar"),
    "egypt": ("cairo", "new cairo", "giza", "alexandria", "6th of october", "sheikh zayed",
              "new administrative capital", "smart village"),
}

REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.I)
REMOTE_STRONG = re.compile(r"\b(fully remote|100% remote|remote[- ]first|work from anywhere|this is a remote)\b", re.I)
LOCATION_HINT = re.compile(r"\b(remote|hybrid|on-site|onsite)\b", re.I)


def _contains(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack) is not None


def countries_in(text: str) -> set[str]:
    lowered = text.lower()
    found = set()
    for country, aliases in COUNTRY_ALIASES.items():
        if _contains(lowered, country) or any(_contains(lowered, alias) for alias in aliases):
            found.add(country)
    return found


def looks_like_location(text: str) -> bool:
    return bool(LOCATION_HINT.search(text) or countries_in(text) or REMOTE.search(text))


def is_remote(location: str, title: str, description: str) -> bool:
    return bool(REMOTE.search(location) or REMOTE.search(title) or REMOTE_STRONG.search(description or ""))
