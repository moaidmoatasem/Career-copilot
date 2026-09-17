"""Draft → human review → human action. The assistant can create and revise drafts; only a human approves.

Integrity rules:
* approve/reject are never exposed as MCP tools (the CLI calls them, from an interactive terminal);
* approval stores a SHA-256 of the exact approved text; mark_executed refuses if the text changed;
* every transition is written to the append-only audit log.
"""

from __future__ import annotations

import json
import re

from .safety import detect_flags
from .store import Store
from .util import sha256, utcnow

KINDS = ("message_reply", "post", "comment", "application", "profile_edit", "outreach")

_NUMERIC_CLAIM = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|percent\b|x\b|times\b|\+)"
    r"|\b(?:increased|reduced|decreased|improved|cut|saved|boosted|grew|accelerated|lowered)\b[^.\n]{0,40}?\d[\d.,]*",
    re.I,
)
_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+|00)\d[\d\s-]{7,}\d")


class DraftError(ValueError):
    pass


def content_checks(text: str, limit: int | None) -> dict:
    checks: dict = {"chars": len(text), "limit": limit, "ai_generated": True}
    claims = sorted({m.group(0).strip() for m in _NUMERIC_CLAIM.finditer(text)})
    if claims:
        checks["claims_to_verify"] = claims[:20]
    links = _URL.findall(text)
    if links:
        checks["outbound_links"] = links[:10]
    if _EMAIL.search(text) or _PHONE.search(text):
        checks["contains_contact_details"] = True
    flags = detect_flags(text)
    if flags:
        checks["flags"] = flags
    return checks


def _validate(content: str, limit: int | None, kind: str) -> str:
    content = (content or "").strip()
    if not content:
        raise DraftError("draft text is empty")
    if limit is not None and len(content) > limit:
        raise DraftError(
            f"{kind} is {len(content)} characters but the limit for this field is {limit}. "
            "Shorten it and try again."
        )
    return content


def _row(store: Store, draft_id: int) -> dict:
    row = store.one("SELECT * FROM drafts WHERE id = ?", (draft_id,))
    if row is None:
        raise DraftError(f"draft {draft_id} not found")
    return row


def public_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "target": row["target_ref"],
        "channel": row["channel"],
        "content": row["content"],
        "original_content": row["original_content"] or None,
        "rationale": row["rationale"],
        "checks": json.loads(row["checks_json"] or "{}"),
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "reviewer_note": row["reviewer_note"] or None,
        "executed_at": row["executed_at"],
    }


def create(
    store: Store,
    *,
    kind: str,
    content: str,
    rationale: str,
    limit: int | None,
    target_ref: str = "",
    channel: str = "",
    original: str = "",
) -> dict:
    if kind not in KINDS:
        raise DraftError(f"unknown draft kind '{kind}'")
    content = _validate(content, limit, kind)
    checks = content_checks(content, limit)
    now = utcnow()
    with store.transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO drafts(kind, target_ref, channel, content, original_content, rationale, char_limit, "
            "checks_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?, 'pending', ?, ?)",
            (kind, target_ref, channel, content, original, (rationale or "").strip(), limit,
             json.dumps(checks, ensure_ascii=False), now, now),
        )
        draft_id = cursor.lastrowid
        store.audit("assistant", "draft.create", f"draft:{draft_id}",
                    {"kind": kind, "target": target_ref, "chars": len(content)}, conn=conn)
    return {
        "draft_id": draft_id,
        "status": "pending",
        "checks": checks,
        "next_step": "Nothing has been sent. The user reviews this in a terminal with `career-copilot review`, "
                     "then performs the approved action on LinkedIn.",
    }


def revise(store: Store, draft_id: int, content: str, rationale: str | None = None) -> dict:
    row = _row(store, draft_id)
    if row["status"] != "pending":
        raise DraftError(f"draft {draft_id} is '{row['status']}'; only pending drafts can be revised")
    content = _validate(content, row["char_limit"], row["kind"])
    checks = content_checks(content, row["char_limit"])
    with store.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET content = ?, rationale = COALESCE(?, rationale), checks_json = ?, updated_at = ? WHERE id = ?",
            (content, rationale, json.dumps(checks, ensure_ascii=False), utcnow(), draft_id),
        )
        store.audit("assistant", "draft.revise", f"draft:{draft_id}", {"chars": len(content)}, conn=conn)
    return {"draft_id": draft_id, "status": "pending", "checks": checks}


