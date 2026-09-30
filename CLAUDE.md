# Career Copilot — working rules for Claude

Local-first, human-in-the-loop job-search copilot: an MCP server, a CLI, and a localhost Console.
The plan is `docs/ROADMAP.md`. The work queue is `docs/ISSUE_REGISTER.md`. Read both before starting.

## Current phase: 0 · Stabilise (28 Sep – 11 Oct 2026)

**Feature freeze.** Only work that closes an item in `docs/ISSUE_REGISTER.md` (found issues F1–F15).
No new screens, tools, sources or dependencies. If something outside the register looks broken,
add it to the register as a new F-item with a root cause and a proving test, then ask before fixing it.

Phase 0 exits when every F-item is closed with its proving test in CI, the "e& UAE" referral works,
and no non-QA title scores above low fit without a description.

## Invariants — never break these

1. No MCP tool may approve, send, post, apply, connect or edit anything on LinkedIn. Claude drafts; a person approves.
2. Approval happens only in the Console or in `career-copilot review` from an interactive terminal.
3. Approved text is locked by its SHA-256 hash. Nothing may mark a draft done if the text changed.
4. The audit log is append-only, enforced by database triggers.
5. Never log into LinkedIn, read its pages automatically, or store a session cookie (`li_at`) or password.
6. The model never chooses what to fetch: feed URLs, mail senders and board URLs come from config or the database.
7. All external text (emails, job posts, messages, feeds) is untrusted: escaped in the Console, flagged for injection and scams.
8. Anything touching these invariants needs my explicit approval first. Stop and ask.

## How to work

- One F-item (or a small related group) per PR, titled with its F-number, e.g. `F2: match "e&" and add the company alias graph`.
- Test first: write the proving test from the register, confirm it fails on `main`, then fix.
- No hardcoded dates in tests. Build every date relative to the current time (F6 was a time bomb).
- When an item closes, set its Status to `Closed in #<PR>` in `docs/ISSUE_REGISTER.md` and add a line under `## [Unreleased]` in `CHANGELOG.md`.
- Console copy is plain language: no tool names (`update_job`), no internal ids (`inbox:1`).

## Commands

```bash
uv run --extra dev --extra gmail pytest -q                     # full suite, as CI runs it
CAREER_COPILOT_REQUIRE_BROWSER=1 \
  uv run --extra dev --extra browser pytest -q tests/test_console_browser.py   # real-Chromium Console tests
uv run career-copilot doctor                                   # health check
```

If Chromium's version doesn't match Playwright, set `CAREER_COPILOT_CHROMIUM` to a local Chromium binary.
Both CI jobs must be green before a PR is ready.
