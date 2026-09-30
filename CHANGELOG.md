# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Your saved jobs come in with the export.** LinkedIn's data export carries every job you saved,
  and the importer was throwing all of them away — on a real export that was 341 jobs discarded by a
  tool whose whole job is scoring jobs. They are now read, scored and deduped against jobs already
  ingested from alert emails, so a job you saved and a job you were emailed stay one row. The export
  carries only title, company and link, so a saved job is capped at *promising* until you paste the
  description, exactly like any other job without one.
- `import_linkedin_export` takes **`saved_jobs_days`** (default 365) to bound how far back to read,
  and reports what it left out and why: jobs older than the window, and jobs LinkedIn exports without
  a title because the posting has since been taken down. Nothing is dropped silently.
- **`career-copilot import-export`**, so the LinkedIn export can be imported from a terminal. Every
  other import already had a CLI command; this one was reachable only by asking Claude, which meant a
  downloaded ZIP had no way in without Claude Desktop running.
- **An approval PIN for the Console.** `career-copilot pin set` makes every approval in the Console
  ask for a PIN, so a browser agent with a Console tab open can reach Approve but can't use it. Before
  this, `career-copilot review` was the only approval surface such an agent couldn't operate. The PIN is
  optional; without one the Console behaves exactly as before.
- **The idle lock can be unlocked.** After 15 minutes idle the same PIN unlocks the session, instead of
  the only way back being a fresh `career-copilot console` link. It unlocks only the browser that opened
  the one-time link, and issues a new session cookie when it does; a browser that never logged in still
  needs a new link.
- The PIN is set and cleared only from an interactive terminal (`pin set` / `pin clear` refuse piped
  input, like `review`). No MCP tool and no Console page can set, change or read it, so nothing driving
  the chat or the browser can pick its own. Only a salted scrypt hash is stored, in the local database.
- Five wrong PINs, at unlock or approval, end the Console session until you run `career-copilot
  console` again. Each guess is counted before it is checked, so guesses sent at once can't slip past the
  limit. Failures, the lockout and each unlock are written to the audit log, never with the PIN in them.
- The Data & privacy page says whether a PIN is set and how to change it; `career-copilot pin status`
  says the same from a terminal.
- **The Console is tested in a real browser.** A CI job drives it in Chromium and clicks every form a
  person would: approve (including the ticked-box and PIN checks), keyboard shortcuts, edit, reject,
  revoke, done, idle unlock, job and inbox status, courses and plan controls, the three drafting screens,
  and purge. Any browser error or a POST without the Console's own Origin fails the test. Both bugs fixed
  below would have been caught. Runs locally with the new `browser` extra.
- **A Settings screen edits `profile.toml`.** Candidate, targets, skills, tiers, learning hours,
  retention and news interests are now a form in the Console instead of a file you hand-edit. Every save
  is validated the same way the file is on load — the exact same `load_profile()` — so a bad value (an
  unknown seniority, tiers out of order, a non-numeric field) is rejected before anything on disk
  changes; the rejected save leaves `profile.toml` byte-for-byte as it was. `[[news.feeds]]` and
  `[skills.aliases]` aren't in the form yet (they need add/remove-row UI this pass didn't build) and
  round-trip through every save unedited.
- Saving from Settings keeps one `profile.toml.bak` — the file as it was immediately before your save —
  because the save rewrites the whole file and any comments in it, the template's or your own, are not
  kept. The page says so before every save. The write itself goes to a temp file, is validated, and only
  then atomically replaces the real file, so a crash mid-save can't leave a half-written `profile.toml`.
  The `0600` permission is kept on both the new file and the backup. The audit log records which field
  *names* changed, never the values — profile content otherwise never leaves the local database in raw
  form.

### Fixed

- **LinkedIn's sharded CSVs are read in full.** LinkedIn splits large tables across numbered files
  (`Saved Jobs.csv`, `Saved Jobs_1.csv`, …) and the reader kept only the first one it saw, so accounts
  large enough to be sharded silently lost the rest — connections and messages included, not just
  saved jobs. Shards are now folded onto the table they belong to and read together.
- **Console forms work in a real browser.** The Console sent `Referrer-Policy: no-referrer`, and under
  that policy browsers send `Origin: null` on form submissions, which the Console's own Origin check
  refused. So in Chrome every approve, reject, edit, purge and queue-draft button answered "Origin
  mismatch — request blocked". The tests never saw it because their client sends no Origin header. The
  policy is now `same-origin`, which still sends nothing to other sites, and a `null` Origin is still
  refused.
