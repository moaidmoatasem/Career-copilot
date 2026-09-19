"""Copilot Console: a localhost-only web app where you review and approve drafts.

Claude drafts (in Claude Desktop), you decide (here, or in `career-copilot review`),
LinkedIn is where anything actually happens. This module has no route that reaches
LinkedIn, and no "send" capability exists anywhere in this codebase: approving,
rejecting, revoking and marking a draft done are human-only operations that live in
`drafts.py`, never exposed as an MCP tool.

Security posture (see README "Security model"):
* binds 127.0.0.1 only, never 0.0.0.0;
* a one-time launch token (printed by `career-copilot console`) is exchanged for an
  HttpOnly, SameSite=Strict session cookie; the token cannot be reused;
* the session locks after 15 minutes idle — there is no PIN yet (tracked as an open
  decision in the product plan), so unlocking means running `career-copilot console`
  again from a terminal;
* Host and Origin headers are checked on every request to close DNS-rebinding and
  cross-site-request paths; a strict Content-Security-Policy allows only this
  server's own same-origin assets (no CDN, no inline script);
* external text (job descriptions, inbox previews) is always shown escaped as plain
  text, never as HTML, and URLs inside it are never auto-linked.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import time
import webbrowser
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from . import boards
from .service import (
    ACTIVE_TIERS, ALL_TIERS, COURSE_STATUSES, INBOX_STATUSES, JOB_STATUSES, Copilot, CopilotError,
)

IDLE_TIMEOUT_SECONDS = 15 * 60
LAUNCH_TOKEN_TTL_SECONDS = 10 * 60
SESSION_COOKIE = "cc_session"
PURGE_CHOICES = ("inbox", "news", "jobs", "connections", "snapshot", "drafts", "courses", "sponsors", "all")
REJECT_REASONS = ("wrong facts", "tone", "not needed", "other")

NAV_ITEMS = [
    ("/", "Today"),
    ("/review", "Review"),
    ("/jobs", "Jobs"),
    ("/career", "Career path"),
    ("/inbox", "Inbox"),
    ("/activity", "Activity"),
    ("/data", "Data & privacy"),
]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _age(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _int_param(request: Request, name: str, default: int, low: int, high: int) -> int:
    """A query-string integer, clamped. A junk value falls back rather than erroring the page."""
    try:
        return max(low, min(high, int(request.query_params.get(name, default))))
    except (TypeError, ValueError):
        return default


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


# ---------------------------------------------------------------------------- assets

CSS = """
:root {
  --bg: #f7f7f5; --surface: #ffffff; --border: #e2e0db; --text: #1c1c1a; --muted: #6b6a63;
  --accent: #7c5cff; --accent-ink: #ffffff; --good: #1b7a4d; --warn: #a15c00; --bad: #b3261e;
  --external-bg: #f1eef9; --external-rule: #7c5cff; --ai-chip: #7c5cff; --lock: #3a3a36;
  --focus: #2563eb; --radius: 10px; color-scheme: light;
}
:root:not([data-theme="light"]) {
  @media (prefers-color-scheme: dark) {
    --bg: #16161a; --surface: #1e1e23; --border: #34343c; --text: #f0f0ee; --muted: #a4a3ab;
    --accent: #a78bfa; --accent-ink: #16161a; --good: #4ade80; --warn: #fbbf24; --bad: #f87171;
    --external-bg: #262233; --external-rule: #a78bfa; --lock: #d8d8dd; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #16161a; --surface: #1e1e23; --border: #34343c; --text: #f0f0ee; --muted: #a4a3ab;
  --accent: #a78bfa; --accent-ink: #16161a; --good: #4ade80; --warn: #fbbf24; --bad: #f87171;
  --external-bg: #262233; --external-rule: #a78bfa; --lock: #d8d8dd; color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); }
.shell { display: flex; min-height: 100vh; }
.nav { width: 220px; flex: none; border-right: 1px solid var(--border); padding: 16px 8px; }
.nav .brand { font-weight: 700; padding: 8px 12px 16px; }
.nav-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 12px;
  border-radius: var(--radius); color: var(--text); text-decoration: none; margin-bottom: 2px; }
.nav-item:hover { background: var(--surface); }
.nav-item.active { background: var(--accent); color: var(--accent-ink); }
.badge { background: var(--muted); color: var(--surface); border-radius: 999px; padding: 1px 8px; font-size: 12px; }
.badge.red { background: var(--bad); color: #fff; }
.main { flex: 1; min-width: 0; padding: 20px 28px 60px; max-width: 1200px; }
.topstrip { display: flex; flex-wrap: wrap; gap: 16px; color: var(--muted); font-size: 12.5px; margin-bottom: 20px; }
h1 { font-size: 20px; margin: 0 0 16px; }
h2 { font-size: 15px; margin: 24px 0 10px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; margin-bottom: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.stat { font-size: 28px; font-weight: 700; }
.muted { color: var(--muted); }
.row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 14px; flex-wrap: wrap; }
.tabs a { padding: 8px 12px; text-decoration: none; color: var(--muted); border-bottom: 2px solid transparent; }
.tabs a.active { color: var(--text); border-color: var(--accent); font-weight: 600; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
.chip { display: inline-block; border: 1px solid var(--border); border-radius: 999px; padding: 1px 9px; font-size: 12px; margin: 2px 4px 2px 0; }
.chip.tier-matched { background: var(--good); color: #fff; border-color: transparent; }
.chip.tier-promising { background: var(--accent); color: var(--accent-ink); border-color: transparent; }
.chip.tier-close { border-color: var(--muted); }
.chip.tier-low_fit, .chip.tier-excluded { color: var(--muted); }
.external { background: var(--external-bg); border-left: 3px solid var(--external-rule); border-radius: 0 6px 6px 0;
  padding: 10px 12px; white-space: pre-wrap; word-break: break-word; }
.external .src { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.ai-chip { display: inline-block; background: var(--ai-chip); color: #fff; border-radius: 999px; padding: 1px 9px; font-size: 11px; font-weight: 600; }
.approved-lock { color: var(--lock); font-size: 12px; }
.banner { border-radius: var(--radius); padding: 10px 14px; margin-bottom: 14px; }
.banner.warn { background: color-mix(in srgb, var(--warn) 15%, var(--surface)); border: 1px solid var(--warn); }
.banner.bad { background: color-mix(in srgb, var(--bad) 15%, var(--surface)); border: 1px solid var(--bad); }
.banner.good { background: color-mix(in srgb, var(--good) 15%, var(--surface)); border: 1px solid var(--good); }
.check-list { list-style: none; padding: 0; margin: 8px 0; }
.check-list li { padding: 6px 0; border-bottom: 1px dashed var(--border); }
label { display: block; margin: 10px 0 4px; font-weight: 600; font-size: 12.5px; }
textarea, input[type=text], input[type=password], select {
  width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font: inherit; }
textarea { min-height: 140px; resize: vertical; }
/* Inline controls inside a .row. These need the element in the selector: the rule above uses
   input[type=text], which outranks a bare class on specificity. */
input.field-sm, select.field-sm { width: 6em; flex: none; }
input.field-md, select.field-md { width: 11em; flex: none; }
.row form { margin: 0; }
button, .btn { background: var(--accent); color: var(--accent-ink); border: none; border-radius: 8px;
  padding: 9px 16px; font: inherit; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; min-height: 40px; }
button.secondary, .btn.secondary { background: transparent; color: var(--text); border: 1px solid var(--border); }
button.danger, .btn.danger { background: var(--bad); color: #fff; }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--focus); outline-offset: 2px; }
.bars { display: grid; gap: 8px; margin: 10px 0; }
.bar-row { display: grid; grid-template-columns: 90px 1fr 48px; align-items: center; gap: 8px; font-size: 12.5px; }
.bar-track { background: var(--border); border-radius: 6px; height: 10px; overflow: hidden; }
.bar-fill { background: var(--accent); height: 100%; }
.help { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5); align-items: center; justify-content: center; }
.help.open { display: flex; }
.help .card { max-width: 420px; }
kbd { border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; font-family: inherit; background: var(--bg); }
@media (max-width: 900px) {
  .shell { flex-direction: column; }
  .nav { width: 100%; display: flex; overflow-x: auto; border-right: none; border-bottom: 1px solid var(--border); }
  .nav .brand { display: none; }
  .nav-item { white-space: nowrap; }
  .main { padding: 16px; }
}
"""

JS = """
(function () {
  document.querySelectorAll("select[data-autosubmit]").forEach(function (el) {
    el.addEventListener("change", function () { el.form.requestSubmit(); });
  });
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var src = document.querySelector(btn.getAttribute("data-copy"));
      if (!src) return;
      navigator.clipboard.writeText(src.value || src.textContent).then(function () {
        var was = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = was; }, 1200);
      });
    });
  });
  document.querySelectorAll("form[data-confirm-text]").forEach(function (form) {
    var expect = form.getAttribute("data-confirm-text");
    var input = form.querySelector("[data-confirm-input]");
    var submit = form.querySelector("[data-confirm-submit]");
    if (!input || !submit) return;
    submit.disabled = true;
    input.addEventListener("input", function () { submit.disabled = input.value !== expect; });
  });
  var help = document.getElementById("shortcut-help");
  function inField(el) { return el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName); }
  document.addEventListener("keydown", function (e) {
    if (inField(document.activeElement) && e.key !== "Escape") return;
    var body = document.body;
    if (e.key === "?") { if (help) help.classList.toggle("open"); return; }
    if (e.key === "Escape") { if (help) help.classList.remove("open"); return; }
    if (e.key === "a") { var f = document.getElementById("approve-form"); if (f) f.requestSubmit(); }
    else if (e.key === "e") { var el = document.querySelector("[data-key-edit]"); if (el) location.href = el.href; }
    else if (e.key === "r") { var rr = document.querySelector("[data-key-reject]"); if (rr) rr.focus(); }
    else if (e.key === "j" || e.key === "s") { var n = document.querySelector("[data-key-next]"); if (n) location.href = n.href; }
    else if (e.key === "k") { var p = document.querySelector("[data-key-prev]"); if (p) location.href = p.href; }
  });
})();
"""


# ---------------------------------------------------------------------------- layout

def layout(request: Request, *, title: str, active: str, body: str) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    pending = cp.store.scalar("SELECT COUNT(*) FROM drafts WHERE status = 'pending'") or 0
    oldest = cp.store.scalar("SELECT created_at FROM drafts WHERE status = 'pending' ORDER BY id LIMIT 1")
    review_badge = ""
    if pending:
        klass = "badge red" if _hours_since(oldest) > 24 else "badge"
        review_badge = f'<span class="{klass}">{pending}</span>'
    badges = {"/review": review_badge}
    nav = "".join(
        f'<a class="nav-item{" active" if path == active else ""}" href="{path}">'
        f'<span>{esc(label)}</span>{badges.get(path, "")}</a>'
        for path, label in NAV_ITEMS
    )
    gmail = cp.gmail_status()
    strip = (
        f'<span>Claude: no MCP tool can approve or send — only this Console and '
        f'<code>career-copilot review</code> can.</span>'
        f'<span>Gmail: {"connected, last synced " + esc(_age(gmail["last_sync"])) if gmail["connected"] and gmail["last_sync"] else ("connected" if gmail["connected"] else "not connected")}</span>'
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)} · Copilot Console</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="shell">
  <nav class="nav">
    <div class="brand">Copilot Console</div>
    {nav}
  </nav>
  <main class="main">
    <div class="topstrip">{strip}</div>
    <h1>{esc(title)}</h1>
    {body}
  </main>
</div>
<div class="help" id="shortcut-help">
  <div class="card">
    <h2>Keyboard shortcuts</h2>
    <p><kbd>a</kbd> approve &nbsp; <kbd>e</kbd> edit &nbsp; <kbd>r</kbd> focus reject reason &nbsp;
       <kbd>j</kbd>/<kbd>s</kbd> next &nbsp; <kbd>k</kbd> previous &nbsp; <kbd>?</kbd> toggle this help</p>
  </div>
</div>
<script src="/static/app.js" defer></script>
</body>
</html>""")


