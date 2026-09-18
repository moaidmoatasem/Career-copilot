from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from career_copilot import boards, doctor
from career_copilot.service import Copilot

from conftest import PROFILE

ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"
ROBOTS_DENY = "User-agent: *\nDisallow: /\n"


def statuses(checks, title_contains: str) -> list[str]:
    return [c.status for c in checks if title_contains.lower() in c.title.lower()]


def only(checks, title_contains: str):
    matches = [c for c in checks if title_contains.lower() in c.title.lower()]
    assert len(matches) == 1, f"expected one {title_contains!r} check, got {[c.title for c in matches]}"
    return matches[0]


@pytest.fixture
def healthy(tmp_path, monkeypatch) -> Path:
    """A home that `init` would have produced."""
    monkeypatch.setenv("CAREER_COPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("CAREER_COPILOT_PROFILE", raising=False)
    (tmp_path / "profile.toml").write_text(PROFILE, encoding="utf-8")
    os.chmod(tmp_path / "profile.toml", 0o600)
    (tmp_path / "imports").mkdir(exist_ok=True)
    os.chmod(tmp_path, 0o700)
    Copilot(tmp_path).store.close()
    return tmp_path


def fake_urlopen(body: str | None = None, error: Exception | None = None):
    class _Response:
        def __init__(self, text: str):
            self._text = text.encode()

        def read(self, _size: int = -1) -> bytes:
            return self._text

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _open(request, timeout=None):  # noqa: ARG001
        if error is not None:
            raise error
        return _Response(body or "")

    return _open


# ---------------------------------------------------------------- schema parsing


def test_schema_names_parses_tables_and_triggers():
    """Regression: triggers are declared `NAME BEFORE UPDATE ON ...`, not `NAME (`."""
    tables = doctor._schema_names("TABLE")
    triggers = doctor._schema_names("TRIGGER")
    assert "jobs" in tables and "audit_log" in tables and "synced_messages" in tables
    assert triggers == ["audit_log_no_update", "audit_log_no_delete"]
    assert all(" " not in name for name in tables + triggers)


# ---------------------------------------------------------------- filesystem


def test_healthy_install_has_no_failures(healthy):
    checks = doctor.run_checks(healthy, network=False)
    assert [c for c in checks if c.failed] == []


def test_missing_home_is_a_failure(tmp_path):
    checks = doctor.check_data_dir(tmp_path / "nope")
    assert only(checks, "Data folder").status == doctor.FAIL


def test_loose_data_folder_permissions_warn(healthy):
    os.chmod(healthy, 0o755)
    assert only(doctor.check_data_dir(healthy), "Data folder permissions").status == doctor.WARN


def test_missing_imports_folder_warns(healthy):
    (healthy / "imports").rmdir()
    assert only(doctor.check_data_dir(healthy), "Imports folder").status == doctor.WARN


# ---------------------------------------------------------------- database


def test_healthy_database_passes_every_check(healthy):
    checks = doctor.check_database(healthy)
    assert only(checks, "Database integrity").status == doctor.OK
    assert only(checks, "Database schema").status == doctor.OK
    assert only(checks, "append-only").status == doctor.OK


def test_world_readable_database_is_a_failure(healthy):
    os.chmod(healthy / "copilot.db", 0o644)
    assert only(doctor.check_database(healthy), "Database permissions").status == doctor.FAIL


def test_missing_database_warns_rather_than_crashing(tmp_path):
    assert only(doctor.check_database(tmp_path), "Database").status == doctor.WARN


def test_missing_table_is_a_failure(healthy):
    conn = sqlite3.connect(healthy / "copilot.db")
    conn.execute("DROP TABLE synced_messages")
    conn.commit()
    conn.close()
    assert only(doctor.check_database(healthy), "Database schema").status == doctor.FAIL


def test_dropped_audit_trigger_is_a_failure(healthy):
    conn = sqlite3.connect(healthy / "copilot.db")
    conn.execute("DROP TRIGGER audit_log_no_delete")
    conn.commit()
    conn.close()
    assert only(doctor.check_database(healthy), "append-only").status == doctor.FAIL


def test_doctor_never_creates_a_database(tmp_path):
    doctor.check_database(tmp_path)
    assert not (tmp_path / "copilot.db").exists()


def test_work_state_counts_are_reported(healthy):
    cp = Copilot(healthy)
    cp.add_job("Senior QA Engineer", url="https://wuzzuf.net/jobs/p/1")
    cp.draft_post("A post about test automation that is long enough to be a draft.", "rationale")
    cp.store.close()
    checks = doctor.check_database(healthy)
    assert "1 pending" in only(checks, "Drafts waiting").detail
    assert only(checks, "without a description").status == doctor.WARN


# ---------------------------------------------------------------- profile


def test_missing_profile_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("CAREER_COPILOT_PROFILE", raising=False)
    assert only(doctor.check_profile(tmp_path), "Profile").status == doctor.FAIL


def test_unparseable_profile_is_a_failure(healthy):
    (healthy / "profile.toml").write_text("this is not = valid = toml", encoding="utf-8")
    assert only(doctor.check_profile(healthy), "Profile").status == doctor.FAIL


def test_untouched_template_warns(healthy):
    (healthy / "profile.toml").write_text(
        PROFILE.replace('name = "Test User"', 'name = "Your Name"'), encoding="utf-8"
    )
    check = only(doctor.check_profile(healthy), "Profile is yours")
    assert check.status == doctor.WARN and "Your Name" in check.detail


def test_a_filled_in_profile_does_not_warn(healthy):
    assert only(doctor.check_profile(healthy), "Profile is yours").status == doctor.OK


def test_no_target_titles_is_a_failure(healthy):
    (healthy / "profile.toml").write_text(
        PROFILE.replace(
            'titles = ["Senior QA Engineer", "Senior Test Automation Engineer", "QA Lead"]', "titles = []"
        ),
        encoding="utf-8",
    )
    assert only(doctor.check_profile(healthy), "Target titles").status == doctor.FAIL


# ---------------------------------------------------------------- gmail


def test_gmail_not_connected_warns_but_does_not_fail(healthy):
    checks = doctor.check_gmail(healthy, network=False)
    assert only(checks, "Gmail connection").status == doctor.WARN
    assert not any(c.failed for c in checks)


def test_readable_gmail_token_is_a_failure(healthy):
    token = healthy / "gmail-token.json"
    token.write_text(json.dumps({"scopes": [doctor.gmail.SCOPE]}), encoding="utf-8")
    os.chmod(token, 0o644)
    assert only(doctor.check_gmail(healthy, network=False), "Gmail token permissions").status == doctor.FAIL


def test_a_wider_gmail_scope_is_a_failure(healthy):
    token = healthy / "gmail-token.json"
    token.write_text(json.dumps({"scopes": ["https://mail.google.com/"]}), encoding="utf-8")
    os.chmod(token, 0o600)
    check = only(doctor.check_gmail(healthy, network=False), "Gmail scope")
    assert check.status == doctor.FAIL and "gmail.readonly" in check.detail


def test_correct_gmail_scope_passes(healthy):
    token = healthy / "gmail-token.json"
    token.write_text(json.dumps({"scopes": [doctor.gmail.SCOPE]}), encoding="utf-8")
    os.chmod(token, 0o600)
    assert only(doctor.check_gmail(healthy, network=False), "Gmail scope").status == doctor.OK


# ---------------------------------------------------------------- boards


def test_boards_are_skipped_offline():
    assert only(doctor.check_boards(network=False), "Job boards").status == doctor.OK


def test_robots_allowing_job_pages_passes(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(ROBOTS_ALLOW))
    checks = doctor.check_boards(network=True)
    assert len(checks) == len(boards.FETCHABLE_DOMAINS)
    assert {c.status for c in checks} == {doctor.OK}


def test_robots_disallowing_job_pages_warns(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(ROBOTS_DENY))
    checks = doctor.check_boards(network=True)
    assert {c.status for c in checks} == {doctor.WARN}
    assert all("disallows" in c.detail for c in checks)


def test_absent_robots_means_nothing_is_disallowed(monkeypatch):
    error = HTTPError("https://www.bayt.com/robots.txt", 404, "Not Found", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(error=error))
    checks = doctor.check_boards(network=True)
    assert {c.status for c in checks} == {doctor.OK}


def test_an_unreachable_board_is_not_reported_as_a_refusal(monkeypatch):
    """A blocked network must not be described as the board disallowing us — different fixes."""
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(error=URLError("Tunnel connection failed: 403")))
    checks = doctor.check_boards(network=True)
    assert all("reachability" in c.title for c in checks)
    assert all("not a decision by the board" in c.detail for c in checks)
    assert all("disallow" not in c.detail for c in checks)


