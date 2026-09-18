"""UK Register of Licensed Sponsors — company-name matching.

Ported from the Sponsorship Oracle in cherenkov-nexus (`src/oracle/register.ts`), which exists
because a substring lookup over the register is actively misleading: `LIKE '%wise%' LIMIT 1`
against 126,998 rows returns "Aaron Wise Limited" for a query of "Wise" and reports it as fact.
An unranked `LIMIT 1` is not a match, it is the first row the query happened to reach.

So: rank every candidate, report the confidence, and refuse to pick when the leader is not
decisively ahead. A confident wrong answer about someone's immigration prospects is worse than
an honest question.

Two rules this module adds on top of the original:

* **Route is filtered before names are scored.** The register really does contain a row
  `Wise | Religious Worker | High Wycombe`, which scores a perfect 1.0 against a query of "Wise"
  and would auto-confirm. Matching it would tell someone the fintech holds a licence on the
  strength of a Buckinghamshire religious-worker licence. Only routes that can sponsor skilled
  work are considered.
* **An empty register is never "not a sponsor."** That distinction is the caller's to make, and
  `rank_candidates` returning nothing says only that nothing matched.

Everything here is pure: no database, no network. Retrieval lives in `service.py`.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Legal-form suffixes and generic corporate words, stripped for matching — but only when they
# are not the whole name, so "The Limited Company Ltd" keeps something to match on.
NOISE_TOKENS = frozenset({
    "ltd", "limited", "plc", "llp", "lp", "llc", "inc", "incorporated",
    "co", "company", "corp", "corporation", "group", "holdings", "holding",
    "uk", "gb", "the", "and", "of", "services", "service", "international",
})

# Licence routes that can sponsor skilled work. Everything else on the register — Creative
# Worker, Religious Worker, International Sportsperson, Charity Worker, Ministers of Religion,
# Seasonal Worker, Government Authorised Exchange, International Agreement — is a different
# permission entirely, and a blank route cannot be confirmed as either.
WORK_ROUTE_PREFIXES = ("skilled worker", "global business mobility", "scale up", "intra company")

# Set high on purpose: an unnecessary confirmation costs one click, a wrong sponsor costs the
# whole answer.
AUTO_CONFIRM_SCORE = 0.95
# Below this a candidate is not worth showing at all.
MIN_CANDIDATE_SCORE = 0.34
# How far ahead the leader must be before it is treated as unambiguous.
DECISIVE_GAP = 0.10

_CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("organisation name", "organisation", "name", "sponsor"),
    "town": ("town/city", "town", "city"),
    "county": ("county", "region"),
    "type_rating": ("type & rating", "type and rating", "type", "rating"),
    "route": ("sub category (where applicable)", "sub-category", "sub category", "route", "sponsor route"),
}


@dataclass(frozen=True)
class SponsorCandidate:
    name: str
    route: str
    type_rating: str
    town: str
    county: str
    score: float
    basis: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "route": self.route,
            "type_rating": self.type_rating,
            "town": self.town,
            "county": self.county,
            "score": round(self.score, 3),
            "basis": self.basis,
        }


def normalise_name(raw: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", raw or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = stripped.lower().replace("&", " and ")
    return " ".join("".join(c if c.isalnum() else " " for c in lowered).split())


def core_name(raw: str) -> str:
    """Normalised name with legal-form noise removed, falling back if that empties it."""
    tokens = normalise_name(raw).split()
    kept = [t for t in tokens if t not in NOISE_TOKENS]
    return " ".join(kept or tokens)


def is_work_route(route: str) -> bool:
    return normalise_name(route).startswith(WORK_ROUTE_PREFIXES)


def _core_leads(q_norm: str, c_norm: str, core: str) -> bool:
    """True when the shared core sits at the front of both names.

    Stripping noise can promote a token out of the middle of a name: "UK Wise Group Ltd" reduces
    to "wise", which then matches a query of "Wise" exactly and would auto-confirm the wrong
    company. A company's distinctive word leads its name ("Google UK Limited", "Monzo Bank Ltd");
    when it has to be excavated from the middle, the equal cores are an artefact of stripping and
    the match has to be earned on the weaker tiers instead.
    """
    return ((q_norm == core or q_norm.startswith(f"{core} "))
            and (c_norm == core or c_norm.startswith(f"{core} ")))


def score_match(query: str, candidate: str) -> tuple[float, str]:
    """Score 0–1 that `candidate` is the company `query` names, with the basis for it."""
    q_norm, c_norm = normalise_name(query), normalise_name(candidate)
    if not q_norm or not c_norm:
        return 0.0, "tokens"
    if q_norm == c_norm:
        return 1.0, "exact"

    q_core, c_core = core_name(query), core_name(candidate)
    if q_core == c_core and _core_leads(q_norm, c_norm, q_core):
        return 0.97, "normalised"

    q_tokens, c_tokens = q_core.split(), c_core.split()
    if not q_tokens or not c_tokens:
        return 0.0, "tokens"

    # Prefix on a token boundary: "wise" scores well against "wise payments", and not at all
    # against "aaron wise". This is the case that fixes the original defect.
    if c_core.startswith(f"{q_core} ") or q_core.startswith(f"{c_core} "):
        shorter, longer = min(len(q_tokens), len(c_tokens)), max(len(q_tokens), len(c_tokens))
        return 0.7 + 0.25 * (shorter / longer), "prefix"

    overlap = set(q_tokens) & set(c_tokens)
    if not overlap:
        return 0.0, "tokens"
    jaccard = len(overlap) / len(set(q_tokens) | set(c_tokens))
    # A single short shared token is how unrelated companies collide.
    weak = len(overlap) == 1 and len(next(iter(overlap))) <= 4
    return jaccard * (0.5 if weak else 0.9), "tokens"


def rank_candidates(query: str, rows: list[dict], limit: int = 6) -> list[SponsorCandidate]:
    """Rank register rows against a company name, best first.

    `rows` carry `name`, and optionally `route`, `type_rating`, `town`, `county`. Rows on a
    route that cannot sponsor skilled work are dropped before scoring, never after.
    """
    query = (query or "").strip()
    # An empty or one-character company name has no honest answer; the original matched
    # `LIKE '%%'` and reported whatever row came first as a verified sponsor.
    if len(query) < 2 or not core_name(query):
        return []

    scored: list[SponsorCandidate] = []
    for row in rows:
        route = (row.get("route") or "").strip()
        if not is_work_route(route):
            continue
        name = (row.get("name") or "").strip()
        score, basis = score_match(query, name)
        if score < MIN_CANDIDATE_SCORE:
            continue
        scored.append(SponsorCandidate(
            name=name,
            route=route,
            type_rating=(row.get("type_rating") or "").strip(),
            town=(row.get("town") or "").strip(),
            county=(row.get("county") or "").strip(),
            score=score,
            basis=basis,
        ))
    scored.sort(key=lambda c: (-c.score, c.name))
    return scored[:limit]


def decide(candidates: list[SponsorCandidate]) -> tuple[SponsorCandidate | None, bool]:
    """Pick the match only when it is unambiguous. Returns (confirmed, needs_confirmation)."""
    if not candidates:
        return None, False
    top = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None

    # A character-exact match is the strongest signal there is, and confirming it buys no
    # safety — unless two rows match exactly, which is a real ambiguity only a person can settle.
    exactly_one = top.score >= 1.0 and (runner_up is None or runner_up.score < 1.0)
    decisive = exactly_one or (
        top.score >= AUTO_CONFIRM_SCORE
        and (runner_up is None or top.score - runner_up.score >= DECISIVE_GAP)
    )
    return (top if decisive else None), not decisive


def _resolve_columns(header: list[str]) -> dict[str, str]:
    seen = {" ".join((h or "").lower().split()): h for h in header}
    resolved = {}
    for field, aliases in _CSV_COLUMNS.items():
        for alias in aliases:
            if alias in seen:
                resolved[field] = seen[alias]
                break
    return resolved


def parse_register_csv(path: Path) -> tuple[list[dict], dict]:
    """Read the gov.uk register CSV into rows, plus a report of how its columns were read.

    Column names have changed across gov.uk publications, so each field accepts several
    spellings. Only the organisation name is required.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _resolve_columns(list(reader.fieldnames or []))
        if "name" not in columns:
            raise ValueError(
                "could not find an organisation-name column in this CSV; "
                f"columns seen: {', '.join(reader.fieldnames or []) or 'none'}"
            )
        rows, skipped = [], 0
        for record in reader:
            name = (record.get(columns["name"]) or "").strip()
            if not name:
                skipped += 1
                continue
            rows.append({
                field: (record.get(column) or "").strip()
                for field, column in columns.items()
            })
    report = {
        "columns": columns,
        "rows": len(rows),
        "skipped_without_name": skipped,
        "work_route_rows": sum(1 for r in rows if is_work_route(r.get("route", ""))),
    }
    return rows, report