def error_redirect(location: str, message: str) -> RedirectResponse:
    from urllib.parse import urlencode
    sep = "&" if "?" in location else "?"
    return RedirectResponse(f"{location}{sep}{urlencode({'error': message})}", status_code=303)


def banner_from_query(request: Request) -> str:
    err = request.query_params.get("error")
    ok = request.query_params.get("ok")
    if err:
        return f'<div class="banner bad">{esc(err)}</div>'
    if ok:
        return f'<div class="banner good">{esc(ok)}</div>'
    return ""


# ---------------------------------------------------------------------------- Today

def today(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    status = cp.status()
    reminders = "".join(f"<li>{esc(r)}</li>" for r in status["reminders"]) or "<li>Nothing needs you right now.</li>"
    tiers = status["jobs_by_tier"]
    tier_line = " · ".join(f"{esc(t)}: {tiers.get(t, 0)}" for t in ACTIVE_TIERS)
    body = f"""
{banner_from_query(request)}
<div class="grid">
  <div class="card">
    <div class="muted">Drafts waiting</div>
    <div class="stat">{status['drafts_pending_review']}</div>
    <a class="btn" href="/review">Review now</a>
  </div>
  <div class="card">
    <div class="muted">Approved, not done yet</div>
    <div class="stat">{status['drafts_approved_not_done']}</div>
    <a class="btn secondary" href="/review?tab=approved">Ready to do</a>
  </div>
  <div class="card">
    <div class="muted">Open in your inbox</div>
    <div class="stat">{status['inbox_open']}</div>
    <a class="btn secondary" href="/inbox">Go to inbox</a>
  </div>
  <div class="card">
    <div class="muted">Jobs by tier</div>
    <div style="margin-top:8px">{tier_line}</div>
    <a class="btn secondary" href="/jobs">Go to jobs</a>
  </div>
</div>
<h2>What needs you</h2>
<div class="card"><ul class="check-list">{reminders}</ul></div>
<h2>Run daily triage in Claude</h2>
<div class="card">
  <p class="muted">Paste this into Claude Desktop. Claude reads your job-alert emails and drafts replies;
  nothing is sent until you approve it here.</p>
  <textarea id="triage-prompt" readonly>Run my daily LinkedIn triage: sync Gmail (or read any job-alert emails I paste),
list new jobs by tier, tell me who needs a reply, and draft replies for my review.</textarea>
  <button class="secondary" data-copy="#triage-prompt">Copy prompt</button>
</div>
"""
    return layout(request, title="Today", active="/", body=body)


# ---------------------------------------------------------------------------- Review

def _draft_row(d: dict) -> str:
    checks = d["checks"]
    chips = []
    if checks.get("claims_to_verify"):
        chips.append(f'<span class="chip">{len(checks["claims_to_verify"])} number(s)</span>')
    if checks.get("outbound_links"):
        chips.append(f'<span class="chip">{len(checks["outbound_links"])} link(s)</span>')
    if checks.get("flags"):
        chips.append('<span class="chip" style="border-color:var(--bad);color:var(--bad)">flag</span>')
    target = esc(d["target"] or "—")
    return (f'<tr><td><a href="/review/{d["id"]}">#{d["id"]} · {esc(d["kind"])}</a></td>'
            f'<td>{target}</td><td>{esc(_age(d["created_at"]))}</td><td>{"".join(chips)}</td></tr>')


def review_list(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    tab = request.query_params.get("tab", "pending")
    tabs = [("pending", "Pending"), ("approved", "Ready to do"), ("executed", "Done"), ("rejected", "Rejected & withdrawn")]
    if tab not in {t for t, _ in tabs}:
        tab = "pending"
    if tab == "rejected":
        rows = cp.list_drafts("rejected", 100)["drafts"] + cp.list_drafts("withdrawn", 100)["drafts"]
        rows.sort(key=lambda d: d["id"], reverse=True)
    else:
        rows = cp.list_drafts(tab, 100)["drafts"]
    tab_html = "".join(
        f'<a class="{"active" if t == tab else ""}" href="/review?tab={t}">{esc(label)}</a>' for t, label in tabs
    )
    if not rows:
        empty = {
            "pending": "No drafts waiting. Ask Claude to triage your inbox and they'll appear here.",
            "approved": "Nothing approved yet.",
            "executed": "Nothing marked done yet.",
            "rejected": "Nothing rejected or withdrawn.",
        }[tab]
        table = f'<p class="muted">{esc(empty)}</p>'
    else:
        table = ('<table><thead><tr><th>Draft</th><th>Target</th><th>Age</th><th>Needs attention</th></tr></thead>'
                  f'<tbody>{"".join(_draft_row(d) for d in rows)}</tbody></table>')
    body = f'{banner_from_query(request)}<div class="tabs">{tab_html}</div><div class="card">{table}</div>'
    return layout(request, title="Review", active="/review", body=body)


def _length_line(checks: dict) -> str:
    limit = checks.get("limit")
    over = limit is not None and checks["chars"] > limit
    return (f'<div class="row">Length: {checks["chars"]}' + (f' / {limit}' if limit else '') +
            (' <span class="banner bad" style="display:inline;padding:2px 8px">over the limit</span>' if over else '') + '</div>')


def _checks_html(checks: dict, prefix: str = "") -> str:
    parts = []
    for i, claim in enumerate(checks.get("claims_to_verify", [])):
        parts.append(f'<li><label style="display:inline;font-weight:400"><input type="checkbox" name="{prefix}claim_{i}" required> '
                      f'I can trace this number: <strong>{esc(claim)}</strong></label></li>')
    for i, link in enumerate(checks.get("outbound_links", [])):
        parts.append(f'<li><label style="display:inline;font-weight:400"><input type="checkbox" name="{prefix}link_{i}" required> '
                      f'I confirm this link: <strong>{esc(link)}</strong></label></li>')
    if checks.get("contains_contact_details"):
        parts.append('<li class="muted">Contains an email address or phone number.</li>')
    for flag in checks.get("flags", []):
        parts.append(f'<li><label style="display:inline;font-weight:400"><input type="checkbox" name="{prefix}flag_ack" required> '
                      f'<strong style="color:var(--bad)">[{esc(flag["severity"])}] {esc(flag["type"])}</strong>: {esc(flag["excerpt"])}</label></li>')
    return "".join(parts)


def review_detail(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    try:
        d = cp.get_draft(draft_id)
    except CopilotError as exc:
        return error_redirect("/review", str(exc))
    status = d["status"]
    same_status = cp.list_drafts(status, 200)["drafts"]
    ids = [row["id"] for row in same_status]
    prev_id = next((i for i in reversed(ids) if i < draft_id), None)
    next_id = next((i for i in ids if i > draft_id), None)
    nav_links = (
        (f'<a class="btn secondary" data-key-prev href="/review/{prev_id}">&larr; Previous</a>' if prev_id else "") +
        (f'<a class="btn secondary" data-key-next href="/review/{next_id}">Next &rarr;</a>' if next_id else "")
    )
    checks_html = (_length_line(d["checks"]) + f'<ul class="check-list">{_checks_html(d["checks"])}</ul>'
                   if status == "pending" else "")
    content_block = f'<div class="external"><span class="src">draft text</span>{esc(d["content"])}</div>'
    actions = ""
    if status == "pending":
        actions = f"""
<form id="approve-form" method="post" action="/review/{draft_id}/approve" class="card">
  <h2>Approve</h2>
  {checks_html}
  <label>Note (optional)</label><input type="text" name="note">
  <div class="row" style="margin-top:10px">
    <button type="submit">Approve (a)</button>
    <a class="btn secondary" data-key-edit href="/review/{draft_id}/edit">Edit (e)</a>
  </div>
</form>
<form method="post" action="/review/{draft_id}/reject" class="card">
  <h2>Reject</h2>
  <label>Reason</label>
  <select name="reason" data-key-reject>{"".join(f'<option value="{esc(r)}">{esc(r)}</option>' for r in REJECT_REASONS)}</select>
  <label>Detail (optional)</label><input type="text" name="detail">
  <button type="submit" class="danger" style="margin-top:10px">Reject (r)</button>
</form>
"""
    elif status == "approved":
        actions = f"""
<div class="card">
  <h2>Ready to do on LinkedIn</h2>
  <p class="approved-lock">Approved. Locked to hash {esc(d.get('approved_hash') or '')[:8]} — it cannot drift after approval.</p>
  <ol>
    <li>Copy the text above</li>
    <li>Open the conversation or page on LinkedIn</li>
    <li>Paste and send/post/apply it yourself</li>
    <li>Come back and mark it done</li>
  </ol>
  <div class="row">
    <form method="post" action="/review/{draft_id}/done"><button type="submit">Mark as done</button></form>
    <form method="post" action="/review/{draft_id}/revoke"><button type="submit" class="secondary">Revoke (back to pending)</button></form>
  </div>
</div>
"""
    elif status == "executed":
        actions = f'<div class="card"><p class="muted">Marked done {esc(_age(d["executed_at"]))}.</p></div>'
    else:
        note = d.get("reviewer_note") or ""
        actions = f'<div class="card"><p class="muted">{esc(status.capitalize())}{": " + esc(note) if note else ""}.</p></div>'
    rationale = f'<p class="muted">Why Claude drafted this: {esc(d["rationale"])}</p>' if d.get("rationale") else ""
    body = f"""
{banner_from_query(request)}
<div class="row" style="justify-content:space-between">
  <div><span class="ai-chip">AI-generated</span> <strong>Draft #{draft_id} · {esc(d['kind'])}</strong>
    <span class="muted">target: {esc(d['target'] or '—')} · {esc(_age(d['created_at']))}</span></div>
  <div class="row">{nav_links}</div>
</div>
{rationale}
<p class="banner warn">Read this fully and check for inaccuracies before approving. Claude cannot approve, edit
history, or send anything — only you can, here or in <code>career-copilot review</code>.</p>
{content_block}
{actions}
"""
    return layout(request, title=f"Draft #{draft_id}", active="/review", body=body)


def review_edit_get(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    try:
        d = cp.get_draft(draft_id)
    except CopilotError as exc:
        return error_redirect("/review", str(exc))
    if d["status"] != "pending":
        return error_redirect(f"/review/{draft_id}", "only a pending draft can be edited")
    body = f"""
{banner_from_query(request)}
<form method="post" action="/review/{draft_id}/edit" class="card">
  <h2>Edit draft #{draft_id}</h2>
  <textarea name="content" autofocus>{esc(d['content'])}</textarea>
  <div class="row" style="margin-top:10px">
    <button type="submit">Save</button>
    <a class="btn secondary" href="/review/{draft_id}">Cancel</a>
  </div>
</form>
"""
    return layout(request, title=f"Edit draft #{draft_id}", active="/review", body=body)


async def review_edit_post(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    form = await request.form()
    try:
        cp.revise_draft(draft_id, form.get("content", ""))
    except CopilotError as exc:
        return error_redirect(f"/review/{draft_id}/edit", str(exc))
    return RedirectResponse(f"/review/{draft_id}", status_code=303)


async def review_approve(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    try:
        d = cp.get_draft(draft_id)
    except CopilotError as exc:
        return error_redirect("/review", str(exc))
    form = await request.form()
    checks = d["checks"]
    for i in range(len(checks.get("claims_to_verify", []))):
        if form.get(f"claim_{i}") != "on":
            return error_redirect(f"/review/{draft_id}", "confirm every number before approving")
    for i in range(len(checks.get("outbound_links", []))):
        if form.get(f"link_{i}") != "on":
            return error_redirect(f"/review/{draft_id}", "confirm every link before approving")
    if checks.get("flags") and form.get("flag_ack") != "on":
        return error_redirect(f"/review/{draft_id}", "acknowledge the safety flag before approving")
    try:
        cp.approve_draft(draft_id, note=form.get("note", ""))
    except CopilotError as exc:
        return error_redirect(f"/review/{draft_id}", str(exc))
    return RedirectResponse("/review?tab=approved&ok=" + str(draft_id), status_code=303)


async def review_reject(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    form = await request.form()
    reason = form.get("reason", "other")
    detail = form.get("detail", "")
    note = f"{reason}: {detail}" if detail else reason
    try:
        cp.reject_draft(draft_id, note=note)
    except CopilotError as exc:
        return error_redirect(f"/review/{draft_id}", str(exc))
    return RedirectResponse("/review?tab=rejected", status_code=303)


async def review_revoke(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    try:
        cp.revoke_draft(draft_id)
    except CopilotError as exc:
        return error_redirect(f"/review/{draft_id}", str(exc))
    return RedirectResponse(f"/review/{draft_id}", status_code=303)


async def review_done(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    draft_id = int(request.path_params["draft_id"])
    try:
        cp.mark_executed(draft_id, actor="human")
    except CopilotError as exc:
        return error_redirect(f"/review/{draft_id}", str(exc))
    return RedirectResponse("/review?tab=executed", status_code=303)


# ---------------------------------------------------------------------------- Jobs

def _job_row(j: dict) -> str:
    missing = "".join(f'<span class="chip">{esc(s)}</span>' for s in j.get("missing_required", [])[:3])
    desc = "" if j["has_description"] else '<span class="muted"> (no description)</span>'
    status_options = "".join(
        f'<option value="{s}"{" selected" if s == j["status"] else ""}>{s}</option>' for s in JOB_STATUSES
    )
    return f"""<tr>
  <td><a href="/jobs/{j['id']}">{esc(j['title'])}</a>{desc}<div class="muted">{esc(j['company'])} · {esc(j['location'])}</div></td>
  <td><span class="chip tier-{j['tier']}">{esc(j['tier'])}</span> {j['score'] if j['score'] is not None else '—'}</td>
  <td>{missing}</td>
  <td>
    <form method="post" action="/jobs/{j['id']}/status">
      <input type="hidden" name="back" value="board">
      <select name="status" data-autosubmit>{status_options}</select>
    </form>
  </td>
</tr>"""


def jobs_board(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    tier = request.query_params.get("tier") or None
    if tier and tier not in ALL_TIERS:
        tier = None
    rows = cp.list_jobs(tier, None, 100)["jobs"]
    tabs = [("", "Active")] + [(t, t.replace("_", " ")) for t in ALL_TIERS]
    tab_html = "".join(
        f'<a class="{"active" if (tier or "") == t else ""}" href="/jobs{"?tier=" + t if t else ""}">{esc(label)}</a>'
        for t, label in tabs
    )
    if not rows:
        table = '<p class="muted">No jobs yet. Ask Claude to sync your job alerts, or paste one to add manually.</p>'
    else:
        table = ('<table><thead><tr><th>Job</th><th>Fit</th><th>Missing skills</th><th>Status</th></tr></thead>'
                  f'<tbody>{"".join(_job_row(j) for j in rows)}</tbody></table>')
    body = f'{banner_from_query(request)}<div class="tabs">{tab_html}</div><div class="card">{table}</div>'
    return layout(request, title="Jobs", active="/jobs", body=body)


def _sponsorship_card(sponsorship: dict | None) -> str:
    """Render the register signal. Deliberately plain text and no progress bar: the score is a
    name-similarity confidence, not a measure of fit, and must never be read as one."""
    if not sponsorship:
        return ""
    status = sponsorship.get("status")
    register = sponsorship.get("register", {})
    provisional = ('<span class="chip">PROVISIONAL · register imported '
                   f'{esc(_age(register.get("imported_at")))}</span>' if register.get("stale") else "")

    if status == "no_register":
        inner = ('<p>The sponsor register has not been imported yet, so this is <strong>unknown</strong> — '
                 'not a "no". Import it from the Data &amp; privacy page.</p>')
    elif status == "no_company":
        inner = '<p>No usable company name was recorded for this job, so the register cannot be checked.</p>'
    elif status == "no_match":
        inner = (f'<p>No licensed sponsor matched <strong>{esc(sponsorship.get("searched_for", ""))}</strong>. '
                 'The employer may be registered under a different legal name — check the register itself '
                 'before concluding anything.</p>')
    elif status == "needs_confirmation":
        rows = "".join(
            f'<li><strong>{esc(c["name"])}</strong> · {esc(c["town"] or "—")} · {esc(c["route"])} '
            f'<span class="muted">({c["score"]:.2f} name match)</span></li>'
            for c in sponsorship.get("candidates", [])
        )
        inner = (f'<p>Possible matches for <strong>{esc(sponsorship.get("searched_for", ""))}</strong> — '
                 f'confirm which is right:</p><ul class="check-list">{rows}</ul>')
    else:
        match = sponsorship.get("match") or {}
        inner = (f'<p><strong>{esc(match.get("name", ""))}</strong> appears on the register · '
                 f'{esc(match.get("town") or "—")} · {esc(match.get("route", ""))} · '
                 f'{esc(match.get("type_rating", ""))}</p>')

    caveat = ('<p class="muted">Register entries are company-level. A licence does not mean this employer '
              'will sponsor this role, and says nothing about whether you meet the salary or skill '
              'thresholds.</p>')
    return f"""
<div class="card">
  <h2>UK sponsor register</h2>
  {provisional}
  {inner}
  {caveat}
</div>"""


def _referrals_card(referrals: dict | None) -> str:
    """Who you already know at this company. It informs; it never offers to contact anyone."""
    if referrals is None:
        return ""
    connections = referrals.get("connections", [])
    if not connections:
        note = referrals.get("note") or "No first-degree connections found at this company."
        inner = f'<p class="muted">{esc(note)}</p>'
    else:
        rows = "".join(
            f'<li><strong>{esc(c["name"])}</strong>'
            + (f' · {esc(c["position"])}' if c.get("position") else "")
            + (f' · <span class="muted">connected {esc(c["connected_on"])}</span>' if c.get("connected_on") else "")
            + (f' · <a href="{esc(c["profile_url"])}" target="_blank" rel="noopener noreferrer">profile</a>'
               if c.get("profile_url") else "")
            + "</li>"
            for c in connections
        )
        tip = f'<p class="muted">{esc(referrals["tip"])}</p>' if referrals.get("tip") else ""
        inner = f'<ul class="check-list">{rows}</ul>{tip}'
    return f"""
<div class="card">
  <h2>People you know at {esc(referrals.get("company") or "this company")}</h2>
  {inner}
</div>"""


def _bar(label: str, value: float | None) -> str:
    if value is None:
        return ""
    pct = max(0, min(100, round(value * 100)))
    return (f'<div class="bar-row"><span>{esc(label)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div><span>{pct}%</span></div>')


def job_detail(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    job_id = int(request.path_params["job_id"])
    try:
        j = cp.get_job(job_id)
    except CopilotError as exc:
        return error_redirect("/jobs", str(exc))
    breakdown = j["analysis"].get("breakdown", {})
    bars = "".join(_bar(k, breakdown.get(k)) for k in ("skills", "title", "level", "location"))
    matched = "".join(f'<span class="chip">{esc(s)}</span>' for s in j["analysis"].get("matched_skills", []))
    missing_req = "".join(f'<span class="chip" style="border-color:var(--bad);color:var(--bad)">{esc(s)}</span>'
                           for s in j["analysis"].get("missing_required", []))
    missing_pref = "".join(f'<span class="chip">{esc(s)}</span>' for s in j["analysis"].get("missing_preferred", []))
    flags = ""
    if j.get("flags"):
        items = "".join(f'<li>[{esc(f["severity"])}] {esc(f["type"])}: {esc(f["excerpt"])}</li>' for f in j["flags"])
        flags = f'<div class="banner bad"><strong>Flagged</strong><ul>{items}</ul></div>'
    reasons = "".join(f"<li>{esc(r)}</li>" for r in j.get("why", []))
    description_block = (
        f'<div class="external"><span class="src">job description (external)</span>{esc(j["description"])}</div>'
        if j["description"] else '<p class="muted">No description yet — capped at Promising until one is added.</p>'
    )

    # Offer the fetch only where it can actually work: a URL, no description yet, and a board the
    # fetcher is allowed to read. A LinkedIn job gets the refusal in words instead of a dead button.
    fetch_block = ""
    if j.get("url") and not j["description"]:
        try:
            boards.check_url(j["url"])
        except boards.BoardError as exc:
            fetch_block = f'<p class="muted">Can\'t fetch this one: {esc(exc)} Paste it below instead.</p>'
        else:
            fetch_block = f"""
  <form method="post" action="/jobs/{job_id}/fetch">
    <button type="submit">Fetch from {esc(boards.host_of(j["url"]))}</button>
    <span class="muted">reads only the posting's published job data, and honours robots.txt</span>
  </form>"""

    referrals = None
    # find_referrals refuses a job with no company name; that's a missing field, not an error worth
    # showing, so the card simply doesn't render.
    if j.get("company"):
        try:
            referrals = cp.find_referrals(job_id)
        except CopilotError:
            referrals = None
    status_options = "".join(
        f'<option value="{s}"{" selected" if s == j["status"] else ""}>{s}</option>' for s in JOB_STATUSES
    )
    body = f"""
{banner_from_query(request)}
<div class="row" style="justify-content:space-between">
  <div><strong>{esc(j['title'])}</strong> <span class="muted">@ {esc(j['company'])} · {esc(j['location'])}</span></div>
  <span class="chip tier-{j['tier']}">{esc(j['tier'])} · {j['score'] if j['score'] is not None else '—'} ({esc(j['confidence'])} confidence)</span>
</div>
{flags}
<div class="card">
  <h2>Fit breakdown</h2>
  <div class="bars">{bars}</div>
  <ul class="check-list">{reasons}</ul>
</div>
{_sponsorship_card(j.get("sponsorship"))}
{_referrals_card(referrals)}
<div class="card">
  <h2>Skills</h2>
  <p class="muted">Matched</p>{matched or '<span class="muted">none yet</span>'}
  <p class="muted">Missing (required)</p>{missing_req or '<span class="muted">none</span>'}
  <p class="muted">Missing (preferred)</p>{missing_pref or '<span class="muted">none</span>'}
</div>
<div class="card">
  <h2>Description</h2>
  {description_block}
  {fetch_block}
  <form method="post" action="/jobs/{job_id}/description">
    <label>Paste or update the full description</label>
    <textarea name="description" placeholder="Paste the job description here to unlock skills-based scoring.">{esc(j['description'])}</textarea>
    <button type="submit" style="margin-top:10px">Save & rescore</button>
  </form>
</div>
<div class="card">
  <h2>Status</h2>
  <form method="post" action="/jobs/{job_id}/status">
    <input type="hidden" name="back" value="detail">
    <select name="status" data-autosubmit>{status_options}</select>
  </form>
  {f'<p class="muted"><a href="{esc(j["url"])}" target="_blank" rel="noopener noreferrer">Open posting</a></p>' if j.get('url') else ''}
</div>
"""
    return layout(request, title=j["title"], active="/jobs", body=body)


async def job_fetch_description(request: Request) -> Response:
    """Fetch this job's description from its board. The URL comes from the database, never here."""
    cp: Copilot = request.app.state.cp
    job_id = int(request.path_params["job_id"])
    try:
        result = cp.fetch_job_description(job_id)
    except CopilotError as exc:
        return error_redirect(f"/jobs/{job_id}", str(exc))
    if not result.get("fetched"):
        return error_redirect(f"/jobs/{job_id}", result.get("note", "nothing was fetched"))
    ok = f"Fetched {result['description_chars']} characters from {result['source']}"
    if result.get("tier_change"):
        ok += f" · {result['tier_change']}"
    return RedirectResponse(f"/jobs/{job_id}?ok={quote_plus(ok)}", status_code=303)


async def job_update_description(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    job_id = int(request.path_params["job_id"])
    form = await request.form()
    try:
        before = cp.get_job(job_id)
        after = cp.update_job(job_id, description=form.get("description", ""))
    except CopilotError as exc:
        return error_redirect(f"/jobs/{job_id}", str(exc))
    if before["tier"] != after["tier"]:
        return RedirectResponse(f"/jobs/{job_id}?ok=Rescored: {before['tier']} → {after['tier']}", status_code=303)
    return RedirectResponse(f"/jobs/{job_id}?ok=Saved", status_code=303)


async def job_update_status(request: Request) -> Response:
    """`back` is a fixed keyword, never reflected raw, so this never becomes an open redirect."""
    cp: Copilot = request.app.state.cp
    job_id = int(request.path_params["job_id"])
    form = await request.form()
    back = f"/jobs/{job_id}" if form.get("back") == "detail" else "/jobs"
    try:
        cp.update_job(job_id, status=form.get("status", "new"))
    except CopilotError as exc:
        return error_redirect(back, str(exc))
    return RedirectResponse(back, status_code=303)


# ---------------------------------------------------------------------------- Inbox

def _inbox_row(item: dict) -> str:
    flags = ' <span class="chip" style="border-color:var(--bad);color:var(--bad)">flag</span>' if item.get("flags") else ""
    status_options = "".join(
        f'<option value="{s}"{" selected" if s == item["status"] else ""}>{s}</option>' for s in INBOX_STATUSES
    )
    return f"""<tr>
  <td><strong>{esc(item['sender'] or 'unknown sender')}</strong>{flags}<div class="muted">{esc(item['subject'])}</div>
      <div class="external"><span class="src">preview, from {esc(item['source'])} · {esc(_age(item['received_at']))}</span>{esc(item['preview'])}</div></td>
  <td>{esc(item['category'])}</td>
  <td>{esc(item['priority'])}</td>
  <td>
    <form method="post" action="/inbox/{item['id']}/status">
      <select name="status" data-autosubmit>{status_options}</select>
    </form>
    {f'<a href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">Open conversation</a>' if item.get('url') else ''}
  </td>
</tr>"""


def inbox_list(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    status = request.query_params.get("status") or None
    if status and status not in INBOX_STATUSES:
        status = None
    rows = cp.list_inbox(status, None, 100)["items"]
    tabs = [("", "Open"), ("new", "New"), ("needs_reply", "Needs reply"), ("drafted", "Drafted"),
            ("replied", "Replied"), ("archived", "Archived")]
    tab_html = "".join(
        f'<a class="{"active" if (status or "") == t else ""}" href="/inbox{"?status=" + t if t else ""}">{esc(label)}</a>'
        for t, label in tabs
    )
    if not rows:
        table = '<p class="muted">No replies owed. New messages arrive when Claude ingests your notification emails.</p>'
    else:
        table = ('<table><thead><tr><th>Message</th><th>Category</th><th>Priority</th><th>Status</th></tr></thead>'
                  f'<tbody>{"".join(_inbox_row(i) for i in rows)}</tbody></table>')
    body = f'{banner_from_query(request)}<div class="tabs">{tab_html}</div><div class="card">{table}</div>'
    return layout(request, title="Inbox", active="/inbox", body=body)


async def inbox_update_status(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    item_id = int(request.path_params["item_id"])
    form = await request.form()
    try:
        cp.update_inbox_item(item_id, form.get("status", "new"))
    except CopilotError as exc:
        return error_redirect("/inbox", str(exc))
    return RedirectResponse("/inbox", status_code=303)


# ---------------------------------------------------------------------------- Data & privacy

def _register_card(register: dict) -> str:
    if not register["imported"]:
        return f"""
<div class="card">
  <h2>UK sponsor register</h2>
  <p class="muted">Not imported. Without it, UK jobs show sponsorship as unknown — never as "not a sponsor".</p>
  <ol>
    <li>Download the "Worker and Temporary Worker" CSV from
        <a href="{esc(register['source'])}" target="_blank" rel="noopener noreferrer">gov.uk</a></li>
    <li>Put it in <code>{esc(register['imports_folder'])}</code></li>
    <li>Run <code>career-copilot import-sponsors &lt;file name&gt;</code></li>
  </ol>
</div>"""
    stale = ('<span class="chip">PROVISIONAL — gov.uk republishes this roughly weekly; re-import it</span>'
             if register["stale"] else "")
    return f"""
<div class="card">
  <h2>UK sponsor register</h2>
  {stale}
  <p>{register['rows']:,} entries from <code>{esc(register['file'])}</code>, imported
     {esc(_age(register['imported_at']))}.</p>
  <p class="muted">{esc(register['licence'])}
     <a href="{esc(register['source'])}" target="_blank" rel="noopener noreferrer">Source</a></p>
</div>"""


# ---------------------------------------------------------------------------- Career path

def _course_links(find_courses: dict) -> str:
    """Course-search links. These are URLs this project builds, so linking them is safe."""
    return " · ".join(
        f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(name.replace("_", " "))}</a>'
        for name, url in (find_courses or {}).items()
    )


def _gaps_tab(cp: Copilot) -> str:
    gaps = cp.skill_gaps(12)["gaps"]
    if not gaps:
        return ('<p class="muted">No gaps measured yet. Add jobs with full descriptions — the skills half '
                'of the score is what these are derived from.</p>')
    rows = []
    for gap in gaps:
        tracked = "".join(f'<span class="chip">{esc(c["title"])} · {c["progress_pct"]}%</span>'
                          for c in gap.get("tracked_courses", []))
        examples = ", ".join(esc(j) for j in gap.get("example_jobs", [])[:3])
        rows.append(f"""
<div class="card">
  <div class="row" style="justify-content:space-between">
    <strong>{esc(gap["skill"])}</strong>
    <span class="chip">{esc(gap["status"])} · {gap["jobs"]} job(s)</span>
  </div>
  <div class="bars">{_bar("demand", min(1.0, gap["demand"] / max(1.0, gaps[0]["demand"])))}</div>
  {f'<p class="muted">Asked for by: {examples}</p>' if examples else ""}
  {tracked}
  <p class="muted">Find a course: {_course_links(gap.get("find_courses", {}))}</p>
</div>""")
    return "".join(rows)


def _plan_tab(cp: Copilot, weeks: int, hours: int) -> str:
    try:
        plan = cp.learning_plan(weeks, hours)
    except CopilotError as exc:
        return f'<div class="banner bad">{esc(exc)}</div>'
    week_options = "".join(f'<option value="{w}"{" selected" if w == weeks else ""}>{w} weeks</option>'
                           for w in (4, 8, 12, 16, 24))
    hour_options = "".join(f'<option value="{h}"{" selected" if h == hours else ""}>{h} h/week</option>'
                           for h in (2, 4, 6, 8, 10, 15))
    controls = f"""
<form method="get" action="/career" class="row">
  <input type="hidden" name="tab" value="plan">
  <select name="weeks" class="field-md" data-autosubmit>{week_options}</select>
  <select name="hours" class="field-md" data-autosubmit>{hour_options}</select>
</form>"""
    capacity = plan.get("capacity_hours") or 0
    planned = plan.get("hours_planned") or 0
    steps = "".join(f"""
<li><strong>{esc(s["skill"])}</strong> · week {esc(s["weeks"])} · {s["estimated_hours"]}h
  <div class="muted">{esc(s["why"])}</div>
  {f'<div class="muted">Show it with: {esc(s["proof_of_skill"])}</div>' if s.get("proof_of_skill") else ""}
  {f'<div class="muted">Would move {s["jobs_it_would_upgrade"]} job(s) up a tier</div>'
   if s.get("jobs_it_would_upgrade") else ""}
  <div class="muted">Find a course: {_course_links(s.get("find_courses", {}))}</div>
</li>""" for s in plan.get("steps", []))
    if not steps:
        return f'{controls}<p class="muted">Nothing to plan yet — add jobs with descriptions first.</p>'
    did_not_fit = "".join(f'<span class="chip">{esc(s)}</span>' for s in plan.get("did_not_fit", []))
    outcome = plan.get("if_you_complete_the_plan") or {}
    upgrades = "".join(
        f'<tr><td>{esc(u["title"])} <span class="muted">@ {esc(u["company"])}</span></td>'
        f'<td>{esc(u["from"])} → {esc(u["to"])}</td><td>{esc(u["score"])}</td></tr>'
        for u in outcome.get("upgrades", [])
    )
    outcome_block = ""
    if upgrades:
        outcome_block = f"""
<div class="card">
  <h2>If you finish this plan</h2>
  <p>{outcome.get("jobs_upgraded", 0)} job(s) would move up a tier.</p>
  <table><thead><tr><th>Job</th><th>Tier</th><th>Score</th></tr></thead><tbody>{upgrades}</tbody></table>
</div>"""
    return f"""
{controls}
<div class="card">
  <h2>Capacity</h2>
  <div class="bars">{_bar("planned", min(1.0, planned / capacity) if capacity else None)}</div>
  <p class="muted">{planned} of {capacity} available hours planned over {plan.get("weeks")} weeks.</p>
  {f'<p class="muted">Did not fit: {did_not_fit}</p>' if did_not_fit else ""}
  {f'<p class="muted">{esc(plan["note"])}</p>' if plan.get("note") else ""}
</div>
<div class="card">
  <h2>Steps</h2>
  <p class="muted">Hours and tier movements below are a projection from today's stored jobs and your
     profile — not a promise.</p>
  <ul class="check-list">{steps}</ul>
</div>
{outcome_block}"""


def _courses_tab(cp: Copilot) -> str:
    courses = cp.list_courses()["courses"]
    rows = []
    for c in courses:
        options = "".join(f'<option value="{s}"{" selected" if s == c["status"] else ""}>{s}</option>'
                          for s in COURSE_STATUSES)
        overdue = (' <span class="chip" style="border-color:var(--bad);color:var(--bad)">overdue</span>'
                   if c["target_date"] and c["status"] != "completed"
                   and c["target_date"] < datetime.now(timezone.utc).date().isoformat() else "")
        rows.append(f"""
<tr>
  <td><strong>{esc(c["title"])}</strong>{overdue}
      <div class="muted">{esc(c["skill"])}{" · " + esc(c["provider"]) if c["provider"] else ""}
      {" · due " + esc(c["target_date"]) if c["target_date"] else ""}</div></td>
  <td>
    <div class="row">
      <form method="post" action="/career/courses/{c["id"]}">
        <select name="status" data-autosubmit>{options}</select>
      </form>
      <form method="post" action="/career/courses/{c["id"]}" class="row">
        <input type="text" name="progress_pct" value="{c["progress_pct"]}" inputmode="numeric"
               class="field-sm" aria-label="progress percent for {esc(c["title"])}">
        <button type="submit" class="secondary">Save</button>
      </form>
    </div>
  </td>
</tr>""")
    table = (f'<table><thead><tr><th>Course</th><th>Status &amp; progress</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>') if rows else \
        '<p class="muted">No courses tracked yet.</p>'
    return f"""
<div class="card">{table}
  <p class="muted">Setting progress to 100 marks a course completed; any progress above 0 moves it
     out of "planned".</p>
</div>
<form method="post" action="/career/courses" class="card">
  <h2>Track a course</h2>
  <label>Skill</label><input type="text" name="skill" required>
  <label>Title</label><input type="text" name="title" required>
  <label>Provider (optional)</label><input type="text" name="provider">
  <label>URL (optional)</label><input type="text" name="url" placeholder="https://…">
  <label>Target date (optional)</label><input type="text" name="target_date" placeholder="2026-12-31">
  <button type="submit" style="margin-top:10px">Add course</button>
</form>"""


def career_path(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    tab = request.query_params.get("tab", "gaps")
    if tab not in ("gaps", "plan", "courses"):
        tab = "gaps"
    weeks = _int_param(request, "weeks", 12, 1, 52)
    hours = _int_param(request, "hours", cp.profile.hours_per_week, 1, 60)
    tabs = [("gaps", "Skill gaps"), ("plan", "Learning plan"), ("courses", "Courses")]
    tab_html = "".join(f'<a class="{"active" if t == tab else ""}" href="/career?tab={t}">{esc(label)}</a>'
                       for t, label in tabs)
    if tab == "gaps":
        content = _gaps_tab(cp)
    elif tab == "plan":
        content = _plan_tab(cp, weeks, hours)
    else:
        content = _courses_tab(cp)
    body = f'{banner_from_query(request)}<div class="tabs">{tab_html}</div>{content}'
    return layout(request, title="Career path", active="/career", body=body)


async def career_add_course(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    form = await request.form()
    try:
        cp.add_course(form.get("skill", ""), form.get("title", ""), form.get("provider", ""),
                      form.get("url", ""), form.get("target_date", ""))
    except CopilotError as exc:
        return error_redirect("/career?tab=courses", str(exc))
    return RedirectResponse("/career?tab=courses&ok=Course+added", status_code=303)


async def career_update_course(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    course_id = int(request.path_params["course_id"])
    form = await request.form()
    raw = (form.get("progress_pct") or "").strip()
    try:
        progress = int(raw) if raw else None
    except ValueError:
        return error_redirect("/career?tab=courses", "progress must be a whole number between 0 and 100")
    # Status and progress arrive from separate forms on purpose: update_course only applies its
    # "100% means completed" rule when no status is supplied, so sending both would silently
    # suppress it and contradict what the page tells you.
    try:
        updated = cp.update_course(course_id, status=form.get("status") or None, progress_pct=progress)
    except CopilotError as exc:
        return error_redirect("/career?tab=courses", str(exc))
    ok = updated.get("tip") or "Course updated"
    return RedirectResponse(f"/career?tab=courses&ok={quote_plus(ok)}", status_code=303)


# ---------------------------------------------------------------------------- Activity

def activity(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    limit = _int_param(request, "limit", 100, 1, 500)
    entries = cp.audit_log(limit)["entries"]
    rows = "".join(f"""
<tr>
  <td>{esc(_age(e["ts"]))}<div class="muted">{esc(e["ts"])}</div></td>
  <td><span class="chip">{esc(e["actor"])}</span></td>
  <td>{esc(e["action"])}</td>
  <td>{esc(e["object_ref"] or "—")}</td>
  <td><code class="muted">{esc(json.dumps(e["details"], ensure_ascii=False))}</code></td>
</tr>""" for e in entries)
    table = (f'<table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Object</th><th>Detail</th>'
             f'</tr></thead><tbody>{rows}</tbody></table>') if rows else \
        '<p class="muted">Nothing recorded yet.</p>'
    body = f"""
{banner_from_query(request)}
<p class="muted">Every action this copilot takes, and every approval you make, in the order it happened.
   The log is append-only — enforced by the database itself, so neither Claude nor this page can edit
   or delete an entry.</p>
<div class="card">{table}</div>"""
    return layout(request, title="Activity", active="/activity", body=body)


def data_privacy(request: Request) -> HTMLResponse:
    cp: Copilot = request.app.state.cp
    status = cp.status()
    purge_forms = "".join(f"""
<form method="post" action="/data/purge" class="card" data-confirm-text="{esc('DELETE' if what == 'all' else what)}">
  <strong>{esc(what)}</strong>{' <span class="muted">(everything)</span>' if what == 'all' else ''}
  <p class="muted">Type "{esc('DELETE' if what == 'all' else what)}" to confirm — this cannot be undone.</p>
  <input type="hidden" name="what" value="{esc(what)}">
  <input type="text" name="confirm" data-confirm-input autocomplete="off">
  <button type="submit" class="danger" data-confirm-submit disabled style="margin-top:8px">Delete {esc(what)}</button>
</form>""" for what in PURGE_CHOICES)
    body = f"""
{banner_from_query(request)}
<div class="card">
  <h2>Where your data lives</h2>
  <p>Profile: <code>{esc(status['profile_file'])}</code></p>
  <p>Imports: <code>{esc(status['imports_folder'])}</code></p>
  <p>Retention for inbox previews and news: {status['retention_days']} days — change it in
     <code>profile.toml</code> (editing it here is planned for a later phase).</p>
</div>
<div class="card">
  <h2>What leaves this machine</h2>
  <p>This database and everything in it stay on this machine. The text you and Claude work on in a chat
     is sent to Claude as part of that conversation. Feed requests go only to the RSS/Atom URLs you listed.
     Gmail sync (if connected) reads only mail from a fixed sender allowlist, read-only.
     <strong>Nothing is ever sent to LinkedIn by this app or the MCP server</strong> — every action is a
     draft you copy and do yourself.</p>
</div>
<div class="card">
  <h2>Counts</h2>
  <p>Jobs: {sum(status['jobs_by_tier'].values())} · Inbox open: {status['inbox_open']} ·
     Connections imported: {status['connections_imported']} ·
     Profile export imported: {'yes' if status['profile_snapshot_imported'] else 'no'}</p>
</div>
{_register_card(cp.sponsor_register_status())}
<h2>Delete data</h2>
<div class="grid">{purge_forms}</div>
"""
    return layout(request, title="Data & privacy", active="/data", body=body)


async def data_purge(request: Request) -> Response:
    cp: Copilot = request.app.state.cp
    form = await request.form()
    what = form.get("what", "")
    if what not in PURGE_CHOICES:
        return error_redirect("/data", "unknown category")
    expected = "DELETE" if what == "all" else what
    if form.get("confirm", "") != expected:
        return error_redirect("/data", f'type "{expected}" to confirm deleting {what}')
    try:
        cp.purge(what)
    except CopilotError as exc:
        return error_redirect("/data", str(exc))
    return RedirectResponse(f"/data?ok=Deleted+{what}", status_code=303)


# ---------------------------------------------------------------------------- auth & security

def _security_headers(response: Response, port: int) -> None:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"


class SecurityMiddleware(BaseHTTPMiddleware):
    """Same-origin only, one-time launch token, idle session lock. See module docstring."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        state = request.app.state
        path = request.url.path

        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in state.allowed_origins:
                return PlainTextResponse("Origin mismatch — request blocked.", status_code=403)

        if path == "/login":
            response = await call_next(request)
            _security_headers(response, state.port)
            return response
        if path.startswith("/static/"):
            response = await call_next(request)
            _security_headers(response, state.port)
            return response

        sid = request.cookies.get(SESSION_COOKIE)
        now = time.monotonic()
        sessions: dict[str, float] = state.sessions
        if not sid or sid not in sessions or now - sessions[sid] > IDLE_TIMEOUT_SECONDS:
            sessions.pop(sid, None)
            if path == "/locked":
                response = await call_next(request)
            else:
                response = RedirectResponse("/locked", status_code=303)
            _security_headers(response, state.port)
            return response
        sessions[sid] = now
        response = await call_next(request)
        _security_headers(response, state.port)
        return response


def login(request: Request) -> Response:
    state = request.app.state
    token = request.query_params.get("token", "")
    if state.launch_token_used or not token or not secrets.compare_digest(token, state.launch_token):
        return PlainTextResponse(
            "This launch link is invalid or was already used. Run `career-copilot console` again.",
            status_code=403,
        )
    if time.monotonic() - state.launch_token_created > LAUNCH_TOKEN_TTL_SECONDS:
        return PlainTextResponse("This launch link has expired. Run `career-copilot console` again.", status_code=403)
    state.launch_token_used = True
    sid = secrets.token_urlsafe(32)
    state.sessions[sid] = time.monotonic()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="strict", secure=False, path="/")
    return response


def locked(request: Request) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><title>Console locked</title>"
        "<body style='font:14px sans-serif;padding:40px;max-width:520px'>"
        "<h1>Console locked</h1>"
        "<p>Your session ended (15 minutes idle, or it was never started). There is no PIN yet in this "
        "release, so unlocking means running <code>career-copilot console</code> again from a terminal — "
        "that command prints a fresh one-time link.</p></body>",
        status_code=200,
    )


async def static_css(request: Request) -> Response:
    return Response(CSS, media_type="text/css")


async def static_js(request: Request) -> Response:
    return Response(JS, media_type="application/javascript")


# ---------------------------------------------------------------------------- app factory

def create_app(cp: Copilot, port: int) -> Starlette:
    # TrustedHostMiddleware compares only the hostname (it strips the port itself), so these are bare.
    allowed_hosts = ["127.0.0.1", "localhost"]
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    routes = [
        Route("/", today),
        Route("/login", login),
        Route("/locked", locked),
        Route("/static/app.css", static_css),
        Route("/static/app.js", static_js),
        Route("/review", review_list),
        Route("/review/{draft_id:int}", review_detail),
        Route("/review/{draft_id:int}/edit", review_edit_get, methods=["GET"]),
        Route("/review/{draft_id:int}/edit", review_edit_post, methods=["POST"]),
        Route("/review/{draft_id:int}/approve", review_approve, methods=["POST"]),
        Route("/review/{draft_id:int}/reject", review_reject, methods=["POST"]),
        Route("/review/{draft_id:int}/revoke", review_revoke, methods=["POST"]),
        Route("/review/{draft_id:int}/done", review_done, methods=["POST"]),
        Route("/jobs", jobs_board),
        Route("/jobs/{job_id:int}", job_detail),
        Route("/jobs/{job_id:int}/description", job_update_description, methods=["POST"]),
        Route("/jobs/{job_id:int}/fetch", job_fetch_description, methods=["POST"]),
        Route("/jobs/{job_id:int}/status", job_update_status, methods=["POST"]),
        Route("/career", career_path),
        Route("/career/courses", career_add_course, methods=["POST"]),
        Route("/career/courses/{course_id:int}", career_update_course, methods=["POST"]),
        Route("/activity", activity),
        Route("/inbox", inbox_list),
        Route("/inbox/{item_id:int}/status", inbox_update_status, methods=["POST"]),
        Route("/data", data_privacy),
        Route("/data/purge", data_purge, methods=["POST"]),
    ]
    middleware = [
        Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts, www_redirect=False),
        Middleware(SecurityMiddleware),
    ]
    app = Starlette(routes=routes, middleware=middleware)
    app.state.cp = cp
    app.state.port = port
    app.state.allowed_origins = allowed_origins
    app.state.sessions = {}
    app.state.launch_token = secrets.token_urlsafe(32)
    app.state.launch_token_used = False
    app.state.launch_token_created = time.monotonic()
    return app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(cp: Copilot | None = None, open_browser: bool = True) -> int:
    """Blocking entry point for `career-copilot console`."""
    import uvicorn

    cp = cp or Copilot()
    if not cp.profile.configured:
        print(f"No profile yet. Run `career-copilot init` and edit {cp.profile_path} first.")
        return 1
    port = free_port()
    app = create_app(cp, port)
    url = f"http://127.0.0.1:{port}/login?token={app.state.launch_token}"
    print("Copilot Console (localhost only — this link works once):")
    print(f"  {url}")
    print("If it expires or you close the tab, run `career-copilot console` again.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0
