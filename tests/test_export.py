import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from career_copilot.service import CopilotError


def _date(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S UTC")


def make_export(folder, name="Complete_LinkedInDataExport.zip"):
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
