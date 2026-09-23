"""The approval PIN: stored only as a salted hash, set only by a person at a terminal."""

from __future__ import annotations

import io
import json

import pytest

from career_copilot import cli, pin
from career_copilot import server as srv


def test_hash_verifies_the_right_pin_and_nothing_else():
    stored = pin.hash_pin("402917")
    assert pin.verify("402917", stored)
    assert pin.verify(" 402917 ", stored)
    assert not pin.verify("402918", stored)
    assert not pin.verify("", stored)


def test_each_hash_is_salted_and_carries_no_pin():
    a, b = pin.hash_pin("402917"), pin.hash_pin("402917")
    assert a != b
    assert "402917" not in a
    assert a.startswith("scrypt$")


@pytest.mark.parametrize("stored", ["", "garbage", "md5$1$2$3$4$5", "scrypt$x$8$1$AAAA$AAAA", "scrypt$16384$8$1$!!$!!"])
def test_a_malformed_hash_never_matches(stored):
    assert not pin.verify("402917", stored)


@pytest.mark.parametrize("bad", ["12a456", "40291", "4029174029174", "111111", "123456", "987654", "٤٠٢٩١٧", ""])
def test_weak_or_malformed_pins_are_refused(bad):
    with pytest.raises(pin.PinError):
        pin.validate(bad)


def test_a_reasonable_pin_is_accepted():
    assert pin.validate(" 402917 ") == "402917"
    assert pin.validate("135792468024") == "135792468024"


def test_set_and_clear_are_audited_without_the_pin(cp):
    assert not pin.is_set(cp.store)
    pin.set_pin(cp.store, "402917")
    assert pin.is_set(cp.store)
    pin.set_pin(cp.store, "518204")
    assert pin.verify("518204", pin.stored_hash(cp.store))
    assert pin.clear_pin(cp.store) is True
    assert pin.clear_pin(cp.store) is False
    assert not pin.is_set(cp.store)

    entries = cp.audit_log(20)["entries"]
    actions = [(e["actor"], e["action"], e["details"]) for e in entries if e["action"].startswith("pin.")]
    assert actions == [("human", "pin.clear", {}), ("human", "pin.set", {"replaced": True}),
                       ("human", "pin.set", {"replaced": False})]
    dumped = json.dumps(entries)
    assert "402917" not in dumped and "518204" not in dumped


@pytest.mark.anyio
async def test_no_mcp_tool_can_touch_the_pin(cp):
    pin.set_pin(cp.store, "402917")
    tools = await srv.mcp.list_tools()
    assert not [t.name for t in tools if "pin" in t.name.lower()]
    assert pin.stored_hash(cp.store) not in json.dumps(cp.status())


# ---------------------------------------------------------------------------- CLI

@pytest.fixture
def terminal(monkeypatch, cp):
    """Run `career-copilot pin` in-process against the test home, as if from a real terminal."""
    monkeypatch.setenv("CAREER_COPILOT_HOME", str(cp.home))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def typed(*answers):
        replies = iter(answers)
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(replies))

    return typed


def test_cli_sets_the_pin_after_typing_it_twice(terminal, cp):
    terminal("402917", "402917")
    assert cli.main(["pin", "set"]) == 0
    assert pin.verify("402917", pin.stored_hash(cp.store))


def test_cli_refuses_a_mismatched_confirmation(terminal, cp, capsys):
    terminal("402917", "402918")
    assert cli.main(["pin", "set"]) == 1
    assert not pin.is_set(cp.store)
    assert "didn't match" in capsys.readouterr().err


def test_cli_refuses_a_weak_pin(terminal, cp, capsys):
    terminal("123456")
    assert cli.main(["pin", "set"]) == 1
    assert not pin.is_set(cp.store)
    assert "straight run" in capsys.readouterr().err


def test_cli_clears_the_pin(terminal, cp):
    pin.set_pin(cp.store, "402917")
    assert cli.main(["pin", "clear"]) == 0
    assert not pin.is_set(cp.store)


def test_cli_status_reports_without_a_terminal(monkeypatch, cp, capsys):
    monkeypatch.setenv("CAREER_COPILOT_HOME", str(cp.home))
    assert cli.main(["pin", "status"]) == 0
    assert "not set" in capsys.readouterr().out
    pin.set_pin(cp.store, "402917")
    assert cli.main(["pin", "status"]) == 0
    assert "Approval PIN: set" in capsys.readouterr().out