- **Score bars show the score.** The Console's Content-Security-Policy (`style-src 'self'`) makes
  browsers ignore inline `style=` attributes, and the bars set their width inline, so every fit and
  capacity bar drew at 100% — a job matching 27% of its skills looked like a perfect match. The same
  policy was silently dropping the red on flag, overdue and missing-skill chips, the layout of the
  review checklist, and spacing around buttons. Styling now lives in the stylesheet as classes, a test
  keeps `style=` out of the Console, and the favicon request no longer logs a 404.
- **Non-QA roles no longer leak in on title alone (F1).** A job from an alert email has no description,
  so level and location made up 45% of its score. That was enough to put "Senior Backend Engineer (Go)"
  in Dubai at 64 (*promising*) and "Senior Accountant" at 51 (*close*). Without a skills-based score, a
  title outside the role family your target titles name (QA, test, SDET, automation) is now low fit,
  with the reason shown. "Senior QA Engineer" in Dubai stays *promising*. Profiles whose target titles
  name none of those families aren't gated.
- **The News screen's escaping test works on any date (F6).** It stored its hostile item on a fixed
  date, 18 Sep 2026, and the News screen shows only the last 7 days. So from 26 Sep the item fell off
  the screen: the test failed, and its "no raw `<script>`" check passed without checking anything. The
  item is now dated when the test runs, and the test first asserts the item is on screen, so it fails
  if escaping is removed rather than passing on an empty page.

## [0.3.0] - 2026-09-19

### Added

- **Three more Console screens.** Profile audit, Network and News were reachable only through Claude or
  a terminal. Profile audit lists findings by severity and what your target jobs keep asking for; Network
  finds first-degree connections at a job's company and can draft the ask; News ranks your configured
  feeds, refreshes them, and drafts a post. Career path arrived separately in the same release.
- Every action on these screens **queues a pending draft and never approves one** — approval stays on
  Review, where the per-number and per-link confirmations and the flag acknowledgement live. A test
  drives all three drafting actions and asserts exactly three pending drafts, nothing approved or
  executed.
- Their empty states are the states a new install is actually in: no connections imported explains the
  LinkedIn data export; a job with no company renders the error as a banner rather than a traceback; a
  feed that fails names the feed and the error.
- **The Console reaches two features that already existed.** `fetch_job_description` and
  `find_referrals` shipped working, were exposed to Claude, and had no button anywhere — the only
  way to use either was to ask. The job page now offers both: a **Fetch** button (shown only when
  the job has a URL, has no description yet, and sits on a board the fetcher is allowed to read —
  a LinkedIn job gets the reason in words instead of a dead button), and a **People you know here**
  card listing first-degree connections from your export. The card informs; it never offers to
  contact anyone.
- **Career path screen** (`/career`): skill gaps ranked by demand with course-search links, a
  learning plan with weeks/hours controls, capacity against your available hours, what did not fit,
  and which jobs would move up a tier — labelled a projection, not a promise. Courses are tracked
  from the same screen.
- **Activity screen** (`/activity`): the full audit trail — who did what, when — read-only, with no
  write route, over a log the database itself keeps append-only.
- Course status and progress are submitted separately on purpose: `update_course` only applies its
  "100% means completed" rule when no status accompanies the progress, so sending both would have
  silently contradicted what the page tells you.
- **UK sponsor-licence check.** For UK-located jobs, `check_sponsor_licence` and the Console's job
  page say whether the employer appears on the Home Office Register of Licensed Sponsors. You
  import the register yourself: download the CSV from gov.uk, put it in the imports folder, and run
  `career-copilot import-sponsors <file>` (or the `import_sponsor_register` tool). Nothing
  downloads it for you, and the import date travels with every match.
- Name matching is ranked, not a substring hit: exact, legal-suffix-equivalent, leading-prefix and
  token-overlap tiers, with a candidate list when nothing is decisively ahead. It refuses to pick
  rather than pick wrongly — "Wise" is offered as a choice, never resolved to "Aaron Wise Limited".
  Licence routes that cannot sponsor skilled work (Creative, Religious, Sportsperson, Charity,
  Ministers of Religion, Seasonal) are excluded before names are scored, so the register's real
  `Wise | Religious Worker | High Wycombe` row can never be reported as the fintech.
- What the check will not say: never "sponsored", never that an employer will sponsor a given role,
  and never "not a sponsor" when the register simply hasn't been imported or the job has no company
  name — those are reported as unknown. Server instruction 6 holds the model to the same line.
  Matches are marked provisional once the import is over 35 days old.