def test_a_server_error_on_robots_is_conservative(monkeypatch):
    error = HTTPError("https://www.bayt.com/robots.txt", 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(error=error))
    checks = doctor.check_boards(network=True)
    assert {c.status for c in checks} == {doctor.WARN}
    assert all("treated as disallowed" in c.detail for c in checks)


# ---------------------------------------------------------------- feeds


def test_feeds_configured_are_counted(healthy):
    assert only(doctor.check_feeds(healthy, network=False), "News feeds").status == doctor.OK


def test_no_feeds_warns(healthy):
    text = PROFILE.split("[[news.feeds]]")[0]
    (healthy / "profile.toml").write_text(text, encoding="utf-8")
    assert only(doctor.check_feeds(healthy, network=False), "News feeds").status == doctor.WARN


# ---------------------------------------------------------------- desktop config


def test_missing_desktop_config_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "desktop_config_paths", lambda: [tmp_path / "claude_desktop_config.json"])
    assert only(doctor.check_desktop_config(), "Claude Desktop config").status == doctor.WARN


def test_registered_desktop_config_passes(tmp_path, monkeypatch, healthy):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("", encoding="utf-8")
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(json.dumps({"mcpServers": {"career-copilot": {
        "command": "uv",
        "args": ["--directory", str(project), "run", "career-copilot-mcp"],
        "env": {"CAREER_COPILOT_HOME": str(healthy)},
    }}}), encoding="utf-8")
    monkeypatch.setattr(doctor, "desktop_config_paths", lambda: [config])
    checks = doctor.check_desktop_config()
    assert not any(c.failed for c in checks)
    assert only(checks, "Configured project directory").status == doctor.OK


