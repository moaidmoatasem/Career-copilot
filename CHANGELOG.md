# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/moaidmoatasem/Career-copilot/releases/tag/v0.1.0
