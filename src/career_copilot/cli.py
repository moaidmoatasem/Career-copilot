"""`career-copilot`: the human side. Approvals happen here, never inside the MCP server."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from .config import home_dir, profile_file, template_text
from .service import Copilot, CopilotError

_TTY = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def bold(text: str) -> str:
    return _c(text, "1")


def warn(text: str) -> str:
    return _c(text, "33")


def good(text: str) -> str:
    return _c(text, "32")


def _wrap(text: str, indent: str = "  ") -> str:
    return "\n".join(
        textwrap.fill(line, width=100, initial_indent=indent, subsequent_indent=indent) if line.strip() else ""
        for line in text.splitlines()
    )


def claude_config_snippet() -> dict:
    project_root = Path(__file__).resolve().parents[2]
    env = {"CAREER_COPILOT_HOME": str(home_dir())}
    if (project_root / "pyproject.toml").exists():
        server = {"command": "uv", "args": ["--directory", str(project_root), "run", "career-copilot-mcp"], "env": env}
    else:
        server = {"command": sys.executable, "args": ["-m", "career_copilot.server"], "env": env}
    return {"mcpServers": {"career-copilot": server}}


def cmd_init(_: argparse.Namespace) -> int:
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    (home / "imports").mkdir(exist_ok=True)
    for path in (home, home / "imports"):
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    profile = profile_file(home)
    if profile.exists():
        print(f"Profile already exists: {profile}")
    else:
        profile.write_text(template_text(), encoding="utf-8")
        try:
            os.chmod(profile, 0o600)
        except OSError:
            pass
        print(good(f"Created {profile}"))
    Copilot(home).store.close()
    print(f"Database ready in {home}")
    print(f"\n{bold('Next steps')}")
    print(f"  1. Edit your profile: {profile}")
    print(f"  2. Put your LinkedIn data export ZIP in: {home / 'imports'}")
    print("  3. Add this to Claude Desktop (Settings → Developer → Edit Config), then fully restart Claude:\n")
    print(textwrap.indent(json.dumps(claude_config_snippet(), indent=2), "     "))
    return 0


def _read_edit(original: str) -> str | None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(original)
            path = handle.name
        try:
            subprocess.run([*shlex.split(editor), path], check=False)
            edited = Path(path).read_text(encoding="utf-8").strip()
        finally:
            Path(path).unlink(missing_ok=True)
    else:
        print("Type the new text. Finish with a line containing only a single dot (.)")
        lines = []
        while True:
            line = input()
            if line.strip() == ".":
                break
            lines.append(line)
        edited = "\n".join(lines).strip()
    return edited if edited and edited != original.strip() else None


def _show_draft(cp: Copilot, draft: dict) -> None:
    checks = draft["checks"]
    print("\n" + bold(f"Draft #{draft['id']} · {draft['kind']}") + f"  ({draft['created_at']})")
    if draft["target"]:
        print(f"  target: {draft['target']}" + (f"  channel: {draft['channel']}" if draft["channel"] else ""))
    if draft["rationale"]:
        print(f"  why: {draft['rationale']}")
    limit = checks.get("limit")
    print(f"  length: {checks.get('chars')}" + (f" / {limit}" if limit else ""))
    print(warn("  AI-generated: read it fully and check for inaccuracies before approving."))
    if checks.get("claims_to_verify"):
        print(warn(f"  numbers to verify (real and traceable?): {', '.join(checks['claims_to_verify'])}"))
    if checks.get("outbound_links"):
        print(warn(f"  contains links: {', '.join(checks['outbound_links'])}"))
    if checks.get("contains_contact_details"):
        print(warn("  contains an email address or phone number"))
    for flag in checks.get("flags", []):
        print(warn(f"  flag [{flag['severity']}] {flag['type']}: {flag['excerpt']}"))
    if draft["kind"] == "profile_edit" and draft.get("original_content"):
        diff = difflib.unified_diff(
            draft["original_content"].splitlines(), draft["content"].splitlines(),
            fromfile="current profile", tofile="proposed", lineterm="",
        )
        print("  diff:")
        print(textwrap.indent("\n".join(diff), "    "))
    else:
        print("  text:")
        print(_wrap(draft["content"], "    "))


def cmd_review(_: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("review needs an interactive terminal: approvals must come from a person.", file=sys.stderr)
        return 2
    cp = Copilot()
    pending = cp.list_drafts("pending", 100)["drafts"]
    if not pending:
        print("No drafts waiting for review.")
        return 0
    print(bold(f"{len(pending)} draft(s) waiting for review"))
    for draft in reversed(pending):
        _show_draft(cp, draft)
        while True:
            choice = input(bold("\n[a]pprove  [e]dit & approve  [r]eject  [s]kip  [q]uit > ")).strip().lower()
            try:
                if choice == "a":
                    note = input("note (optional): ").strip()
                    approved = cp.approve_draft(draft["id"], note=note)
                    print(good("Approved. ") + cp.how_to_execute({**draft, "target_ref": draft["target"],
                                                                  "channel": approved["channel"]}))
                    break
                if choice == "e":
                    edited = _read_edit(draft["content"])
                    if edited is None:
                        print("No changes made.")
                        continue
                    approved = cp.approve_draft(draft["id"], edited_text=edited, note="edited by reviewer")
                    print(good("Edited and approved. ") + cp.how_to_execute({**draft, "target_ref": draft["target"],
                                                                             "channel": approved["channel"]}))
                    break
                if choice == "r":
                    cp.reject_draft(draft["id"], input("reason (optional): ").strip())
                    print("Rejected.")
                    break
                if choice == "s":
                    break
                if choice == "q":
                    return 0
            except CopilotError as exc:
                print(warn(f"Couldn't do that: {exc}"))
    print("\nWhen you've done an approved action on LinkedIn, tell Claude or run: career-copilot done <draft_id>")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    try:
        result = Copilot().mark_executed(args.draft_id, note=args.note or "", actor="human")
    except CopilotError as exc:
        print(warn(str(exc)), file=sys.stderr)
        return 1
    print(good(f"Draft #{result['draft_id']} marked as done."))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(Copilot().status(), indent=2, ensure_ascii=False))
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    result = Copilot().list_jobs(args.tier, None, args.limit)
    for job in result["jobs"]:
        description = "" if job["has_description"] else warn(" (no description)")
        print(f"#{job['id']:<4} {job['tier']:<9} {job['score']:>3}  {job['title']} @ {job['company']} · {job['location']}{description}")
    if not result["jobs"]:
        print("No jobs yet.")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    for entry in reversed(Copilot().audit_log(args.n)["entries"]):
        print(f"{entry['ts']}  {entry['actor']:<9} {entry['action']:<18} {entry['object_ref']:<12} {json.dumps(entry['details'], ensure_ascii=False)}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    if not args.yes:
        answer = input(f"Permanently delete '{args.what}' data from {home_dir()}? Type yes: ").strip().lower()
        if answer != "yes":
            print("Cancelled.")
            return 1
    print(json.dumps(Copilot().purge(args.what), indent=2))
    return 0


def cmd_claude_config(_: argparse.Namespace) -> int:
    print(json.dumps(claude_config_snippet(), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="career-copilot", description="Review drafts and manage Career Copilot data.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the profile, imports folder and database").set_defaults(func=cmd_init)
    sub.add_parser("review", help="approve, edit or reject pending drafts (interactive)").set_defaults(func=cmd_review)
    done = sub.add_parser("done", help="record that you did an approved action on LinkedIn")
    done.add_argument("draft_id", type=int)
    done.add_argument("--note", default="")
    done.set_defaults(func=cmd_done)
    sub.add_parser("status", help="show counts and reminders").set_defaults(func=cmd_status)
    jobs = sub.add_parser("jobs", help="list jobs by tier")
    jobs.add_argument("--tier", choices=["matched", "promising", "close", "low_fit", "excluded"])
    jobs.add_argument("--limit", type=int, default=30)
    jobs.set_defaults(func=cmd_jobs)
    log = sub.add_parser("log", help="show the audit log")
    log.add_argument("-n", type=int, default=30)
    log.set_defaults(func=cmd_log)
    purge = sub.add_parser("purge", help="delete stored data")
    purge.add_argument("what", choices=["inbox", "news", "jobs", "connections", "snapshot", "drafts", "courses", "all"])
    purge.add_argument("--yes", action="store_true")
    purge.set_defaults(func=cmd_purge)
    sub.add_parser("claude-config", help="print the Claude Desktop config snippet").set_defaults(func=cmd_claude_config)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CopilotError as exc:
        print(warn(str(exc)), file=sys.stderr)
        return 1
    except (BrokenPipeError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