- `geo.py` recognises the UK, so UK jobs score against a UK target location instead of falling
  through as "outside your target locations".
- `career-copilot purge sponsors` clears the register, and the Data & privacy page shows what was
  imported, when, and its Open Government Licence attribution.
- **Job descriptions from the Gulf boards.** `career-copilot fetch-descriptions`, and the
  `fetch_job_description` / `fetch_missing_descriptions` tools, fill in the descriptions that job
  alerts omit — the input the skills half of the score depends on, and the reason jobs without one
  are capped at *promising*. Fetched descriptions go through the same `update_job` path as pasted
  ones, so they are sanitised, flagged and re-scored identically.
- Four limits keep this inside what the project is willing to do: LinkedIn is refused by name with
  an explanation (its descriptions stay paste-only); only Bayt, GulfTalent, NaukriGulf and Wuzzuf
  are fetchable, https only; `robots.txt` is honoured per host with the fetching user-agent; and
  only the page's published `JobPosting` JSON-LD is read, never prose harvested from the page.
- The model cannot supply a URL to fetch — it names a stored job, and the URL comes from the
  database. Redirects are re-checked against the allowlist, and an unreadable `robots.txt` counts
  as disallowed.
- Fetching only fills blanks: a company or location already recorded by you or an alert email is
  never overwritten.
- **One-click install.** `manifest.json` makes this a Claude Desktop extension: build it with
  `./scripts/build-mcpb.sh` and double-click the resulting `.mcpb` instead of hand-editing
  `claude_desktop_config.json`. It declares `server.type: "uv"`, so Claude Desktop resolves Python and
  dependencies from the existing `pyproject.toml` at install time — nothing is vendored into the
  bundle and no Python ships inside it. The data folder is a prompted `user_config` option.
- `.mcpbignore` keeps personal data out of the distributed file. A bundle is packed from the working
  tree rather than from git, so `.gitignore` does not protect it: `profile.toml`, the database,
  `gmail-token.json`, `gmail-credentials.json`, `.env` and `imports/` are excluded again there, and a
  test asserts each pattern is present.
- Tests pin the manifest to reality: its version must equal `pyproject.toml`'s, its
  `compatibility.runtimes.python` must equal `requires-python`, and its declared `tools` array must
  match the live MCP tool surface exactly — so adding a tool without declaring it fails CI.
- **`career-copilot doctor`.** One command that checks whether an install actually works: runtime
  version, data-folder and database permissions, `PRAGMA integrity_check`, every table in the schema
  and both append-only audit triggers, whether `profile.toml` parses and whether template
  placeholders survive in it, the Gmail token's presence/permissions/scope and whether it still
  refreshes, each job board's `robots.txt`, feed reachability, and whether Claude Desktop has the
  server registered at a path that still exists. Exits `1` on any failure; `--json` for machine
  output, `--offline` to skip network checks. Read-only: it creates, repairs and sends nothing.
- `doctor` distinguishes a board it could not reach from a board that answered and disallowed job
  pages. `RobotFileParser` collapses both into "disallowed", which would report a blocked network as
  the board's decision; those need different fixes, so they get different messages.

## [0.2.0] - 2026-09-17

### Added

- **Copilot Console.** `career-copilot console` opens a localhost-only web app — Today, Review,
  Jobs, Inbox, Data & privacy — with a one-time launch link. It talks only to the local database:
  no route reaches Claude or LinkedIn, and (like the MCP server) it has no "send" capability
  anywhere in it. Numbers and links in a draft must be confirmed individually before it can be
  approved; safety flags need an explicit acknowledgement. The review screen is fully
  keyboard-operable (`a` approve, `e` edit, `r` reject, `j`/`k` next/previous, `?` for shortcuts).
  `career-copilot review` stays available at parity as the terminal-only alternative.
- Session security for the Console: binds `127.0.0.1` only, a single-use launch token exchanged
  for an HttpOnly/SameSite=Strict session cookie, a 15-minute idle lock, Host/Origin header
  checks against DNS rebinding and cross-site requests, and a strict same-origin
  Content-Security-Policy (no CDN, no inline script). External text (job descriptions, inbox
  previews) is always rendered as escaped plain text, never HTML, and URLs in it are never
  auto-linked.
