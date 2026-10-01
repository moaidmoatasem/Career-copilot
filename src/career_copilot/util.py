"""Small shared helpers: time, hashing, URLs, company names."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_utc_iso(value: str | None) -> str:
    """Normalise ISO-8601 or RFC 2822 (email Date header) timestamps to UTC ISO; fall back to now."""
    if not value or not value.strip():
        return utcnow()
    raw = value.strip()
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            dt = None
    if dt is None:
        return utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Digest a file without holding it in memory — register CSVs run to tens of megabytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(text: str, length: int = 16) -> str:
    return sha256(text)[:length]


def restrict_file(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:  # e.g. Windows or unusual filesystems
        pass


def strip_query(url: str) -> str:
    """Drop query string and fragment (removes tracking parameters)."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme or "https", parts.netloc.lower(), parts.path, "", ""))


_LEGAL_SUFFIXES = {
    "llc", "ltd", "limited", "inc", "corp", "corporation", "co", "company", "plc", "gmbh", "bv",
    "sa", "ag", "sae", "fz", "fze", "fzco", "fzllc", "dmcc", "wll", "spc", "pjsc", "psc", "jsc",
    "group", "holding", "holdings", "the",
}
_GENERIC_COMPANY_WORDS = {
    "egypt", "uae", "ksa", "saudi", "arabia", "qatar", "kuwait", "oman", "bahrain", "emirates",
    "middle", "east", "mena", "gulf", "international", "global", "solutions", "technologies",
    "technology", "services", "systems", "digital", "consulting", "and",
}


# One employer, many names. Keys are canonical company keys; each alias is matched after
# company_key() normalisation, either whole or with generic words (such as "uae") removed.
COMPANY_ALIASES: dict[str, list[str]] = {
    "e&": ["etisalat", "etisalat by e&", "emirates telecommunications", "emirates telecommunications group"],
}


def _normalise_company(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    # An ampersand inside a name ("e&", "at&t") is part of it; a standalone "&" means "and".
    text = re.sub(r"[^a-z0-9& ]+", " ", text.replace("fz-llc", "fzllc"))
    text = re.sub(r"(?<![a-z0-9])&(?![a-z0-9])", " ", text)
    return " ".join(t for t in text.split() if t not in _LEGAL_SUFFIXES)


_ALIAS_INDEX: dict[str, str] = {
    _normalise_company(alias): canonical
    for canonical, aliases in COMPANY_ALIASES.items()
    for alias in [canonical, *aliases]
}


def company_key(name: str) -> str:
    key = _normalise_company(name)
    distinctive = " ".join(t for t in key.split() if t not in _GENERIC_COMPANY_WORDS)
    return _ALIAS_INDEX.get(key) or _ALIAS_INDEX.get(distinctive) or key


def company_tokens(name: str) -> set[str]:
    return {t for t in company_key(name).split() if t not in _GENERIC_COMPANY_WORDS and (len(t) > 1 or "&" in t)}


def companies_match(a: str, b: str) -> bool:
    ta, tb = company_tokens(a), company_tokens(b)
    if not ta or not tb:
        # Nothing distinctive left (e.g. "Emirates"): only an exact normalised match counts.
        ka, kb = company_key(a), company_key(b)
        return bool(ka) and ka == kb
    return ta <= tb or tb <= ta
