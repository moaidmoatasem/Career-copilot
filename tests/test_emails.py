from datetime import datetime, timedelta, timezone

import pytest

from career_copilot.emails import categorize, classify, parse_email

JOB_ALERT_TEXT = """Your job alert for Senior QA Engineer in United Arab Emirates
3 new jobs match your preferences.

Senior QA Automation Engineer
Acme Cloud
Dubai, United Arab Emirates
View job: https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc%3D&refId=xyz

QA Lead
Globex Telecom
Riyadh, Saudi Arabia
View job: https://www.linkedin.com/comm/jobs/view/4087654321/?trackingId=def

See all jobs: https://www.linkedin.com/comm/jobs/search/?keywords=qa
Unsubscribe: https://www.linkedin.com/comm/psettings/email-unsubscribe?x=1
"""

JOB_ALERT_HTML = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?trk=eml"><img src="logo.png"></a></td>
<td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?trk=eml">Senior SDET</a>
<p>Initech &middot; Abu Dhabi, United Arab Emirates (Hybrid)</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4011111111/?trk=eml">Test Automation Lead</a>
<p>Umbrella Systems &middot; Cairo, Egypt</p></td></tr>
</table><div style="display:none">Your weekly jobs are here</div></body></html>"""

MESSAGE = """Sara Ahmed
Talent Acquisition Partner at Globex
Hi, we have a Senior QA Engineer opportunity in Dubai. Are you open to a quick chat this week?
View message: https://www.linkedin.com/comm/messaging/thread/2-ZmFrZVRocmVhZElk/?trk=eml
"""

ALERTS = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
MESSAGES = '"Sara Ahmed via LinkedIn" <messages-noreply@linkedin.com>'


def now_rfc2822(delta_hours: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=delta_hours)).strftime("%a, %d %b %Y %H:%M:%S +0000")


def test_plain_text_job_alert_is_parsed_and_tracking_removed():
    result = parse_email(ALERTS, "Senior QA Engineer: 3 new jobs", JOB_ALERT_TEXT)
    assert result.kind == "job_alert"
    by_id = {job["external_id"]: job for job in result.jobs}
    assert set(by_id) == {"4012345678", "4087654321"}
    first = by_id["4012345678"]
    assert first["title"] == "Senior QA Automation Engineer"
    assert first["company"] == "Acme Cloud"
    assert first["location"] == "Dubai, United Arab Emirates"
    assert first["url"] == "https://www.linkedin.com/jobs/view/4012345678/"


def test_html_job_alert_uses_anchor_text():
    result = parse_email(ALERTS, "New jobs for you", JOB_ALERT_HTML)
    titles = {job["title"]: job for job in result.jobs}
    assert set(titles) == {"Senior SDET", "Test Automation Lead"}
    assert titles["Senior SDET"]["company"] == "Initech"
    assert "Abu Dhabi" in titles["Senior SDET"]["location"]


def test_message_notification_becomes_high_priority_recruiter_item():
    result = parse_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822())
    assert result.kind == "message"
    item = result.inbox_items[0]
    assert item["sender"] == "Sara Ahmed"
    assert item["category"] == "recruiter" and item["priority"] == "high"
    assert item["url"] == "https://www.linkedin.com/messaging/thread/2-ZmFrZVRocmVhZElk/"
    assert "opportunity in Dubai" in item["preview"]


def test_scam_message_is_marked_suspicious():
    body = "Congratulations! You are selected for a QA role in Doha. Pay the visa processing fee to confirm."
    result = parse_email(MESSAGES, "Sara Ahmed sent you a new message", body)
    assert result.inbox_items[0]["category"] == "suspicious"


# F5: recruiter messages that name no "role" or "job" were filed as other, normal priority.
STC_MESSAGE = ("Hi Moaid, we have a QA Lead opening at STC in Riyadh and your profile stands out. "
               "Would you be open to a quick call this week?")
ARABIC_MESSAGE = "مرحباً معيد، لدينا فرصة عمل في فريق ضمان الجودة في الرياض. هل أنت مهتم بالتواصل؟"


@pytest.mark.parametrize("body", [STC_MESSAGE, ARABIC_MESSAGE], ids=["stc", "arabic"])
def test_recruiter_messages_are_recruiter_high_priority(body):
    result = parse_email(MESSAGES, "Khalid Al-Otaibi sent you a new message", body)
    item = result.inbox_items[0]
    assert (item["category"], item["priority"]) == ("recruiter", "high")


@pytest.mark.parametrize("text", [
    "Two openings in our Dubai test team, interested?",
    "We are looking for a Senior SDET to lead our mobile automation.",
    "Saw your profile and thought of our new QA team in Doha.",
    "نبحث عن مهندس اختبار آلي، هل الوظيفة تناسبك؟",
    "عندنا وظائف شاغرة في جدة",
])
def test_recruiter_phrasing(text):
    assert categorize(text, []) == ("recruiter", "high")


def test_new_recruiter_words_do_not_swallow_sales_or_networking():
    assert categorize("Join the grand opening webinar and book a demo of our services", [])[0] == "sales_pitch"
    assert categorize("Thanks for connecting, great to connect!", [])[0] == "networking"


def test_genuine_gulf_offer_is_not_suspicious():
    body = ("Hi, we'd like to move forward with you for the Senior QA role in Dubai. "
            "Visa fees are covered by the company and we handle your work permit.")
    result = parse_email(MESSAGES, "Sara Ahmed sent you a new message", body)
    assert result.inbox_items[0]["category"] != "suspicious"


def test_invitation_and_job_board_and_digest():
    invite = parse_email("LinkedIn <invitations@linkedin.com>", "Omar Khaled wants to connect", "Omar Khaled\nQA Manager")
    assert invite.kind == "invitation" and invite.inbox_items[0]["sender"] == "Omar Khaled"

    bayt = parse_email(
        "Bayt.com <jobs@bayt.com>", "New jobs matching Senior QA Engineer",
        "Senior QA Engineer\nEmirates Partner LLC\nhttps://www.bayt.com/en/uae/jobs/senior-qa-engineer-4876543/?utm_source=alert",
    )
    assert bayt.kind == "job_alert"
    assert bayt.jobs[0]["title"] == "Senior QA Engineer"
    assert bayt.jobs[0]["url"] == "https://www.bayt.com/en/uae/jobs/senior-qa-engineer-4876543/"

    digest = parse_email(
        "LinkedIn <updates-noreply@linkedin.com>", "Top posts from your network",
        "Ahmed Samir posted: How we cut flaky Playwright tests in CI\n"
        "https://www.linkedin.com/comm/posts/ahmed-samir_playwright-activity-7234567890123456789-AbCd?trk=eml",
    )
    assert digest.kind == "digest"
    assert digest.news_items[0]["title"].startswith("Ahmed Samir posted")


def test_classify_other():
    assert classify("Someone <x@example.com>", "Lunch on Friday?", "hi") == "other"


def test_ingest_dedupes_and_scores(cp):
    first = cp.ingest_email(ALERTS, "3 new jobs", JOB_ALERT_TEXT, now_rfc2822())
    assert len(first["jobs_added"]) == 2
    assert all(job["tier"] in {"matched", "promising", "close", "low_fit"} for job in first["jobs_added"])
    second = cp.ingest_email(ALERTS, "3 new jobs", JOB_ALERT_TEXT, now_rfc2822())
    assert second["jobs_added"] == [] and second["jobs_already_known"] == 2


def test_new_message_in_same_thread_updates_item(cp):
    cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822(2))
    cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE.replace("this week", "tomorrow"), now_rfc2822(0))
    items = cp.list_inbox()["items"]
    assert len(items) == 1 and "tomorrow" in items[0]["preview"]


def test_application_update_moves_job_to_applied(cp):
    cp.ingest_email(ALERTS, "3 new jobs", JOB_ALERT_TEXT, now_rfc2822())
    cp.ingest_email(
        "LinkedIn <jobs-noreply@linkedin.com>", "Your application was sent to Acme Cloud",
        "Your application was sent\nhttps://www.linkedin.com/comm/jobs/view/4012345678/", now_rfc2822(),
    )
    jobs = cp.list_jobs(status="applied")["jobs"] or cp.list_jobs(tier="low_fit", status="applied")["jobs"]
    assert [job["url"] for job in jobs] == ["https://www.linkedin.com/jobs/view/4012345678/"]