- `drafts.revoke()` / `Copilot.revoke_draft()` send an approved-but-not-yet-done draft back to
  pending, and `Copilot.get_draft()` fetches one draft by id — both needed by the Console's
  Review screen, both human-only like approve/reject.
- **Read-only Gmail sync.** `career-copilot gmail-auth` connects Gmail with the
  `gmail.readonly` scope, and `career-copilot sync` (or the `sync_gmail` tool) reads recent
  job-alert mail straight into the local database, so message bodies no longer pass through the
  conversation. `get_gmail_status` reports whether it's connected and when it last ran.
- Two limits the model cannot change: the OAuth scope is read-only, and the Gmail query is built
  from a fixed sender allowlist (`linkedin.com`, `bayt.com`, `gulftalent.com`, `naukrigulf.com`,
  `wuzzuf.net`), with senders re-checked locally after fetch. Callers pass only a time window and
  a message cap, so an instruction injected into an email cannot widen the sync into the rest of
  the mailbox.
- Authorisation happens only in the CLI, where a person is present; the server can refresh an
  existing token but never mint one.
- `synced_messages` table stores Gmail message ids so repeat syncs are idempotent. Ids only — no
  senders, subjects or bodies.
- Google's client libraries are an optional extra (`uv sync --extra gmail`), imported lazily, so
  the rest of the copilot runs without them.

### Changed

- `ingest_email` and `sync_gmail` now share one storage path (`_store_parsed_email`), so both
  routes tier jobs, flag scams and dedupe identically.
- `starlette` and `uvicorn` (already pulled in transitively by `mcp`) are now direct dependencies,
  for the Console; `httpx` is a `dev` extra so its routes can be tested with Starlette's TestClient.
- CI also installs the `gmail` extra, so those paths are tested rather than skipped.
- `.gitignore` covers `gmail-credentials.json`, `gmail-token.json` and `.env`.
- README documents the Windows and macOS locations of `claude_desktop_config.json`.

## [0.1.0] - 2026-09-17

First release. A local MCP server for Claude Desktop that runs a LinkedIn-centred job search
without LinkedIn credentials, scraping, or any automated sending.

### Added

- **Jobs.** Parses job-alert emails from LinkedIn, Bayt, GulfTalent, NaukriGulf and Wuzzuf via
  `ingest_email`, and scores each role deterministically — skills 50%, title 25%, level 15%,
  location 10% — into *matched*, *promising* and *close* tiers with a reason for each. Jobs
  without a description are capped at *promising* until one is added.
- **Career path.** Ranks the skills blocking your target jobs, builds a time-boxed weekly plan
  against `hours_per_week`, tracks courses, and reports how many jobs each skill would move up
  a tier.
- **Inbox.** Prioritises recruiter messages, and flags recruitment scams (fee requests, wire
  transfers, OTP/passport/bank requests) and instructions hidden in email HTML.
- **Profile audit.** Checks headline, About, experience and skills against LinkedIn's character
  limits and the skills your target jobs ask for, proposing edits as before/after diffs and
  marking claims that need a source.
- **News and posts.** Ranks the RSS/Atom feeds listed in your profile by your interests and skill
  gaps (`refresh_news`), and drafts posts and comments for review.
- **Referrals.** Finds first-degree connections at a job's company from your LinkedIn data export
  and drafts the ask.
- **LinkedIn export import.** Reads the official "Get a copy of your data" archive for profile,
  skills, connections and conversations, confined to the `imports/` folder.
- **Approval workflow.** `career-copilot review` in an interactive terminal is the only way to
  approve a draft; it refuses piped input. `career-copilot done <draft_id>` records that you
  carried the action out yourself.
- **Safety model.** No MCP tool can send or approve anything. Approval stores a SHA-256 of the
  exact approved text and `mark_executed` refuses if it changed. Untrusted external text is
  sanitised and flagged. The audit log is append-only, enforced by database triggers. Outbound
  network access is limited to the feeds in your profile. The data directory is `0700` and the
  database `0600`.
- **Privacy.** Everything is stored locally; inbox previews and news older than `retention_days`
  (default 90) are deleted automatically, and `career-copilot purge` clears any category on
  demand. Connections are stored without email addresses. Drafts are labelled as AI-generated.
- **Packaging.** `career-copilot init` creates the data directory and prints a ready-to-paste
  Claude Desktop config block. 56 tests covering parsing, scoring, safety, approval integrity,
  export handling, learning plans, news, the MCP tool surface over the protocol, and a real
  stdio server end to end.

[0.3.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.3.0
[0.2.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.2.0
[0.1.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.1.0
