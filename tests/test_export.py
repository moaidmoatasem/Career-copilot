import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from conftest import MATCHED_DESCRIPTION

from career_copilot.service import CopilotError


def _date(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S UTC")


def _saved(days_ago: int) -> str:
    """LinkedIn writes saved dates as M/D/YY, h:mm AM — built by hand so it holds on Windows too."""
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return f"{when.month}/{when.day}/{when:%y}, 9:15 AM"


def make_export(folder, name="Complete_LinkedInDataExport.zip", extra=None):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    files = {
        "Profile.csv": (
            "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,"
            "Twitter Handles,Websites,Instant Messengers\n"
            'Test,User,,,,QA person,Short summary about testing.,,,"Cairo, Egypt",,,\n'
        ),
        "Positions.csv": (
            "Company Name,Title,Description,Location,Started On,Finished On\n"
            "Globex,Senior QA Engineer,Automated API tests,Cairo,Aug 2025,\n"
            "Initech,QA Engineer,,Cairo,Mar 2021,Oct 2025\n"
        ),
        "Skills.csv": "Name\nPython\nSelenium\n",
        "messages.csv": (
            "CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,RECIPIENT PROFILE URLS,DATE,SUBJECT,"
            "CONTENT,FOLDER,IS MESSAGE DRAFT\n"
            f'conv-1,,Sara Ahmed,https://www.linkedin.com/in/sara-ahmed,Test User,https://www.linkedin.com/in/test-user,{_date(2)},,"Hi, are you open to a QA Lead role in Riyadh?",INBOX,No\n'
            f'conv-2,,Omar Khaled,https://www.linkedin.com/in/omar,Test User,https://www.linkedin.com/in/test-user,{_date(3)},,"Great to connect!",INBOX,No\n'
            f'conv-2,,Test User,https://www.linkedin.com/in/test-user,Omar Khaled,https://www.linkedin.com/in/omar,{_date(2)},,"Thanks Omar, talk soon",INBOX,No\n'
            f'conv-3,,Old Contact,https://www.linkedin.com/in/old,Test User,https://www.linkedin.com/in/test-user,{_date(200)},,"Long ago",INBOX,No\n'
        ),
        "Connections.csv": (
            "Notes:\n"
            '"When exporting your connection data, you may notice that some of the email addresses are missing."\n'
            "\n"
            "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
            "Nour,Hassan,https://www.linkedin.com/in/nour-hassan,nour@example.com,Globex Telecom LLC,QA Manager,01 Feb 2024\n"
            "Ali,Mostafa,https://www.linkedin.com/in/ali-m,,Initech,Developer,03 Mar 2023\n"
        ),
    }
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in files.items():
            archive.writestr(f"Complete_LinkedInDataExport/{filename}", content)
    return path


def test_import_export_minimises_and_finds_replies(cp):
    make_export(cp.imports_dir)
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["positions"] == 2 and summary["skills"] == 2
    assert summary["conversations_awaiting_reply"] == 1
    assert summary["connections"] == 2

    items = cp.list_inbox()["items"]
    assert len(items) == 1
    assert items[0]["sender"] == "Sara Ahmed" and items[0]["status"] == "needs_reply"

    stored = cp.store.query("SELECT * FROM connections")
    assert all("@" not in value for row in stored for value in map(str, row.values()))


def test_referrals_match_company_names(cp):
    make_export(cp.imports_dir)
    cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    job = cp.add_job("Senior QA Engineer", company="Globex Telecom", location="Dubai")
    referrals = cp.find_referrals(job["id"])
    assert [c["name"] for c in referrals["connections"]] == ["Nour Hassan"]


@pytest.mark.parametrize("name", ["../outside.zip", "/etc/passwd", "sub/../../x.zip"])
def test_imports_are_confined_to_imports_folder(cp, name):
    with pytest.raises(CopilotError):
        cp.import_linkedin_export(name)


SAVED_JOBS_HEADER = "Saved Date,Job Url,Job Title,Company Name\n"


def test_saved_jobs_are_imported_and_scored(cp):
    make_export(cp.imports_dir, extra={
        "Jobs/Saved Jobs.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(10)}",http://www.linkedin.com/jobs/view/4180272490,Senior QA Engineer,Globex\n'
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["saved_jobs_read"] == 1 and summary["saved_jobs_added"] == 1

    jobs = cp.list_jobs()["jobs"]
    assert [j["title"] for j in jobs] == ["Senior QA Engineer"]
    # No description in the export, so the job cannot climb past "promising".
    assert jobs[0]["tier"] == "promising"
    stored = cp.store.one("SELECT * FROM jobs WHERE id = ?", (jobs[0]["id"],))
    assert stored["source"] == "linkedin" and stored["external_id"] == "4180272490"
    assert stored["url"] == "https://www.linkedin.com/jobs/view/4180272490/"
    assert "Saved on LinkedIn" in stored["notes"]


def test_saved_jobs_read_every_shard_and_dedupe(cp):
    make_export(cp.imports_dir, extra={
        "Jobs/Saved Jobs.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(5)}",http://www.linkedin.com/jobs/view/111111111,QA Lead,Globex\n'
        ),
        "Jobs/Saved Jobs_1.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(6)}",http://www.linkedin.com/jobs/view/222222222,Test Automation Engineer,Initech\n'
            f'"{_saved(7)}",http://www.linkedin.com/jobs/view/111111111,QA Lead,Globex\n'
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["saved_jobs_read"] == 2 and summary["saved_jobs_added"] == 2
    assert len(cp.list_jobs()["jobs"]) == 2


def test_saved_jobs_outside_the_window_and_without_titles_are_counted_not_imported(cp):
    make_export(cp.imports_dir, extra={
        "Jobs/Saved Jobs.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(20)}",http://www.linkedin.com/jobs/view/333333333,QA Lead,Globex\n'
            f'"{_saved(900)}",http://www.linkedin.com/jobs/view/444444444,Old Role,Initech\n'
            # LinkedIn blanks the title of a saved job whose posting has been taken down.
            f'"{_saved(30)}",http://www.linkedin.com/jobs/view/555555555,,\n'
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["saved_jobs_read"] == 1
    assert summary["saved_jobs_older_than_window"] == 1
    assert summary["saved_jobs_no_longer_posted"] == 1
    assert [j["title"] for j in cp.list_jobs()["jobs"]] == ["QA Lead"]


def test_saved_jobs_days_widens_the_window(cp):
    make_export(cp.imports_dir, extra={
        "Jobs/Saved Jobs.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(900)}",http://www.linkedin.com/jobs/view/444444444,Old Role,Initech\n'
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip", saved_jobs_days=2000)
    assert summary["saved_jobs_read"] == 1 and summary["saved_jobs_older_than_window"] == 0


def test_saved_job_merges_with_the_same_job_from_an_alert_email(cp):
    existing = cp.add_job(
        "Senior QA Engineer", company="Globex", location="Dubai",
        url="https://www.linkedin.com/jobs/view/4180272490/", description=MATCHED_DESCRIPTION,
    )
    make_export(cp.imports_dir, extra={
        "Jobs/Saved Jobs.csv": SAVED_JOBS_HEADER + (
            f'"{_saved(3)}",http://www.linkedin.com/jobs/view/4180272490,Senior QA Engineer,Globex\n'
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["saved_jobs_read"] == 1 and summary["saved_jobs_added"] == 0

    jobs = cp.list_jobs()["jobs"]
    assert len(jobs) == 1 and jobs[0]["id"] == existing["id"]
    # The description the job already had survives the merge, so its tier is not knocked back.
    assert cp.get_job(existing["id"])["description"]


def test_connections_are_read_across_shards(cp):
    make_export(cp.imports_dir, extra={
        "Connections_1.csv": (
            "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
            "Sara,Fahmy,https://www.linkedin.com/in/sara-f,,Umbrella,QA Engineer,05 May 2025\n"
        ),
    })
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["connections"] == 3
    names = {row["name"] for row in cp.store.query("SELECT name FROM connections")}
    assert "Sara Fahmy" in names


def test_export_without_saved_jobs_still_imports(cp):
    make_export(cp.imports_dir)
    summary = cp.import_linkedin_export("Complete_LinkedInDataExport.zip")
    assert summary["saved_jobs_read"] == 0 and summary["saved_jobs_added"] == 0
    assert cp.list_jobs()["jobs"] == []
