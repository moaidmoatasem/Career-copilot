# Career Copilot MCP

[![CI](https://github.com/moaidmoatasem/Career-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/moaidmoatasem/Career-copilot/actions/workflows/ci.yml)

A local MCP server that lets Claude run your LinkedIn-centred job search with you: it tiers jobs, plans the skills you need, triages recruiter messages, audits your profile, and ranks industry news. **It never logs into LinkedIn, never scrapes it, and never sends anything on its own.** Every message, post, application and profile edit is a draft until you approve it in your terminal and do it yourself on LinkedIn.

## Why it's built this way

LinkedIn offers no official API that lets a personal app read your inbox, feed or job recommendations. The tools that do this rely on your password or session cookie (`li_at`), which breaks LinkedIn's User Agreement and hands a third party full control of your account. Evading LinkedIn's bot detection (proxies, spoofed browser fingerprints) makes that worse, not safer. So this copilot uses routes that are yours to use:

| Data | Compliant source |
|---|---|
| New jobs | Job-alert emails read from your own mailbox — LinkedIn, Bayt, GulfTalent, NaukriGulf, Wuzzuf — and jobs you paste |
| Messages & invitations | LinkedIn notification emails, and conversations in your LinkedIn data export |
| Profile, skills, connections | LinkedIn's official "Get a copy of your data" export |
| Industry news | RSS/Atom feeds you choose, and LinkedIn digest emails |
| Job descriptions | The `JobPosting` structured data Bayt, GulfTalent, NaukriGulf and Wuzzuf publish for search engines (robots.txt honoured) — and, for LinkedIn jobs, whatever you paste |

## What it covers

| You asked for | What the copilot does |
|---|---|
| Matched / promising / close jobs | Deterministic scoring with reasons: skills 50%, title 25%, level 15%, location 10%, plus minimum skill coverage per tier. Jobs without a description are capped at *promising* until you add it. |
| Courses & career path | Ranks the skills blocking your jobs, builds a time-boxed plan, tracks courses, and shows how many jobs each skill would move up a tier. |
| Inbox | Prioritises recruiter messages, flags scams and injected instructions, drafts replies for approval. |
| Full profile | Audits headline, About, experience and skills against LinkedIn limits and the skills your target jobs ask for; proposes edits with a diff. |
| News & posts | Ranks news by your interests and skill gaps; drafts posts and comments for approval. |
| Referrals | Finds first-degree connections at a job's company (from your export) and drafts the ask. |
| UK sponsor licences | For UK jobs, checks the employer against the Home Office Register of Licensed Sponsors you imported, ranked rather than guessed. Company-level only — it never claims a role is sponsored. |

## Quick start (about 5 minutes)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Claude Desktop.

```bash
git clone https://github.com/moaidmoatasem/Career-copilot.git
cd Career-copilot
uv run career-copilot init            # creates ~/.career-copilot/{profile.toml, imports/, copilot.db}
```

### Installing into Claude Desktop

**One click.** Build the bundle and double-click it:

```bash
./scripts/build-mcpb.sh               # needs Node, only to run the packer
```

Then in Claude Desktop: **Settings → Extensions → Advanced settings → Install Extension…** and pick
`career-copilot.mcpb`. It asks where to keep your data and wires the rest up itself. The bundle declares
`server.type: "uv"`, so Claude Desktop uses uv and this project's `pyproject.toml` to resolve Python and
dependencies at install time — nothing is vendored into it, and no Python is bundled.

**Or by hand,** if you prefer to see the wiring:

`init` writes a starter `~/.career-copilot/profile.toml`. Open it and fill in your name, target
titles and locations, and the skills you can defend in an interview — scoring is only as good as
that file. It stays on your machine and is never committed.

`init` prints a config block. Open **Settings → Developer → Edit Config**, add it to `claude_desktop_config.json`, and fully quit and reopen Claude. The file lives at `%APPDATA%\Claude\claude_desktop_config.json` on Windows and `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS:

```json
{
  "mcpServers": {
    "career-copilot": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/Career-copilot", "run", "career-copilot-mcp"],
      "env": { "CAREER_COPILOT_HOME": "/ABSOLUTE/PATH/.career-copilot" }
    }
  }
}
```

Then use the server's **Daily LinkedIn triage** prompt, or just ask Claude to run your daily LinkedIn triage.

## Reading your job alerts

Two ways in. Connecting Gmail directly is the better one: alert emails go straight from Gmail into the
local database, so their contents never pass through the conversation.

```bash
uv sync --extra gmail            # optional Google client libraries
uv run career-copilot gmail-auth # one-time consent, opens a browser
uv run career-copilot sync       # read the last 7 days of alerts
```

You'll need a free Google OAuth client first: Google Cloud console → **APIs & Services** → enable the
**Gmail API** → **Credentials** → **Create credentials** → **OAuth client ID** → **Desktop app** →
download the JSON and save it as `~/.career-copilot/gmail-credentials.json`. Once connected, Claude can
run the sync itself with the `sync_gmail` tool.

Two limits are built into the sync and are not configurable by the model:

- **Scope is `gmail.readonly`.** It cannot send, label, modify or delete mail.
- **Senders are a fixed allowlist** — `linkedin.com`, `bayt.com`, `gulftalent.com`, `naukrigulf.com`,
  `wuzzuf.net`. Callers choose only a time window and a message cap, so an instruction injected into an
  email cannot widen the sync into the rest of your mailbox. Senders are re-checked locally after fetch.

Without Gmail connected, the copilot still works the old way: in a chat with your Gmail connector
enabled, Claude passes email text to `ingest_email`.

## Filling in job descriptions

A job alert gives you a title and a link. The description is what the skills half of the score is
computed from, so a job without one is capped at *promising* until you supply it.

```bash
uv run career-copilot fetch-descriptions          # tries the 5 newest jobs that lack one
uv run career-copilot fetch-descriptions --limit 20
```

Claude can do the same with `fetch_job_description` and `fetch_missing_descriptions`.

What it will and won't do:

- **Never LinkedIn.** LinkedIn URLs are refused by name, not merely left off a list. Those
  descriptions come from you pasting them — that is the trade for never scraping LinkedIn.
- **Four boards only** — Bayt, GulfTalent, NaukriGulf, Wuzzuf — https only. The model can't pass a
  URL: it names a job already in your database, and the URL comes from there.
- **robots.txt is checked first**, per host, with the same user-agent that does the fetching. If a
  board disallows the path, nothing is requested and the job is left alone.
- **Structured data only.** It reads the page's `JobPosting` JSON-LD — the data these boards
  publish so search engines can read it — and never harvests prose from the page. A page without it
  is reported so you can paste instead. Navigation and footers would otherwise end up scored as
  skills.

## Checking the install

```bash
uv run career-copilot doctor            # or --offline to skip network checks
```

One command that says whether this install actually works: data-folder and database permissions,
database integrity and the append-only audit triggers, whether `profile.toml` parses and still holds
template placeholders, whether the Gmail token is present with the read-only scope and still refreshes,
whether each job board's `robots.txt` allows reading job pages, whether your feeds are reachable, and
whether Claude Desktop has the server registered at a path that still exists.

It exits `1` if anything failed, so it works in a script. `--json` gives machine-readable output.
Nothing is created, repaired or sent — it only reads.

A board reported under **reachability** could not be contacted at all, which is a network or proxy
problem; a board reported under **robots.txt** answered and said no. Those need different fixes, so
they are reported differently.

## Daily workflow

1. **Triage** (Claude): runs `sync_gmail` (or passes emails to `ingest_email`), lists new jobs by tier and messages that need you, and drafts replies.
2. **Approve** (you, in the Console or a terminal):
   ```bash
   uv run career-copilot console   # opens a localhost-only approval page in your browser
   # or, at parity, from a shell:
   uv run career-copilot review    # approve, edit & approve, or reject each draft
   ```
   Numbers and links in a draft must be confirmed one by one before you can approve; safety flags need an
   explicit acknowledgement. Profile edits show a diff.
3. **Act** (you, on LinkedIn): paste and send/post/apply. Tell Claude it's done, mark it in the Console, or run `uv run career-copilot done <draft_id>`.

Other prompts: **Weekly career review**, **Job deep dive** (needs a job id), **Profile refresh**.

## Copilot Console

`career-copilot console` starts a small local web app — Today, Review, Jobs, Career path, Inbox,
Profile audit, Network, News, Activity, and Data & privacy — and opens it in your browser with a one-time link. It talks only to the local database; it never talks to
Claude and it never reaches LinkedIn. There is no "send", "post" or "apply" button anywhere in it: approving
a draft only moves it to *Ready to do*, where you copy the text and act on LinkedIn yourself.

- **Binds `127.0.0.1` only**, with a random free port, and the one-time launch link works once.
- The session locks after 15 minutes idle. There's no approval PIN yet (tracked as an open decision) — unlocking
  means running `career-copilot console` again for a fresh link.
- Host and Origin headers are checked on every request (closes DNS rebinding and cross-site requests), and a
  strict Content-Security-Policy allows only this server's own same-origin CSS/JS — no CDN, no inline script.
- Job descriptions and inbox previews are always shown as escaped plain text, never as HTML, and URLs inside
  them are never auto-linked.
- Fully keyboard-operable on the review screen: `a` approve, `e` edit, `r` focus the reject reason, `j`/`s`
  next draft, `k` previous, `?` for the shortcut list.
- `career-copilot review` (the terminal reviewer) stays available at parity — useful when the Console isn't
  running, or as the one surface a browser automation agent can't reach.
- The job page offers **Fetch** for boards the fetcher may read (a LinkedIn job explains why it can't
  instead of showing a dead button), and lists the people you already know at that company.
- **Career path** ranks the skills blocking your jobs, plans them against the hours you actually have, and
  tracks courses. Anything forward-looking there is labelled a projection rather than a promise.
- **Profile audit** lists findings by severity and what your target jobs keep asking for; proposed edits
  queue as drafts for Review.
- **Network** finds first-degree connections at a job's company from your export, and can draft the ask.
- **News** ranks your configured feeds, refreshes them, and drafts a post — your own take, not a summary.
- **Activity** is the audit trail, read-only over a log the database keeps append-only.

Known gaps, deliberately out of scope for now: no approval PIN, Settings/profile.toml editing, and no
phone mode.

For the profile audit, referrals and replies owed, request your export in LinkedIn (**Settings → Data privacy → Get a copy of your data**), drop the ZIP into `~/.career-copilot/imports/`, and ask Claude to import it.

## Security model

| Risk | Mitigation |
|---|---|
| Account takeover / restriction | No LinkedIn password, cookies or automation. Nothing touches LinkedIn's servers. |
| Prompt injection in emails, posts, job ads | External text is cleaned (hidden HTML, invisible characters) and flagged; the server instructions tell the model to treat it as data. |
| Agent acting without you | No approve/send tools exist in the MCP server or anywhere in the Console. Approval only works from an interactive terminal (`review` refuses piped input) or the Console, which binds `127.0.0.1` behind a one-time launch link and an idle-locked session. |
| Draft changed after approval | Approval stores a SHA-256 of the exact text; `mark_executed` refuses if it changed. |
| Data exfiltration | The server only fetches the https feeds listed in your profile; the model can't make it call arbitrary URLs. Gmail sync is read-only and limited to a fixed sender allowlist, so the model can't point it at the rest of your mailbox. Imports are confined to the `imports/` folder. Drafts with links or contact details are flagged. |
| Recruitment scams | Fee requests, Western Union, codes/OTPs, passport/bank requests are flagged. |
| Silent history rewriting | The audit log is append-only (enforced by database triggers). |
| Local disk exposure | Data folder `0700`, database `0600`. Use full-disk encryption on your laptop. |

## UK sponsor licences

If you're targeting UK roles, import the Home Office **Register of Licensed Sponsors** once and the
copilot will tell you, for each UK job, whether the employer holds a licence:

```bash
# Download the "Worker and Temporary Worker" CSV from gov.uk, then:
uv run career-copilot import-sponsors Worker_and_Temporary_Worker.csv
```

Put the CSV in `~/.career-copilot/imports/` first. Nothing downloads it for you — gov.uk republishes
it roughly weekly, so you control when it refreshes, and matches are marked provisional once your
copy is over 35 days old.

What the check does and doesn't say:

- It matches on **ranked** name similarity, not a substring hit. Where nothing is decisively ahead
  it shows you the candidates and asks, rather than picking. A query of "Wise" is genuinely
  ambiguous in the register and is treated that way.
- Licence routes that can't sponsor skilled work (Creative, Religious, Sportsperson, Charity,
  Ministers of Religion, Seasonal) are excluded before names are scored.
- **A licence is company-level.** It does not mean that employer will sponsor *this* role, and says
  nothing about whether you meet the salary or skill thresholds. The copilot never says "sponsored".
- An empty register or a job with no company name is reported as *unknown*, never as "not a sponsor".
- Non-UK jobs are untouched: no sponsorship information is computed or shown for them at all.

Register data: Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Register of Licensed Sponsors © Crown copyright, UK Home Office. It stays in your local database and
`career-copilot purge sponsors` removes it.

## Data, privacy, AI transparency

- Stored locally only: jobs, inbox previews (not full messages), news, drafts, courses, your profile snapshot, and connections **without** email addresses. Gmail sync stores message *ids* to avoid re-reading, never message bodies.
- Inbox previews and news older than `retention_days` (default 90) are deleted automatically. Delete anything anytime: `uv run career-copilot purge inbox|news|jobs|connections|snapshot|drafts|courses|all`.
- Text you and Claude work on is sent to Claude as part of your conversation. The copilot itself trains nothing.
- Drafts are AI-generated and can be wrong. The review screen says so, and you can edit before approving. This follows the spirit of LinkedIn's Developer AI Policy (label AI output, keep a human in the loop before anything is published).
- Other people's messages are processed for your own networking, kept minimal, and expire. If you're in scope of Egypt's PDPL or the GDPR for any of this data, keep it that way.
- Worth checking on LinkedIn itself: **Data for Generative AI Improvement** in your data privacy settings.

## Tools

Read-only: `get_status`, `get_gmail_status`, `list_jobs`, `get_job`, `find_referrals`, `check_sponsor_licence`, `list_inbox`, `get_skill_gaps`, `build_learning_plan`, `list_courses`, `audit_profile`, `get_news_digest`, `list_drafts`, `get_approved_actions`, `get_audit_log`.
Local writes: `ingest_email`, `import_linkedin_export`, `import_sponsor_register`, `add_job`, `update_job`, `update_inbox_item`, `add_course`, `update_course`, `draft_message_reply`, `draft_post`, `draft_comment`, `draft_application`, `propose_profile_edit`, `draft_outreach`, `revise_draft`, `withdraw_draft`, `mark_executed`.
Network: `refresh_news` (your configured feeds only), `sync_gmail` (read-only scope, allowlisted senders only), `fetch_job_description` / `fetch_missing_descriptions` (allowlisted job boards only, never LinkedIn).

## Limitations

- Email layouts change; parsing is heuristic. Anything unreadable is reported, and `add_job` always works.
- Job alerts carry titles, not descriptions. `career-copilot fetch-descriptions` fills them in for Bayt, GulfTalent, NaukriGulf and Wuzzuf jobs; for LinkedIn jobs you paste them yourself, which is the trade for not scraping.
- The skill taxonomy is tuned for QA, automation and AI-quality roles. Extend it under `[skills.aliases]`.
- The copilot sees what your emails and exports contain, not LinkedIn's live feed.
- LinkedIn character limits are built in as of 2026 and may change.

## Roadmap

- **Next:** an approval PIN and idle-lock unlock for the Console, editing `profile.toml` from the Data
  screen, and widening description coverage beyond the four Gulf boards.
- **Later:** an optional phone approval mode, official *Share on LinkedIn* posting for approved posts (OAuth,
  `w_member_social`; tokens last 60 days and need manual re-authorisation), more job boards, calendar-aware
  interview prep.

## Development

```bash
uv run --extra dev pytest        # or: pip install -e ".[dev]" && pytest
```

The suite covers parsing, scoring and tiers, safety flags, the approval integrity rules, export import and path confinement, learning plans, news, the MCP tool surface over the protocol, a real stdio server end to end, the Console's routes (session security, approve/edit/reject/revoke/done, job rescoring, purge), sponsor-register matching against the real collisions in it, and the Console's career, activity, profile audit, network and news screens. GitHub Actions runs all 283 tests on Python 3.11 and 3.12 for every push and pull request.

Changes are recorded in [CHANGELOG.md](CHANGELOG.md). Licensed under the [MIT License](LICENSE).
