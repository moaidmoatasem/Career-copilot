"""The Console in a real browser: every form clicked the way a person would, under the real headers.

TestClient can't see what a browser does with the Console's headers. It sends no Origin and applies no
Content-Security-Policy, and that gap hid two bugs: every form POST was refused (`Origin: null` under
`Referrer-Policy: no-referrer`), and every inline style was dropped (so every score bar read 100%).

The `ui` fixture fails any test whose page logged a browser error (which is where CSP refusals appear) or
sent a POST without this server's own Origin, so each test below re-checks both on top of its own assertion.

Needs the `browser` extra and a Chromium:
    uv run --extra dev --extra browser playwright install chromium
    uv run --extra dev --extra browser pytest tests/test_console_browser.py
CAREER_COPILOT_CHROMIUM points at a Chromium already on disk instead. Without a browser these tests
skip, unless CAREER_COPILOT_REQUIRE_BROWSER is set (as in CI), where they fail.
"""

from __future__ import annotations

import os
import re
import threading
import time
from urllib.parse import urlsplit

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from career_copilot import console, pin  # noqa: E402

from conftest import CLOSE_DESCRIPTION, MATCHED_DESCRIPTION  # noqa: E402
from test_emails import MESSAGE, MESSAGES, now_rfc2822  # noqa: E402

GOOD_PIN = "402917"
WRONG_PIN = "518204"


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            chromium = playwright.chromium.launch(executable_path=os.environ.get("CAREER_COPILOT_CHROMIUM") or None)
        except sync_api.Error as exc:
            # CI's browser job sets CAREER_COPILOT_REQUIRE_BROWSER, so a missing browser fails there
            # rather than quietly skipping the only tests that look at the Console the way a person does.
            if os.environ.get("CAREER_COPILOT_REQUIRE_BROWSER"):
                raise
            pytest.skip(f"no Chromium to drive ({str(exc).splitlines()[0]}); run `playwright install chromium`")
        yield chromium
        chromium.close()


