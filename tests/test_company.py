"""Company-name matching: ampersand names, the alias graph, and referrals that depend on them (F2)."""

from __future__ import annotations

import pytest

from career_copilot.util import companies_match


def _connection(cp, name: str, company: str, stored_key: str) -> None:
    # stored_key is what the importer wrote at the time, so rows imported before a change to
    # company_key() must still be found.
    cp.store.execute(
        "INSERT INTO connections(dedupe_key, name, company, company_key, position, profile_url, connected_on) "
        "VALUES (?,?,?,?,?,?,?)",
        (f"c:{name}", name, company, stored_key, "QA Manager", "https://www.linkedin.com/in/x", "01 Feb 2024"),
    )


def _referral_names(cp, company: str) -> list[str]:
    job = cp.add_job("Senior QA Engineer", company, "Dubai, United Arab Emirates", url=f"https://example.com/{company}")
    return [c["name"] for c in cp.find_referrals(job["id"])["connections"]]


def test_a_connection_at_e_and_uae_is_found_for_an_e_and_uae_job(cp):
    _connection(cp, "Layla Saeed", "e& UAE", stored_key="e uae")
    assert _referral_names(cp, "e& UAE") == ["Layla Saeed"]


def test_a_connection_at_e_and_is_found_for_etisalat_by_e_and(cp):
    _connection(cp, "Layla Saeed", "e& UAE", stored_key="e uae")
    assert _referral_names(cp, "Etisalat by e&") == ["Layla Saeed"]


@pytest.mark.parametrize("a, b", [
    ("e& UAE", "e&"),
    ("e&", "Etisalat by e&"),
    ("e& UAE", "Etisalat"),
    ("Etisalat UAE", "Emirates Telecommunications Group"),
    ("e&", "Emirates Telecommunications Group PJSC"),
    ("AT&T", "AT&T Inc."),
])
def test_names_of_the_same_company_match(a, b):
    assert companies_match(a, b)
    assert companies_match(b, a)


@pytest.mark.parametrize("a, b", [
    ("e& UAE", "Emirates NBD"),
    ("e& UAE", "Emirates Airline"),
    ("e&", "P&G"),
    ("e& UAE", "Careem UAE"),
    ("Emirates Telecommunications Group", "Emirates Group"),
])
def test_different_companies_do_not_match(a, b):
    assert not companies_match(a, b)
    assert not companies_match(b, a)
