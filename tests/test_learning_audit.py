from conftest import CLOSE_DESCRIPTION, MATCHED_DESCRIPTION
from test_export import make_export


def _jobs(cp):
    matched = cp.add_job("Senior QA Automation Engineer", "Acme", "Dubai, United Arab Emirates", description=MATCHED_DESCRIPTION)
    close = cp.add_job("Senior QA Engineer", "Globex", "Cairo, Egypt", description=CLOSE_DESCRIPTION)
    return matched, close


def test_gaps_plan_and_tier_progression(cp):
    matched, close = _jobs(cp)
    assert matched["tier"] == "matched" and close["tier"] == "close"

    gaps = {g["skill"]: g for g in cp.skill_gaps()["gaps"]}
    assert {"java", "selenium", "jmeter", "kubernetes"} <= set(gaps)
    assert "coursera" in gaps["java"]["find_courses"]

    plan = cp.learning_plan(weeks=12, hours_per_week=6)
    planned = [step["skill"] for step in plan["steps"]]
    assert planned == ["llm", "java"]  # llm is already being learned and blocks both jobs
    assert {"jmeter", "selenium", "kubernetes"} <= set(plan["did_not_fit"])
    assert plan["hours_planned"] <= plan["capacity_hours"]
    progression = plan["if_you_complete_the_plan"]
    assert progression["jobs_upgraded"] == 1
    assert progression["upgrades"][0]["from"] == "close"


def test_completed_courses_leave_the_plan(cp):
    _jobs(cp)
    course = cp.add_course("java", "Java for Testers", "Coursera")
    updated = cp.update_course(course["course_id"], progress_pct=100)
    assert updated["status"] == "completed" and "tip" in updated
    assert "java" not in [step["skill"] for step in cp.learning_plan()["steps"]]


def test_profile_changes_trigger_rescoring(cp, home):
    _, close = _jobs(cp)
    profile = home / "profile.toml"
    text = profile.read_text().replace('"docker"]', '"docker", "java", "selenium", "jmeter"]')
    profile.write_text(text)
    import os
    os.utime(profile, (profile.stat().st_atime + 5, profile.stat().st_mtime + 5))
    assert cp.get_job(close["id"])["tier"] == "matched"


def test_profile_audit_findings(cp):
    _jobs(cp)
    make_export(cp.imports_dir)
    cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    report = cp.audit_profile()
    findings = {(f["section"], f["severity"]) for f in report["findings"]}
    assert ("headline", "medium") in findings
    assert ("about", "medium") in findings
    assert any(f["severity"] == "info" and "Overlapping" in f["finding"] for f in report["findings"])
    skills = [f for f in report["findings"] if f["section"] == "skills"]
    assert skills and "playwright" in skills[0]["suggestion"]

    long_headline = cp.audit_profile(headline="QA " * 80)
    assert any(f["severity"] == "high" and "limit 220" in f["finding"] for f in long_headline["findings"])


def test_retention_sweep_removes_old_items(cp):
    cp.store.execute(
        "INSERT INTO inbox_items(dedupe_key, source, kind, sender, received_at, created_at, updated_at) "
        "VALUES ('old', 'email', 'message', 'x', '2020-01-01T00:00:00+00:00', '2020-01-01', '2020-01-01')"
    )
    result = cp.sweep_expired()
    assert result["inbox_items_deleted"] == 1
