import sqlite3

import pytest

from career_copilot.service import CopilotError

from test_emails import MESSAGE, MESSAGES, now_rfc2822


def _reply_draft(cp):
    cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822())
    item = cp.list_inbox()["items"][0]
    return item, cp.draft_message_reply(item["id"], "Thanks Sara, happy to talk on Tuesday.", "recruiter outreach")


def test_draft_is_pending_and_inbox_marked(cp):
    item, draft = _reply_draft(cp)
    assert draft["status"] == "pending"
    assert cp.list_inbox(status="drafted")["items"][0]["id"] == item["id"]
    assert "Nothing has been sent" in draft["next_step"]


def test_limits_are_enforced(cp):
    with pytest.raises(CopilotError, match="221 characters"):
        cp.propose_profile_edit("headline", "x" * 221, "too long")
    with pytest.raises(CopilotError, match="limit for this field is 200"):
        cp.draft_outreach("Nour Hassan", "y" * 201, "note", channel="connection_note")


def test_numbers_and_links_are_flagged_for_review(cp):
    result = cp.draft_post("We reduced regression time by 40% last quarter. Details: https://example.com", "post idea")
    assert result["checks"]["claims_to_verify"]
    assert result["checks"]["outbound_links"] == ["https://example.com"]


def test_assistant_cannot_mark_unapproved_draft_as_done(cp):
    _, draft = _reply_draft(cp)
    with pytest.raises(CopilotError, match="Only drafts the user approved"):
        cp.mark_executed(draft["draft_id"])


def test_human_approval_then_execution(cp):
    _, draft = _reply_draft(cp)
    approved = cp.approve_draft(draft["draft_id"], note="looks good")
    assert approved["status"] == "approved"
    with pytest.raises(CopilotError, match="only pending drafts can be revised"):
        cp.revise_draft(draft["draft_id"], "sneaky change")
    actions = cp.get_approved_actions()["actions"]
    assert "linkedin.com/messaging/thread" in actions[0]["how_to_do_it"]
    assert cp.mark_executed(draft["draft_id"], "sent on LinkedIn")["status"] == "executed"
    actors = {(e["actor"], e["action"]) for e in cp.audit_log()["entries"]}
    assert ("human", "draft.approve") in actors and ("assistant", "draft.executed") in actors


def test_tampering_after_approval_is_detected(cp):
    _, draft = _reply_draft(cp)
    cp.approve_draft(draft["draft_id"])
    cp.store.execute("UPDATE drafts SET content = 'different text' WHERE id = ?", (draft["draft_id"],))
    with pytest.raises(CopilotError, match="changed after approval"):
        cp.mark_executed(draft["draft_id"])


def test_edit_during_approval_is_revalidated(cp):
    draft = cp.propose_profile_edit("headline", "Senior QA Engineer | Test Automation | API Testing", "sharper")
    with pytest.raises(CopilotError, match="limit"):
        cp.approve_draft(draft["draft_id"], edited_text="z" * 300)


def test_audit_log_is_append_only(cp):
    cp.draft_post("A short post about testing.", "idea")
    with pytest.raises(sqlite3.DatabaseError):
        cp.store.execute("DELETE FROM audit_log")
    with pytest.raises(sqlite3.DatabaseError):
        cp.store.execute("UPDATE audit_log SET actor = 'human'")
