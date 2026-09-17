"""Career path: turn missing skills across target jobs into a ranked, time-boxed learning plan."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from urllib.parse import quote_plus

from . import skills as sk
from .config import Profile
from .scoring import TIER_ORDER, score_job

TIER_WEIGHT = {"matched": 1.2, "promising": 1.0, "close": 0.8}
INACTIVE_STATUSES = {"rejected", "archived"}


def search_links(skill: str) -> dict[str, str]:
    q = quote_plus(skill)
    return {
        "coursera": f"https://www.coursera.org/search?query={q}",
        "linkedin_learning": f"https://www.linkedin.com/learning/search?keywords={q}",
        "microsoft_learn": f"https://learn.microsoft.com/en-us/training/browse/?terms={q}",
        "udemy": f"https://www.udemy.com/courses/search/?q={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}+tutorial",
    }


def aggregate_gaps(jobs: Iterable[dict]) -> list[dict]:
    """Rank skills by how often (and how strongly) they block target jobs."""
    table: dict[str, dict] = {}

    def add(skill: str, weight: float, status: str, job: dict) -> None:
        entry = table.setdefault(skill, {
            "skill": skill, "category": sk.category_of(skill), "status": status,
            "demand": 0.0, "job_ids": set(), "example_jobs": [],
        })
        entry["demand"] += weight
        if status == "learning":
            entry["status"] = "learning"
        if job["id"] not in entry["job_ids"]:
            entry["job_ids"].add(job["id"])
            if len(entry["example_jobs"]) < 3:
                label = job["title"] + (f" @ {job['company']}" if job.get("company") else "")
                entry["example_jobs"].append(label)

    for job in jobs:
        tier_weight = TIER_WEIGHT.get(job.get("tier") or "")
        if tier_weight is None or job.get("status") in INACTIVE_STATUSES:
            continue
        analysis = json.loads(job.get("analysis_json") or "{}")
        for skill in analysis.get("missing_required", []):
            add(skill, 1.0 * tier_weight, "missing", job)
        for skill in analysis.get("missing_preferred", []):
            add(skill, 0.5 * tier_weight, "missing", job)
        for skill in analysis.get("learning_skills", []):
            add(skill, 0.75 * tier_weight, "learning", job)

    ranked = []
    for entry in table.values():
        ranked.append({
            "skill": entry["skill"],
            "category": entry["category"],
            "status": entry["status"],
            "demand": round(entry["demand"], 2),
            "jobs": len(entry["job_ids"]),
            "example_jobs": entry["example_jobs"],
        })
    ranked.sort(key=lambda e: (-e["demand"], -e["jobs"], e["skill"]))
    return ranked


def tier_progression(jobs: Iterable[dict], profile: Profile, assume: set[str]) -> dict:
    """If the user had `assume` skills, which jobs would move up a tier?"""
    upgrades = []
    for job in jobs:
        if job.get("status") in INACTIVE_STATUSES or not job.get("description") or job.get("tier") == "excluded":
            continue
        after = score_job(job["title"], job["description"], job.get("location", ""), profile, assume_skills=assume)
        before_tier = job.get("tier") or "low_fit"
        if TIER_ORDER[after.tier] > TIER_ORDER.get(before_tier, 0):
            upgrades.append({
                "job_id": job["id"],
                "title": job["title"],
                "company": job.get("company", ""),
                "from": before_tier,
                "to": after.tier,
                "score": f"{job.get('score')} → {after.score}",
            })
    return {"skills": sorted(assume), "jobs_upgraded": len(upgrades), "upgrades": upgrades[:10]}


def build_plan(gaps: list[dict], courses: list[dict], weeks: int, hours_per_week: int, top: int) -> dict:
    capacity = weeks * hours_per_week
    completed = {c["skill"] for c in courses if c["status"] == "completed"}
    used = 0
    steps = []
    skipped = []
    for gap in gaps:
        if len(steps) >= top:
            break
        if gap["skill"] in completed:
            continue
        hours = sk.CATEGORY_HOURS.get(gap["category"], sk.CATEGORY_HOURS["other"])
        if used + hours > capacity:
            skipped.append(gap["skill"])
            continue
        start_week = used // hours_per_week + 1
        used += hours
        end_week = math.ceil(used / hours_per_week)
        tracked = [
            {"course_id": c["id"], "title": c["title"], "status": c["status"], "progress_pct": c["progress_pct"]}
            for c in courses if c["skill"] == gap["skill"]
        ]
        steps.append({
            "skill": gap["skill"],
            "status": gap["status"],
            "weeks": f"{start_week}" if end_week == start_week else f"{start_week}-{end_week}",
            "estimated_hours": hours,
            "why": f"blocks {gap['jobs']} target job(s), e.g. {', '.join(gap['example_jobs'][:2])}",
            "tracked_courses": tracked,
            "find_courses": search_links(gap["skill"]),
            "proof_of_skill": sk.PRACTICE_IDEAS.get(gap["category"], sk.PRACTICE_IDEAS["other"]).format(skill=gap["skill"]),
        })
    return {
        "weeks": weeks,
        "hours_per_week": hours_per_week,
        "hours_planned": used,
        "capacity_hours": capacity,
        "steps": steps,
        "did_not_fit": skipped,
        "note": "Hour estimates are rough defaults per skill category. Track real courses with add_course.",
    }