def withdraw(store: Store, draft_id: int, reason: str = "") -> dict:
    row = _row(store, draft_id)
    if row["status"] != "pending":
        raise DraftError(f"draft {draft_id} is '{row['status']}'; only pending drafts can be withdrawn")
    with store.transaction() as conn:
        conn.execute("UPDATE drafts SET status = 'withdrawn', updated_at = ? WHERE id = ?", (utcnow(), draft_id))
        store.audit("assistant", "draft.withdraw", f"draft:{draft_id}", {"reason": reason}, conn=conn)
    return {"draft_id": draft_id, "status": "withdrawn"}


def approve(store: Store, draft_id: int, edited_content: str | None = None, note: str = "") -> dict:
    """Human-only. Called from the interactive CLI, never from the MCP server."""
    row = _row(store, draft_id)
    if row["status"] != "pending":
        raise DraftError(f"draft {draft_id} is '{row['status']}'; only pending drafts can be approved")
    content = row["content"]
    edited = edited_content is not None and edited_content.strip() != content
    if edited:
        content = _validate(edited_content or "", row["char_limit"], row["kind"])
    checks = content_checks(content, row["char_limit"])
    now = utcnow()
    with store.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET content = ?, checks_json = ?, status = 'approved', reviewed_at = ?, reviewer_note = ?, "
            "approved_hash = ?, updated_at = ? WHERE id = ?",
            (content, json.dumps(checks, ensure_ascii=False), now, note, sha256(content), now, draft_id),
        )
        store.audit("human", "draft.approve", f"draft:{draft_id}", {"edited": edited, "note": note}, conn=conn)
    return public_view(_row(store, draft_id))


def reject(store: Store, draft_id: int, note: str = "") -> dict:
    """Human-only."""
    row = _row(store, draft_id)
    if row["status"] != "pending":
        raise DraftError(f"draft {draft_id} is '{row['status']}'; only pending drafts can be rejected")
    now = utcnow()
    with store.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'rejected', reviewed_at = ?, reviewer_note = ?, updated_at = ? WHERE id = ?",
            (now, note, now, draft_id),
        )
        store.audit("human", "draft.reject", f"draft:{draft_id}", {"note": note}, conn=conn)
    return {"draft_id": draft_id, "status": "rejected"}


def revoke(store: Store, draft_id: int, reason: str = "") -> dict:
    """Human-only. Sends an approved-but-not-yet-done draft back to pending."""
    row = _row(store, draft_id)
    if row["status"] != "approved":
        raise DraftError(f"draft {draft_id} is '{row['status']}'; only approved drafts can be revoked")
    now = utcnow()
    with store.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'pending', reviewed_at = NULL, reviewer_note = '', approved_hash = NULL, "
            "updated_at = ? WHERE id = ?",
            (now, draft_id),
        )
        store.audit("human", "draft.revoke", f"draft:{draft_id}", {"reason": reason}, conn=conn)
    return public_view(_row(store, draft_id))


def mark_executed(store: Store, draft_id: int, actor: str, note: str = "") -> dict:
    row = _row(store, draft_id)
    if row["status"] != "approved":
        raise DraftError(
            f"draft {draft_id} is '{row['status']}'. Only drafts the user approved (career-copilot review) "
            "can be marked as done."
        )
    if not row["approved_hash"] or sha256(row["content"]) != row["approved_hash"]:
        raise DraftError(f"draft {draft_id} changed after approval; it needs to be reviewed again")
    now = utcnow()
    with store.transaction() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'executed', executed_at = ?, execution_note = ?, updated_at = ? WHERE id = ?",
            (now, note, now, draft_id),
        )
        store.audit(actor, "draft.executed", f"draft:{draft_id}", {"note": note}, conn=conn)
    return {"draft_id": draft_id, "status": "executed", "executed_at": now}