def test_a_moved_project_directory_is_a_failure(tmp_path, monkeypatch):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(json.dumps({"mcpServers": {"career-copilot": {
        "command": "uv",
        "args": ["--directory", str(tmp_path / "gone"), "run", "career-copilot-mcp"],
    }}}), encoding="utf-8")
    monkeypatch.setattr(doctor, "desktop_config_paths", lambda: [config])
    assert only(doctor.check_desktop_config(), "Configured project directory").status == doctor.FAIL


def test_unregistered_server_warns(tmp_path, monkeypatch):
    config = tmp_path / "claude_desktop_config.json"
    config.write_text(json.dumps({"mcpServers": {"something-else": {}}}), encoding="utf-8")
    monkeypatch.setattr(doctor, "desktop_config_paths", lambda: [config])
    assert only(doctor.check_desktop_config(), "Claude Desktop config").status == doctor.WARN


def test_desktop_config_paths_are_platform_specific():
    paths = doctor.desktop_config_paths()
    assert paths and all(path.name == "claude_desktop_config.json" for path in paths)


# ---------------------------------------------------------------- runner and CLI


def test_summarise_counts_every_status():
    checks = [
        doctor.Check(doctor.OK, "a", ""),
        doctor.Check(doctor.WARN, "b", ""),
        doctor.Check(doctor.WARN, "c", ""),
        doctor.Check(doctor.FAIL, "d", ""),
    ]
    assert doctor.summarise(checks) == {doctor.OK: 1, doctor.WARN: 2, doctor.FAIL: 1}


def test_cli_exits_zero_when_healthy(healthy, capsys):
    from career_copilot import cli

    code = cli.main(["doctor", "--offline"])
    assert code == 0
    assert "failure(s)" in capsys.readouterr().out


def test_cli_exits_one_when_something_failed(healthy, capsys):
    from career_copilot import cli

    os.chmod(healthy / "copilot.db", 0o644)
    assert cli.main(["doctor", "--offline"]) == 1


def test_cli_json_output_is_machine_readable(healthy, capsys):
    from career_copilot import cli

    cli.main(["doctor", "--offline", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"][doctor.OK] > 0
    assert all({"status", "title", "detail"} == set(entry) for entry in payload["checks"])