@pytest.fixture
def live(cp):
    """The real app, served by uvicorn on a real port, over this test's fresh data."""
    port = console.free_port()
    app = console.create_app(cp, port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the Console did not start"
        time.sleep(0.02)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


class UI:
    def __init__(self, cp, app, base, page):
        self.cp, self.app, self.base, self.page = cp, app, base, page
        self.errors: list[str] = []
        self.posts: list = []

    @property
    def path(self) -> str:
        return urlsplit(self.page.url).path

    def go(self, path: str) -> None:
        self.page.goto(self.base + path)

    def click(self, locator) -> None:
        """Click something that submits a form, and wait for the page it leads to."""
        with self.page.expect_navigation():
            locator.click()

    def press(self, key: str) -> None:
        with self.page.expect_navigation():
            self.page.keyboard.press(key)

    def choose(self, locator, value: str) -> None:
        """Pick an option in a <select data-autosubmit>, which submits its form by script."""
        with self.page.expect_navigation():
            locator.select_option(value)

    def button(self, name: str):
        return self.page.get_by_role("button", name=name, exact=True)

    def banner(self) -> str:
        return " ".join(self.page.locator(".banner").all_inner_texts())

    def session_id(self) -> str:
        return next(c["value"] for c in self.page.context.cookies() if c["name"] == console.SESSION_COOKIE)


@pytest.fixture
def ui(browser, live, cp):
    app, base = live
    context = browser.new_context()
    page = context.new_page()
    ui = UI(cp, app, base, page)
    page.on("console", lambda msg: ui.errors.append(f"{ui.path}: {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: ui.errors.append(f"{ui.path}: {exc}"))
    page.on("request", lambda req: ui.posts.append(req) if req.method == "POST" else None)
    ui.go(f"/login?token={app.state.launch_token}")
    assert ui.path == "/"
    yield ui
    origins = {req.all_headers().get("origin") for req in ui.posts}
    context.close()
    assert not ui.errors, "the browser logged errors:\n" + "\n".join(ui.errors)
    assert origins <= {base}, f"a form POST carried Origin {origins - {base}}; the Console refuses anything else"


def _plain_draft(cp, text: str = "Writing up what we learned moving our regression suite to Playwright.") -> int:
    result = cp.draft_post(text, "idea")
    assert not result["checks"].get("claims_to_verify") and not result["checks"].get("outbound_links")
    return result["draft_id"]


def _pending(cp) -> list[dict]:
    return cp.list_drafts("pending", 50)["drafts"]


# ---------------------------------------------------------------------------- review

def test_review_page_shows_the_message_you_are_replying_to(ui):
    ui.cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822())
    item = ui.cp.list_inbox()["items"][0]
    draft_id = ui.cp.draft_message_reply(item["id"], "Thanks Sara, happy to talk on Tuesday.", "reply")["draft_id"]
    ui.go(f"/review/{draft_id}")
    context = ui.page.locator("#reply-context")
    assert context.is_visible()
    assert "Sara Ahmed" in context.inner_text()
    assert "opportunity in Dubai" in context.inner_text()
    assert "inbox:" not in ui.page.content()


def test_approve_needs_every_box_ticked_then_approves(ui):
    draft_id = ui.cp.draft_post("We reduced regression time by 40% last quarter. Details: https://example.com",
                                "idea")["draft_id"]
    ui.go(f"/review/{draft_id}")
    ui.button("Approve (a)").click()  # the checkboxes are `required`, so the browser won't submit yet
    assert ui.path == f"/review/{draft_id}" and ui.cp.get_draft(draft_id)["status"] == "pending"

    for box in ui.page.locator("#approve-form input[type=checkbox]").all():
        box.check()
    ui.page.fill("#approve-form input[name=note]", "checked the numbers")
    ui.click(ui.button("Approve (a)"))
    assert ui.cp.get_draft(draft_id)["status"] == "approved"
    assert ui.path == "/review"


def test_keyboard_moves_between_drafts_and_approves(ui):
    first = _plain_draft(ui.cp, "First note about moving our regression suite to Playwright.")
    second = _plain_draft(ui.cp, "Second note about moving our regression suite to Playwright.")
    ui.go(f"/review/{first}")
    ui.press("j")
    assert ui.path == f"/review/{second}"
    ui.press("k")
    assert ui.path == f"/review/{first}"
    ui.press("a")
    assert ui.cp.get_draft(first)["status"] == "approved"
    assert ui.cp.get_draft(second)["status"] == "pending"


def test_edit_then_approve_keeps_the_edit(ui):
    draft_id = _plain_draft(ui.cp)
    ui.go(f"/review/{draft_id}")
    ui.press("e")
    assert ui.path == f"/review/{draft_id}/edit"
    edited = "Edited: what moving our regression suite to Playwright taught the team."
    ui.page.fill("textarea[name=content]", edited)
    ui.click(ui.button("Save"))
    assert ui.path == f"/review/{draft_id}"
    ui.click(ui.button("Approve (a)"))
    draft = ui.cp.get_draft(draft_id)
    assert draft["status"] == "approved" and draft["content"] == edited


def test_reject_records_the_reason(ui):
    draft_id = _plain_draft(ui.cp)
    ui.go(f"/review/{draft_id}")
    ui.page.select_option("select[name=reason]", "tone")
    ui.page.fill("input[name=detail]", "too formal")
    ui.click(ui.button("Reject (r)"))
    draft = ui.cp.get_draft(draft_id)
    assert draft["status"] == "rejected" and draft["reviewer_note"] == "tone: too formal"


def test_revoke_and_mark_done(ui):
    draft_id = _plain_draft(ui.cp)
    ui.cp.approve_draft(draft_id)
    ui.go(f"/review/{draft_id}")
    ui.click(ui.button("Revoke (back to pending)"))
    assert ui.cp.get_draft(draft_id)["status"] == "pending"

    ui.cp.approve_draft(draft_id)
    ui.go(f"/review/{draft_id}")
    ui.click(ui.button("Mark as done"))
    assert ui.cp.get_draft(draft_id)["status"] == "executed"


# ---------------------------------------------------------------------------- approval PIN

def test_pin_is_asked_for_at_approval(ui):
    pin.set_pin(ui.cp.store, GOOD_PIN)
    draft_id = _plain_draft(ui.cp)
    ui.go(f"/review/{draft_id}")

    ui.page.keyboard.press("a")  # with the PIN field empty, `a` goes there instead of submitting
    assert ui.page.evaluate("document.activeElement.name") == "pin"
    assert ui.page.input_value("input[name=pin]") == ""

    ui.page.fill("input[name=pin]", WRONG_PIN)
    ui.press("Enter")
    assert "attempt(s) left" in ui.banner()
    assert ui.cp.get_draft(draft_id)["status"] == "pending"

    ui.page.fill("input[name=pin]", GOOD_PIN)
    ui.press("Enter")
    assert ui.cp.get_draft(draft_id)["status"] == "approved"


def test_pin_unlocks_an_idle_session(ui):
    pin.set_pin(ui.cp.store, GOOD_PIN)
    old = ui.session_id()
    ui.app.state.sessions[old] = time.monotonic() - console.IDLE_TIMEOUT_SECONDS - 1
    ui.go("/jobs")
    assert ui.path == "/locked"

    ui.page.fill("input[name=pin]", GOOD_PIN)
    ui.click(ui.button("Unlock"))
    assert ui.path == "/"
    assert ui.session_id() != old
    ui.go("/jobs")
    assert ui.path == "/jobs"


# ---------------------------------------------------------------------------- jobs & inbox

def test_pasting_a_description_rescores_the_job(ui):
    job = ui.cp.add_job("Senior QA Engineer", "Acme", "Dubai, United Arab Emirates", "")
    ui.go(f"/jobs/{job['id']}")
    ui.page.fill("textarea[name=description]", MATCHED_DESCRIPTION)
    ui.click(ui.button("Save & rescore"))
    updated = ui.cp.get_job(job["id"])
    assert updated["has_description"] and updated["tier"] == "matched"


def test_job_status_select_submits_itself(ui):
    job = ui.cp.add_job("Senior QA Engineer", "Acme", "Dubai, United Arab Emirates", "")
    ui.go(f"/jobs/{job['id']}")
    ui.choose(ui.page.locator(f"form[action='/jobs/{job['id']}/status'] select[name=status]"), "shortlisted")
    assert ui.cp.get_job(job["id"])["status"] == "shortlisted"


def test_fetch_fills_in_the_description(ui, monkeypatch):
    job = ui.cp.add_job("Senior QA Engineer", "Acme", "Cairo, Egypt", "https://www.bayt.com/en/job-7/")
    monkeypatch.setattr(type(ui.cp), "fetch_job_page",
                        staticmethod(lambda url: {"description": MATCHED_DESCRIPTION, "company": "", "location": ""}))
    ui.go(f"/jobs/{job['id']}")
    ui.click(ui.page.get_by_role("button", name=re.compile(r"^Fetch from")))
    assert ui.cp.get_job(job["id"])["has_description"]
    assert "bayt.com" in ui.banner()


def test_score_bars_are_as_wide_as_the_score(ui):
    job = ui.cp.add_job("Senior QA Engineer", "Acme", "Dubai, United Arab Emirates", "", CLOSE_DESCRIPTION)
    skills = round(ui.cp.get_job(job["id"])["analysis"]["breakdown"]["skills"] * 100)
    assert skills < 50  # a partial match, so a full-width bar would be the bug
    ui.go(f"/jobs/{job['id']}")
    fill = ui.page.locator(".bar-fill").first.bounding_box()["width"]
    track = ui.page.locator(".bar-track").first.bounding_box()["width"]
    assert abs(fill / track * 100 - skills) <= 3


def test_inbox_status_select_submits_itself(ui):
    ui.cp.ingest_email(MESSAGES, "Sara Ahmed sent you a new message", MESSAGE, now_rfc2822())
    item = ui.cp.list_inbox()["items"][0]
    ui.go("/inbox")
    ui.choose(ui.page.locator(f"form[action='/inbox/{item['id']}/status'] select[name=status]"), "archived")
    assert ui.cp.list_inbox(status="archived")["items"][0]["id"] == item["id"]


# ---------------------------------------------------------------------------- career

def test_add_a_course_and_complete_it(ui):
    ui.go("/career?tab=courses")
    ui.page.fill("input[name=skill]", "playwright")
    ui.page.fill("input[name=title]", "Playwright end to end")
    ui.click(ui.button("Add course"))
    assert "Course added" in ui.banner()
    course = ui.cp.list_courses()["courses"][0]

    form = ui.page.locator(f"form[action='/career/courses/{course['id']}']:has(input[name=progress_pct])")
    form.locator("input[name=progress_pct]").fill("100")
    ui.click(form.get_by_role("button", name="Save"))
    assert ui.cp.list_courses()["courses"][0]["status"] == "completed"


def test_plan_controls_replan(ui):
    ui.go("/career?tab=plan")
    ui.choose(ui.page.locator("select[name=weeks]"), "16")
    ui.choose(ui.page.locator("select[name=hours]"), "10")
    assert "weeks=16" in ui.page.url and "hours=10" in ui.page.url
    assert ui.page.locator("select[name=weeks]").input_value() == "16"


# ---------------------------------------------------------------------------- drafting screens

def test_drafting_screens_queue_drafts_and_approve_nothing(ui):
    from test_console import _connection, _job_for_network
    from test_news import RSS

    ui.go("/profile")
    ui.page.select_option("select[name=section]", "headline")
    ui.page.fill("textarea[name=text]", "Senior QA Engineer · test automation and API testing")
    ui.page.fill("input[name=rationale]", "match the titles I target")
    ui.click(ui.button("Queue draft for review"))
    assert ui.path.startswith("/review/")

    _job_for_network(ui.cp)
    _connection(ui.cp)
    ui.go("/network")
    ui.page.fill("textarea[name=text]", "Hi Nour, would you be open to a quick chat about the QA team at Globex?")
    ui.page.fill("input[name=rationale]", "first-degree connection there")
    ui.click(ui.button("Queue draft"))
    assert ui.path.startswith("/review/")

    ui.cp.fetch_feed = lambda url: RSS
    ui.go("/news")
    ui.click(ui.button("Refresh feeds"))
    assert "new item(s)" in ui.banner()
    card = ui.page.locator("form[action='/news/post']").first
    card.locator("textarea[name=text]").fill("My own take: flaky tests are a design smell, not bad luck.")
    card.locator("input[name=rationale]").fill("on topic for my audience")
    ui.click(card.get_by_role("button", name="Queue post for review"))
    assert ui.path.startswith("/review/")

    assert len(_pending(ui.cp)) == 3
    assert not ui.cp.list_drafts("approved", 50)["drafts"]


# ---------------------------------------------------------------------------- data & privacy

def test_purge_button_waits_for_the_typed_word(ui):
    _plain_draft(ui.cp)
    ui.go("/data")
    form = ui.page.locator("form[data-confirm-text='drafts']")
    delete = form.get_by_role("button", name="Delete drafts")
    assert delete.is_disabled()
    form.locator("input[name=confirm]").fill("draft")
    assert delete.is_disabled()
    form.locator("input[name=confirm]").fill("drafts")
    assert delete.is_enabled()
    ui.click(delete)
    assert not _pending(ui.cp)
    assert "Deleted drafts" in ui.banner()


# ---------------------------------------------------------------------------- every page

def test_every_page_renders_without_a_browser_error(ui):
    job = ui.cp.add_job("Senior QA Engineer", "Acme", "Dubai, United Arab Emirates", "", CLOSE_DESCRIPTION)
    draft_id = ui.cp.draft_post("We cut flaky tests by 40%. Details: https://example.com", "idea")["draft_id"]
    ui.cp.add_course("playwright", "Playwright end to end")
    paths = [path for path, _ in console.NAV_ITEMS] + [
        f"/jobs/{job['id']}", f"/review/{draft_id}", f"/review/{draft_id}/edit",
        "/career?tab=plan", "/career?tab=courses", "/review?tab=approved", "/locked",
    ]
    for path in paths:
        ui.go(path)
        assert not ui.errors, "\n".join(ui.errors)
