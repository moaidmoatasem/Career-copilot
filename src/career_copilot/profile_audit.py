"""Profile audit: deterministic checks that point at concrete, verifiable improvements."""

from __future__ import annotations

import re

from . import skills as sk
from .config import LIMITS, Profile
from .export import parse_month_year
from .scoring import _ROLE_FAMILY, _title_tokens, profile_skill_sets

_DIGITS = re.compile(r"\d")
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _role_keyword_present(text: str, profile: Profile) -> bool:
    tokens = _title_tokens(text)
    if tokens & _ROLE_FAMILY:
        return True
    target_tokens = set()
    for title in profile.target_titles:
        target_tokens |= _title_tokens(title)
    target_tokens -= {"engineer"}
    return bool(tokens & target_tokens)


def _overlaps(positions: list[dict]) -> list[str]:
    spans = []
    for p in positions:
        start = parse_month_year(p.get("started_on", ""))
        if not start:
            continue
        end = parse_month_year(p.get("finished_on", "")) or (9999, 12)
        spans.append((start, end, f"{p.get('title', '')} @ {p.get('company', '')}".strip(" @")))
    found = []
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            (s1, e1, a), (s2, e2, b) = spans[i], spans[j]
            if s1 < e2 and s2 < e1:
                found.append(f"{a} ↔ {b}")
    return found


def audit_profile(snapshot: dict, profile: Profile, demand: list[str]) -> dict:
    findings: list[dict] = []

    def add(severity: str, section: str, finding: str, suggestion: str) -> None:
        findings.append({"severity": severity, "section": section, "finding": finding, "suggestion": suggestion})

    have, _, extra = profile_skill_sets(profile)
    top_demand = demand[:10]
    headline = (snapshot.get("headline") or "").strip()
    about = (snapshot.get("about") or "").strip()
    positions = snapshot.get("positions") or []
    listed_skills = {sk.canonicalize(s, extra) for s in snapshot.get("skills") or []}

    if not headline:
        add("high", "headline", "No headline available.", "Import your LinkedIn data export or pass the headline text.")
    else:
        if len(headline) > LIMITS["headline"]:
            add("high", "headline", f"Headline is {len(headline)} characters (limit {LIMITS['headline']}).", "Shorten it.")
        elif len(headline) < 60:
            add("medium", "headline", "Headline is short and leaves search keywords unused.",
                "State your target role and two or three core skills you genuinely use.")
        if not _role_keyword_present(headline, profile):
            add("high", "headline", "Headline doesn't name the role recruiters search for.",
                f"Lead with a target title such as '{profile.target_titles[0]}'." if profile.target_titles
                else "Lead with your target job title.")
        in_headline = sk.extract_skills(headline, extra)
        candidates = [s for s in top_demand if s in have and s not in in_headline][:3]
        if len(in_headline & set(top_demand)) < 2 and candidates:
            add("medium", "headline", "Few in-demand skills from your target jobs appear in the headline.",
                f"Consider adding: {', '.join(candidates)} (only skills you can back up in an interview).")

    if not about:
        add("high", "about", "No About section available.", "Import your data export or pass the About text.")
    else:
        if len(about) > LIMITS["about"]:
            add("high", "about", f"About is {len(about)} characters (limit {LIMITS['about']}).", "Trim it.")
        elif len(about) < 800:
            add("medium", "about", "About section is brief.",
                "Expand it with the problems you solve, the systems you've tested, and what you're looking for next.")
        if not _role_keyword_present(about[:300], profile):
            add("medium", "about", "Your role isn't clear in the first lines (the part shown before 'see more').",
                "Open with who you are professionally and the role you're targeting.")
        missing_in_about = [s for s in top_demand if s in have and s not in sk.extract_skills(about, extra)][:5]
        if missing_in_about:
            add("low", "about", "In-demand skills you have aren't mentioned.", f"Weave in: {', '.join(missing_in_about)}.")

    text_with_numbers = about + " ".join(p.get("description", "") for p in positions)
    if (about or positions) and not _DIGITS.search(text_with_numbers):
        add("low", "experience", "No concrete results anywhere (counts, scope, scale).",
            "Add results you can trace to a source (e.g. suites automated, services covered, releases supported). "
            "Leave out estimates you can't verify.")

    if not positions:
        add("high", "experience", "No positions available.", "Import your LinkedIn data export.")
    else:
        for index, position in enumerate(positions):
            description = position.get("description", "")
            label = f"{position.get('title', '')} @ {position.get('company', '')}"
            if len(description) > LIMITS["position_description"]:
                add("high", f"experience:{index}", f"{label}: description is {len(description)} characters "
                    f"(limit {LIMITS['position_description']}).", "Shorten it.")
            if index < 3 and not description.strip():
                add("medium", f"experience:{index}", f"{label}: no description.",
                    "Add two to four lines on scope, tools and verifiable outcomes.")
        for pair in _overlaps(positions):
            add("info", "experience", f"Overlapping dates: {pair}.",
                "Fine for genuinely concurrent roles; otherwise correct the dates so they match your CV.")

    if not listed_skills:
        add("medium", "skills", "No skills listed (or export not imported).", "Add the core skills from your target jobs.")
    else:
        to_add = [s for s in top_demand if s in have and s not in listed_skills]
        if to_add:
            add("medium", "skills", "In-demand skills you have aren't in your Skills section.",
                f"Add: {', '.join(to_add)}.")

    findings.sort(key=lambda f: _SEVERITY_ORDER[f["severity"]])
    counts = {level: sum(1 for f in findings if f["severity"] == level) for level in _SEVERITY_ORDER}
    return {
        "summary": counts,
        "findings": findings,
        "demand_skills": top_demand,
        "note": "Demand skills come from jobs stored in the copilot. More jobs with descriptions → better signal.",
    }
