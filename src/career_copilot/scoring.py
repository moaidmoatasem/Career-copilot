"""Deterministic job-fit scoring. Every score comes with the reasons behind it.

Weights (with a job description):  skills 50% · title 25% · level 15% · location 10%,
plus minimum skill coverage per tier (matched 70%, promising 45%, close 25%).
Weights (title-only, e.g. from a job alert email): title 55% · level 25% · location 20%,
and the tier is capped at "promising" until the full description is added.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field

from . import geo
from . import skills as sk
from .config import SENIORITY_RANK, Profile

TIER_ORDER = {"excluded": -1, "low_fit": 0, "close": 1, "promising": 2, "matched": 3}

_LEVEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(intern|internship|trainee)\b", re.I)),
    ("director", re.compile(r"\b(director|vice president|vp)\b", re.I)),
    ("head", re.compile(r"\bhead\b", re.I)),
    ("principal", re.compile(r"\b(principal|staff|architect|distinguished)\b", re.I)),
    ("manager", re.compile(r"\bmanager\b", re.I)),
    ("lead", re.compile(r"\b(lead|leader)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr|entry[- ]level|graduate)\b", re.I)),
    ("mid", re.compile(r"\b(mid[- ]level|intermediate)\b", re.I)),
]
_YEARS = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?\b", re.I)

_TITLE_SYNONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"software development engineer in test|software engineer in test|\bsdet\b", re.I), " sdet "),
    (re.compile(r"quality assurance|quality engineering|quality control|\bqc\b|\bqe\b|\bquality\b", re.I), " qa "),
    (re.compile(r"test automation|automation testing|automation test|automated testing|\bautomation\b", re.I), " automation "),
    (re.compile(r"\b(testing|tester|test)\b", re.I), " test "),
    (re.compile(r"\b(engineering|engineer|specialist|analyst|developer)\b", re.I), " engineer "),
]
_TITLE_NOISE = {
    "senior", "sr", "junior", "jr", "lead", "leader", "principal", "staff", "head", "of", "the", "and",
    "i", "ii", "iii", "iv", "mid", "level", "intermediate", "associate", "manager", "it", "software",
    "team", "a", "an", "for", "in", "remote", "hybrid",
}
_ROLE_FAMILY = {"qa", "sdet", "test", "automation"}


@dataclass
class FitResult:
    score: int
    tier: str
    confidence: str
    level: str
    best_title_match: str
    breakdown: dict[str, float] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    learning_skills: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_preferred: list[str] = field(default_factory=list)
    alternatives: dict[str, list[str]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def profile_skill_sets(profile: Profile) -> tuple[set[str], set[str], dict[str, list[str]]]:
    extra = {k: list(v) for k, v in profile.skill_aliases.items()}
    have = sk.expand_implied({sk.canonicalize(s, extra) for s in profile.skills_have})
    learning = sk.expand_implied({sk.canonicalize(s, extra) for s in profile.skills_learning}) - have
    for skill in have | learning:
        if skill not in sk.TAXONOMY and skill not in extra:
            extra[skill] = [skill]
    return have, learning, extra


def _title_tokens(title: str) -> set[str]:
    text = title.lower()
    for pattern, replacement in _TITLE_SYNONYMS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[^a-z0-9#+ ]+", " ", text)
    return {t for t in text.split() if t not in _TITLE_NOISE}


def title_similarity(title: str, targets: list[str]) -> tuple[float, str]:
    job_tokens = _title_tokens(title)
    if not job_tokens or not targets:
        return (0.5 if not targets else 0.0), ""
    best, best_target = 0.0, ""
    for target in targets:
        tokens = _title_tokens(target)
        if not tokens:
            continue
        jaccard = len(job_tokens & tokens) / len(job_tokens | tokens)
        ratio = difflib.SequenceMatcher(None, " ".join(sorted(job_tokens)), " ".join(sorted(tokens))).ratio()
        score = 0.6 * jaccard + 0.4 * ratio
        if job_tokens & _ROLE_FAMILY and tokens & _ROLE_FAMILY:
            score = max(score, 0.5)
        if score > best:
            best, best_target = score, target
    if not job_tokens & _ROLE_FAMILY:
        best = min(best, 0.35)
    return round(best, 3), best_target


def detect_level(title: str, description: str) -> tuple[str, str]:
    for level, pattern in _LEVEL_PATTERNS:
        if pattern.search(title):
            return level, "title"
    match = _YEARS.search(description or "")
    if match:
        years = int(match.group(1))
        if years <= 1:
            level = "junior"
        elif years <= 4:
            level = "mid"
        elif years <= 7:
            level = "senior"
        elif years <= 11:
            level = "lead"
        else:
            level = "principal"
        return level, f"asks for {years}+ years"
    return "mid", "no level stated"


def seniority_fit(level: str, profile: Profile) -> float:
    if level in set(profile.acceptable_seniority) | {profile.seniority}:
        return 1.0
    diff = SENIORITY_RANK[level] - SENIORITY_RANK[profile.seniority]
    if diff == 0:
        return 1.0
    return {1: 0.75, -1: 0.8, 2: 0.45, -2: 0.5}.get(diff, 0.2)


def location_fit(location: str, title: str, description: str, profile: Profile) -> tuple[float, str]:
    if geo.is_remote(location, title, description):
        if profile.remote_ok:
            return 1.0, "remote role (you accept remote)"
        return 0.5, "remote role (remote_ok is off in your profile)"
    if not profile.target_locations:
        return 0.7, "no target locations configured"
    if not location.strip():
        return 0.6, "location not stated"
    targets = set()
    for target in profile.target_locations:
        targets |= geo.countries_in(target)
    job_countries = geo.countries_in(location)
    lowered = location.lower()
    if job_countries & targets or any(t.lower() in lowered for t in profile.target_locations):
        where = ", ".join(sorted(job_countries & targets)) or location
        return 1.0, f"in a target location ({where})"
    return 0.25, f"outside your target locations ({location})"


# Minimum weighted skill coverage per tier, so a perfect title/level/location can't hide missing skills.
COVERAGE_GATES = {"matched": 0.70, "promising": 0.45, "close": 0.25}


def tier_for(score: int, profile: Profile, coverage: float | None = None) -> str:
    thresholds = (("matched", profile.tier_matched), ("promising", profile.tier_promising), ("close", profile.tier_close))
    for tier, threshold in thresholds:
        if score >= threshold and (coverage is None or coverage >= COVERAGE_GATES[tier]):
            return tier
    return "low_fit"


def score_job(
    title: str,
    description: str,
    location: str,
    profile: Profile,
    assume_skills: set[str] | None = None,
) -> FitResult:
    """Score one job. `assume_skills` answers "what if I learned these?" for career planning."""
    have, learning, extra = profile_skill_sets(profile)
    if assume_skills:
        have |= sk.expand_implied(set(assume_skills))
        learning -= have

    lowered_title = (title or "").lower()
    for keyword in profile.exclude_title_keywords:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", lowered_title):
            return FitResult(
                score=0, tier="excluded", confidence="high", level="", best_title_match="",
                reasons=[f"title contains excluded keyword '{keyword}'"],
            )

    title_score, best_title = title_similarity(title, profile.target_titles)
    level, level_basis = detect_level(title, description)
    level_score = seniority_fit(level, profile)
    location_score, location_reason = location_fit(location, title, description, profile)

    weights, groups, standalone = sk.job_requirements(title, description, extra)
    relevant = {s: w for s, w in weights.items() if w >= sk.WEIGHT_PREFERRED}
    has_description = len((description or "").strip()) >= 200

    # Requirement units: a single skill, or a set of alternatives where any one satisfies it.
    units: list[tuple[frozenset[str], float]] = []
    grouped: set[str] = set()
    optional: set[str] = set()
    for group in {frozenset(g & relevant.keys()) for g in groups}:
        if len(group) < 2:
            continue
        if group & standalone:  # one option is also required on its own elsewhere in the post
            optional |= group - standalone
            continue
        units.append((group, max(relevant[s] for s in group)))
        grouped |= group
    for skill, weight in relevant.items():
        if skill not in grouped and skill not in optional:
            units.append((frozenset([skill]), weight))

    def credit_for(skill: str) -> float:
        return 1.0 if skill in have else 0.5 if skill in learning else 0.0

    reasons = [
        f"title ≈ '{best_title}' ({title_score:.2f})" if best_title else f"title similarity {title_score:.2f}",
        f"level: {level} ({level_basis}) → fit {level_score:.2f}",
        location_reason,
    ]
    breakdown = {"title": title_score, "level": level_score, "location": location_score}

    if has_description and units:
        total_weight = sum(w for _, w in units)
        credit = sum(w * max(credit_for(s) for s in unit) for unit, w in units)
        skill_score = credit / total_weight
        breakdown["skills"] = round(skill_score, 3)
        total = 0.50 * skill_score + 0.25 * title_score + 0.15 * level_score + 0.10 * location_score
        confidence = "high" if len(description) >= 600 and len(units) >= 4 else "medium"
    else:
        total = 0.55 * title_score + 0.25 * level_score + 0.20 * location_score
        confidence = "low"

    score = round(total * 100)
    coverage = breakdown.get("skills")
    tier = tier_for(score, profile, coverage)
    ungated = tier_for(score, profile)
    if coverage is not None and tier != ungated:
        reasons.append(
            f"tier limited by skill coverage ({coverage:.0%} < {COVERAGE_GATES[ungated]:.0%} needed for '{ungated}')"
        )
    if confidence == "low" and tier == "matched":
        tier = "promising"
        reasons.append("capped at 'promising' until the full job description is added")

    matched = sorted({s for unit, _ in units for s in unit if s in have})
    in_progress = sorted({s for unit, _ in units for s in unit if s in learning})
    missing: list[tuple[str, float]] = []
    alternatives: dict[str, list[str]] = {}
    for unit, weight in units:
        if max(credit_for(s) for s in unit) > 0:
            continue
        # for alternatives, suggest the quickest one to learn
        pick = min(unit, key=lambda s: (sk.CATEGORY_HOURS.get(sk.category_of(s), 15), s))
        missing.append((pick, weight))
        if len(unit) > 1:
            alternatives[pick] = sorted(unit - {pick})
    missing_required = [s for s, w in sorted(missing, key=lambda x: (-x[1], x[0])) if w >= sk.WEIGHT_NEUTRAL]
    missing_preferred = sorted(s for s, w in missing if w < sk.WEIGHT_NEUTRAL)

    if confidence == "low" and has_description:
        reasons.append("description has no recognised skills: add aliases under [skills.aliases] if this looks wrong")
    elif confidence == "low":
        reasons.append("no full job description yet: add it with update_job for a skills-based score")
    else:
        reasons.append(
            f"skills: {len(matched)} matched, {len(in_progress)} in progress, "
            f"{len(missing_required)} missing required (coverage {breakdown['skills']:.0%})"
        )

    return FitResult(
        score=score,
        tier=tier,
        confidence=confidence,
        level=level,
        best_title_match=best_title,
        breakdown=breakdown,
        matched_skills=matched,
        learning_skills=in_progress,
        missing_required=missing_required,
        missing_preferred=missing_preferred,
        alternatives=alternatives,
        reasons=reasons,
    )
