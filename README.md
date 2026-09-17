# Career Copilot MCP

[![CI](https://github.com/moaidmoatasem/Career-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/moaidmoatasem/Career-copilot/actions/workflows/ci.yml)

A local MCP server that lets Claude run your LinkedIn-centred job search with you: it tiers jobs, plans the skills you need, triages recruiter messages, audits your profile, and ranks industry news. **It never logs into LinkedIn, never scrapes it, and never sends anything on its own.** Every message, post, application and profile edit is a draft until you approve it in your terminal and do it yourself on LinkedIn.

## Why it's built this way

LinkedIn offers no official API that lets a personal app read your inbox, feed or job recommendations. The tools that do this rely on your password or session cookie (`li_at`), which breaks LinkedIn's User Agreement and hands a third party full control of your account. Evading LinkedIn's bot detection (proxies, spoofed browser fingerprints) makes that worse, not safer. So this copilot uses routes that are yours to use:

| Data | Compliant source |
|---|---|
| New jobs | LinkedIn job-alert emails (plus Bayt, GulfTalent, NaukriGulf, Wuzzuf alerts) and jobs you paste |
| Messages & invitations | LinkedIn notification emails, and conversations in your LinkedIn data export |
| Profile, skills, connections | LinkedIn's official "Get a copy of your data" export |
| Industry news | RSS/Atom feeds you choose, and LinkedIn digest emails |

## What it covers

| You asked for | What the copilot does |
|---|---|
| Matched / promising / close jobs | Deterministic scoring with reasons: skills 50%, title 25%, level 15%, location 10%, plus minimum skill coverage per tier. Jobs without a description are capped at *promising* until you add it. |
| Courses & career path | Ranks the skills blocking your jobs, builds a time-boxed plan, tracks courses, and shows how many jobs each skill would move up a tier. |
| Inbox | Prioritises recruiter messages, flags scams and injected instructions, drafts replies for approval. |
| Full profile | Audits headline, About, experience and skills against LinkedIn limits and the skills your target jobs ask for; proposes edits with a diff. |
| News & posts | Ranks news by your interests and skill gaps; drafts posts and comments for approval. |
| Referrals | Finds first-degree connections at a job's company (from your export) and drafts the ask. |

## Quick start (about 5 minutes)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Claude Desktop.

```bash
git clone https://github.com/moaidmoatasem/Career-copilot.git
cd Career-copilot
uv run career-copilot init            # creates ~/.career-copilot/{profile.toml, imports/, copilot.db}
```

`init` writes a starter `~/.career-copilot/profile.toml`. Open it and fill in your name, target
titles and locations, and the skills you can defend in an interview — scoring is only as good as
that file. It stays on your machine and is never committed.

`init` prints a config block. In Claude Desktop open **Settings → Developer → Edit Config**, add it to `claude_desktop_config.json`, and fully quit and reopen Claude:

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

Then, in a chat with your Gmail connector enabled, use the server's **Daily LinkedIn triage** prompt, or just ask Claude to run your daily LinkedIn triage.

## Daily workflow

1. **Triage** (Claude): pulls LinkedIn and job-board emails from Gmail into `ingest_email`, lists new jobs by tier and messages that need you, and drafts replies.
2. **Approve** (you, in a terminal):
   ```bash
   uv run career-copilot review    # approve, edit & approve, or reject each draft
   ```
   Numbers in a draft are highlighted so you can confirm they're real and traceable. Profile edits show a diff.
3. **Act** (you, on LinkedIn): paste and send/post/apply. Tell Claude it's done, or run `uv run career-copilot done <draft_id>`.

Other prompts: **Weekly career review**, **Job deep dive** (needs a job id), **Profile refresh**.

For the profile audit, referrals and replies owed, request your export in LinkedIn (**Settings → Data privacy → Get a copy of your data**), drop the ZIP into `~/.career-copilot/imports/`, and ask Claude to import it.

## Security model

| Risk | Mitigation |
|---|---|
| Account takeover / restriction | No LinkedIn password, cookies or automation. Nothing touches LinkedIn's servers. |
| Prompt injection in emails, posts, job ads | External text is cleaned (hidden HTML, invisible characters) and flagged; the server instructions tell the model to treat it as data. |
| Agent acting without you | No approve/send tools exist in the MCP server. Approval only works from an interactive terminal (`review` refuses piped input). |
| Draft changed after approval | Approval stores a SHA-256 of the exact text; `mark_executed` refuses if it changed. |
| Data exfiltration | The server only fetches the https feeds listed in your profile; the model can't make it call arbitrary URLs. Imports are confined to the `imports/` folder. Drafts with links or contact details are flagged. |
| Recruitment scams | Fee requests, Western Union, codes/OTPs, passport/bank requests are flagged. |
| Silent history rewriting | The audit log is append-only (enforced by database triggers). |
| Local disk exposure | Data folder `0700`, database `0600`. Use full-disk encryption on your laptop. |

## Data, privacy, AI transparency

- Stored locally only: jobs, inbox previews (not full messages), news, drafts, courses, your profile snapshot, and connections **without** email addresses.
- Inbox previews and news older than `retention_days` (default 90) are deleted automatically. Delete anything anytime: `uv run career-copilot purge inbox|news|jobs|connections|snapshot|drafts|courses|all`.
- Text you and Claude work on is sent to Claude as part of your conversation. The copilot itself trains nothing.
- Drafts are AI-generated and can be wrong. The review screen says so, and you can edit before approving. This follows the spirit of LinkedIn's Developer AI Policy (label AI output, keep a human in the loop before anything is published).
- Other people's messages are processed for your own networking, kept minimal, and expire. If you're in scope of Egypt's PDPL or the GDPR for any of this data, keep it that way.
- Worth checking on LinkedIn itself: **Data for Generative AI Improvement** in your data privacy settings.

## Tools

Read-only: `get_status`, `list_jobs`, `get_job`, `find_referrals`, `list_inbox`, `get_skill_gaps`, `build_learning_plan`, `list_courses`, `audit_profile`, `get_news_digest`, `list_drafts`, `get_approved_actions`, `get_audit_log`.
Local writes: `ingest_email`, `import_linkedin_export`, `add_job`, `update_job`, `update_inbox_item`, `add_course`, `update_course`, `draft_message_reply`, `draft_post`, `draft_comment`, `draft_application`, `propose_profile_edit`, `draft_outreach`, `revise_draft`, `withdraw_draft`, `mark_executed`.
Network: `refresh_news` (your configured feeds only).

## Limitations

- Email layouts change; parsing is heuristic. Anything unreadable is reported, and `add_job` always works.
- Job alerts carry titles, not descriptions. Paste descriptions for the jobs you care about; that's what unlocks skill scoring.
- The skill taxonomy is tuned for QA, automation and AI-quality roles. Extend it under `[skills.aliases]`.
- The copilot sees what your emails and exports contain, not LinkedIn's live feed.
- LinkedIn character limits are built in as of 2026 and may change.

## Roadmap

- **Next:** direct Gmail sync with the read-only scope (no email bodies through the chat), a localhost approval page, and packaging as a one-click Claude Desktop extension.
- **Later:** official *Share on LinkedIn* posting for approved posts (OAuth, `w_member_social`; tokens last 60 days and need manual re-authorisation), more job boards, calendar-aware interview prep.

## Development

```bash
uv run --extra dev pytest        # or: pip install -e ".[dev]" && pytest
```

The suite covers parsing, scoring and tiers, safety flags, the approval integrity rules, export import and path confinement, learning plans, news, the MCP tool surface over the protocol, and a real stdio server end to end. GitHub Actions runs all 56 tests on Python 3.11 and 3.12 for every push and pull request.

Changes are recorded in [CHANGELOG.md](CHANGELOG.md). Licensed under the [MIT License](LICENSE).
