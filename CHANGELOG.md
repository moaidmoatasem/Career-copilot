# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

[0.2.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.2.0
[0.1.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.1.0
