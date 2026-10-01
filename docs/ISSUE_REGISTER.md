# Issue register

Every known and predicted problem, with the fix and the test that closes it.
Exported 26 Sep 2026 from the Career Copilot roadmap doc. Update this file as issues close.

## Found issues

Fifteen issues, confirmed against `main` at 5bf7a12 on 26 Sep 2026. All land in Phase 0, highest priority first. Each closes only when its proving test is in CI.

| # | Issue | Root cause | Fix | Proving test | Priority | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | Tiers collapse on alert-only jobs, and non-QA roles leak in ("Senior Backend Engineer (Go)" 64 promising, "Senior Accountant" 51 close) | `scoring.score_job` title-only branch gives level and location 45% | Title-family gate: no description and a title outside the role family means low fit | Those two titles score low fit; "Senior QA Engineer, Dubai" stays promising | High | Closed in #17 |
| F2 | "e&" can never match, so referrals fail on e& UAE | `util.company_tokens` drops "&", "uae" and one-letter tokens, leaving nothing | Keep ampersand names as a token, fall back to exact normalised equality, add an alias graph (e&, Etisalat by e&, Emirates Telecommunications Group) | A connection at "e& UAE" is found for an "e& UAE" job and for "Etisalat by e&" | High | Closed in #18 |
| F3 | Alternatives half-parsed: "(or Selenium)" becomes a requirement, and "X, Y or Z" groups only Y and Z | `skills._alternative_groups` only links adjacent pairs joined by "or" or "/" | Parse coordinated lists: "X (or Y)", "X, Y or Z", "e.g. X, Y", "such as". Replaced by schema groups in Phase 3 | Phrasing suite, one case per pattern, including the e& description | High | Closed in #19 |
| F4 | Genuine Gulf offers flagged as scams: "visa fees covered by the company" is suspicious | `safety` scam rule matches "visa … fee" whoever pays | Only flag when the candidate is asked to pay ("pay", "transfer", "send", "deposit" near the fee). Treat "covered", "paid by", "we handle" as benign | Three sentences: covered-by-company is clean, handle-your-fee is clean, pay-via-Western-Union is flagged | High | Open |
| F5 | Recruiter message missed: "QA Lead opening at STC" filed as other, normal priority | `emails._RECRUITER` lacks "opening" and common Arabic terms | Add "opening", "we are looking for", "your profile", "role at", plus Arabic such as وظيفة and فرصة عمل | STC message becomes recruiter, high priority; an Arabic recruiter message too | High | Open |
| F6 | Time-bomb test fails from 26 Sep, and its XSS assertion no longer checks anything | `test_external_text_on_the_news_screen_is_escaped` hardcodes 2026-09-18 against a 7-day window | Use the current time | Test passes on any date and fails if escaping is removed | High (CI) | Closed in #16 |
| F7 | Review shows no context: the reply's original message isn't visible, and the target reads "inbox:1" | Console `review_detail` renders only the draft | Context pane with the original preview and sender name. Plain-language reminders, no tool names | Browser test asserts the original preview is visible on the review page | Medium | Open |
| F8 | "Mark as done" is available to Claude, so an injected instruction could hide approved, unsent drafts | `server.py` exposes `mark_executed` | Claude may only *report* done. The Console confirms it | MCP tool list has no way to reach the executed state alone | Medium | Open |
| F9 | Learning plan double-counts: "ci/cd" and "github actions" are separate steps | `learning.build_plan` ignores implications and alternatives | Collapse through `IMPLIES` and alternative groups | e& plan has one CI step | Medium | Open |
| F10 | Same job twice from different sources (Emirates NBD on Bayt and in Saved Jobs) | Dedupe keys on source and external id only | Likely-duplicate key (normalised company, title, country) shown to you to merge, never merged silently | Two sources produce one "likely duplicate" prompt | Medium | Open |
| F11 | Imports are not atomic | `import_linkedin_export` uses two transactions plus per-row upserts | One transaction per import | A failure injected mid-import leaves the database unchanged | Medium | Open |
| F12 | No schema versioning | `store.py` uses `CREATE TABLE IF NOT EXISTS` only | `PRAGMA user_version` with numbered migrations | An old database fixture migrates cleanly | Medium | Open |
| F13 | Feeds and boards fetched one at a time | Loop in `refresh_news` and the description fetcher | Thread pool with a per-host limit | Five fake feeds that each take 1 s finish in under 2 s | Low | Open |
| F14 | "Open posting" renders any stored URL as a live link | No scheme check on `href` | Allow http and https only | A `javascript:` URL renders no link | Low | Open |
| F15 | A title-only job shows "100", which reads as a perfect match | Numeric score shown without its confidence | Show "title match 100, skills unknown" until a description exists | Job list shows the label for title-only jobs | Low | Open |

## Predicted issues

These haven't happened yet. Each traces to a premortem cause (P1–P11 in `docs/ROADMAP.md`) or to a new component in the plan, and each ships with its prevention, not after the first incident.

| # | Predicted issue | Source | Prevention | Phase |
| --- | --- | --- | --- | --- |
| R1 | Email layouts change and parsing silently yields nothing | P5 | Per-source yield reporting, an alarm on zero yield, a fixture corpus of real emails refreshed monthly | 1 |
| R2 | Pasting stops and tiers fall back to title-only | P3 | Description resolver, share-to-copilot capture, description coverage on the Data screen | 1 |
| R3 | A leaked app password exposes the whole mailbox | Mail routes | Dedicated job-search mailbox by default, OS keychain storage, mailbox opened read-only, allowlisted senders only | 1 |
| R4 | The model invents requirements when extracting | Scoring v2 | Grounding check: every requirement must quote words present in the description, else it's dropped | 3 |
| R5 | The model is unavailable or rate-limited | Scoring v2 | Regex reader as fallback, extraction cache keyed by description hash, confidence label on affected jobs | 3 |
| R6 | An MCP SDK major version breaks the server (v2 already renamed FastMCP) | Platform | Pin below the next major, contract tests on the tool surface, a written upgrade playbook | 1 |
| R7 | Windows-only failures in paths, encoding or permissions | P1 | Windows job in CI, installer smoke test on a clean VM | 1 |
| R8 | Ticking claims becomes muscle memory | P10 | Flag ticks under 2 seconds, then move from tick boxes to evidence links | 2–3 |
| R9 | Scam rules over-flag legitimate MENA offers, or under-flag new scam forms | F4, market pack | Labelled scam and legitimate-offer corpus in the harness, with false-positive and false-negative rates tracked per release | 2 |
| R10 | Personal data about other people is kept longer than needed | Privacy, Egypt's Law 151 of 2020 and GDPR where it applies | Retention defaults, purge per category, no connection emails stored, a data summary in the wizard, export and delete-everything | Ongoing |
| R11 | Evidence links rot or point at private material | Evidence ledger | Last-checked date per link, a public-or-private flag, only public evidence on the shareable card | 3–4 |
| R12 | Duplicate merges lose data | F10 | Merge only with your confirmation, keep both source records under the merged job | 1 |
| R13 | Scope creep returns after the freeze lifts | P7 | Each new feature must name the metric it moves, one release a fortnight, register reviewed at each phase gate | All |
| R14 | Your own search ends before other users arrive | P6 | Recruit the first 20 users during Phase 1, design Phase 4 features for employed users too | 1–2 |
