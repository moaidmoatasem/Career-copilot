"""The Copilot Console: localhost-only, session-gated, no route reaches LinkedIn."""

from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

from career_copilot import console
from career_copilot.service import CopilotError

from test_emails import MESSAGE, MESSAGES, now_rfc2822

PORT = 55199


@pytest.fixture
def app(cp):
    return console.create_app(cp, PORT)


@pytest.fixture
def client(app):
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


@pytest.fixture
def logged_in(client, app):
    r = client.get(f"/login?token={app.state.launch_token}")
    assert r.status_code == 200
    return client


def _reply_draft(cp):
    cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822())
    item = cp.list_inbox()["items"][0]
    return item, cp.draft_message_reply(item["id"], "Thanks Sara, happy to talk on Tuesday.", "recruiter outreach")


# ---------------------------------------------------------------------------- session security

def test_unauthenticated_request_is_locked_out(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/locked"


def test_login_token_works_once(client, app):
    url = f"/login?token={app.state.launch_token}"
    r = client.get(url)
    assert r.status_code == 200
    assert "cc_session" in client.cookies

    r2 = client.get(url)
    assert r2.status_code == 403


def test_wrong_token_is_rejected(client):
    r = client.get("/login?token=not-the-token")
    assert r.status_code == 403


def test_idle_session_locks(logged_in, app):
    sid = logged_in.cookies["cc_session"]
    app.state.sessions[sid] = time.monotonic() - console.IDLE_TIMEOUT_SECONDS - 1
    r = logged_in.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/locked"


def test_origin_mismatch_on_post_is_rejected(logged_in):
    r = logged_in.post("/data/purge", data={"what": "drafts"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers_present(logged_in):
    r = logged_in.get("/")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "script-src 'self'" in r.headers["content-security-policy"]


# ---------------------------------------------------------------------------- today & nav

def test_today_shows_status(logged_in, cp):
    _reply_draft(cp)
    r = logged_in.get("/")
    assert r.status_code == 200
    assert "Drafts waiting" in r.text
    assert "1" in r.text  # one pending draft


# ---------------------------------------------------------------------------- review

def test_pending_draft_lists_and_shows_checks(logged_in, cp):
    result = cp.draft_post("We reduced regression time by 40% last quarter. Details: https://example.com", "post idea")
    draft_id = result["draft_id"]

    r = logged_in.get("/review")
    assert f"#{draft_id}" in r.text

    r = logged_in.get(f"/review/{draft_id}")
    assert "trace this number" in r.text
    assert "confirm this link" in r.text


def test_approve_is_blocked_until_checks_confirmed(logged_in, cp):
    result = cp.draft_post("We reduced regression time by 40% last quarter. Details: https://example.com", "idea")
    draft_id = result["draft_id"]

    r = logged_in.post(f"/review/{draft_id}/approve", data={"note": ""}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert cp.get_draft(draft_id)["status"] == "pending"


def test_approve_with_all_checks_confirmed_succeeds(logged_in, cp):
    result = cp.draft_post("We reduced regression time by 40% last quarter. Details: https://example.com", "idea")
    draft_id = result["draft_id"]
    checks = result["checks"]
    form = {"note": "verified"}
    form.update({f"claim_{i}": "on" for i in range(len(checks["claims_to_verify"]))})
    form.update({f"link_{i}": "on" for i in range(len(checks["outbound_links"]))})

    r = logged_in.post(f"/review/{draft_id}/approve", data=form, follow_redirects=False)
    assert r.status_code == 303
    assert cp.get_draft(draft_id)["status"] == "approved"


def test_edit_then_approve(logged_in, cp):
    _, draft = _reply_draft(cp)
    draft_id = draft["draft_id"]

    r = logged_in.post(f"/review/{draft_id}/edit", data={"content": "Thanks Sara, Wednesday works better."},
                       follow_redirects=False)
    assert r.status_code == 303
    assert cp.get_draft(draft_id)["content"] == "Thanks Sara, Wednesday works better."

    r = logged_in.post(f"/review/{draft_id}/approve", data={"note": ""})
    assert cp.get_draft(draft_id)["status"] == "approved"


def test_reject_records_reason(logged_in, cp):
    _, draft = _reply_draft(cp)
    draft_id = draft["draft_id"]
    r = logged_in.post(f"/review/{draft_id}/reject", data={"reason": "tone", "detail": "too formal"},
                       follow_redirects=False)
    assert r.status_code == 303
    view = cp.get_draft(draft_id)
    assert view["status"] == "rejected"
    assert "too formal" in view["reviewer_note"]


def test_revoke_sends_approved_draft_back_to_pending(logged_in, cp):
    _, draft = _reply_draft(cp)
    draft_id = draft["draft_id"]
    cp.approve_draft(draft_id)

    r = logged_in.post(f"/review/{draft_id}/revoke", follow_redirects=False)
    assert r.status_code == 303
    assert cp.get_draft(draft_id)["status"] == "pending"


def test_mark_done_only_after_approval(logged_in, cp):
    _, draft = _reply_draft(cp)
    draft_id = draft["draft_id"]

    r = logged_in.post(f"/review/{draft_id}/done", follow_redirects=False)
    assert "error=" in r.headers["location"]

    cp.approve_draft(draft_id)
    r = logged_in.post(f"/review/{draft_id}/done", follow_redirects=False)
    assert r.status_code == 303
    assert cp.get_draft(draft_id)["status"] == "executed"


def test_tampered_approved_draft_cannot_be_marked_done(logged_in, cp):
    _, draft = _reply_draft(cp)
    draft_id = draft["draft_id"]
    cp.approve_draft(draft_id)
    cp.store.execute("UPDATE drafts SET content = 'tampered' WHERE id = ?", (draft_id,))

    r = logged_in.post(f"/review/{draft_id}/done", follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert cp.get_draft(draft_id)["status"] == "approved"


def test_draft_content_is_escaped_not_rendered_as_html(logged_in, cp):
    result = cp.draft_post("<script>alert(1)</script> nice post", "idea")
    r = logged_in.get(f"/review/{result['draft_id']}")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


# ---------------------------------------------------------------------------- jobs

def test_jobs_board_and_detail(logged_in, cp):
    job = cp.add_job("QA Automation Engineer", "Acme", "Cairo, Egypt", "", "")
    r = logged_in.get("/jobs")
    assert "QA Automation Engineer" in r.text

    r = logged_in.get(f"/jobs/{job['id']}")
    assert r.status_code == 200
    assert "Fit breakdown" in r.text


def test_job_description_update_rescores(logged_in, cp):
    job = cp.add_job("Senior QA Engineer", "Acme", "United Arab Emirates", "")
    description = (
        "Requirements: 5+ years in test automation, Strong Python and Playwright, "
        "API testing, CI/CD pipelines and Docker. " * 3
    )
    r = logged_in.post(f"/jobs/{job['id']}/description", data={"description": description}, follow_redirects=False)
    assert r.status_code == 303
    updated = cp.get_job(job["id"])
    assert updated["has_description"]
    assert updated["tier"] in ("matched", "promising", "close")


def test_job_status_change(logged_in, cp):
    job = cp.add_job("QA Engineer", "Acme", "Egypt", "")
    r = logged_in.post(f"/jobs/{job['id']}/status", data={"status": "shortlisted", "back": "detail"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/jobs/{job['id']}"
    assert cp.get_job(job["id"])["status"] == "shortlisted"


# ---------------------------------------------------------------------------- inbox

def test_inbox_list_and_status_change(logged_in, cp):
    item, _ = _reply_draft(cp)
    r = logged_in.get("/inbox")
    assert item["sender"] in r.text or "Sara" in r.text

    r = logged_in.post(f"/inbox/{item['id']}/status", data={"status": "archived"}, follow_redirects=False)
    assert r.status_code == 303
    assert cp.list_inbox(status="archived")["items"][0]["id"] == item["id"]


def test_inbox_preview_text_is_not_html_and_not_autolinked(logged_in, cp):
    cp.ingest_email(
        MESSAGES,
        "Sara Ahmed sent you a new message",
        MESSAGE.replace("Thanks", "Visit https://phish.example <b>now</b> Thanks"),
        now_rfc2822(),
    )
    r = logged_in.get("/inbox")
    assert '<a href="https://phish.example"' not in r.text
    assert "<b>now</b>" not in r.text


# ---------------------------------------------------------------------------- data & privacy

def test_data_page_shows_status(logged_in, cp):
    r = logged_in.get("/data")
    assert r.status_code == 200
    assert str(cp.profile_path) in r.text


def test_purge_rejects_unknown_category(logged_in):
    r = logged_in.post("/data/purge", data={"what": "everything"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_purge_requires_typed_confirmation(logged_in, cp):
    cp.draft_post("A short post.", "idea")
    r = logged_in.post("/data/purge", data={"what": "drafts", "confirm": "nope"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert cp.list_drafts("pending")["count"] == 1


def test_purge_removes_drafts(logged_in, cp):
    cp.draft_post("A short post.", "idea")
    assert cp.list_drafts("pending")["count"] == 1
    r = logged_in.post("/data/purge", data={"what": "drafts", "confirm": "drafts"}, follow_redirects=False)
    assert r.status_code == 303
    assert cp.list_drafts("pending")["count"] == 0


def test_purge_all_requires_typing_delete(logged_in, cp):
    r = logged_in.post("/data/purge", data={"what": "all", "confirm": "all"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    r = logged_in.post("/data/purge", data={"what": "all", "confirm": "DELETE"}, follow_redirects=False)
    assert r.status_code == 303
