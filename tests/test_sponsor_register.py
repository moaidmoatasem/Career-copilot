"""Importing the register, and how a licence match reaches the job, the tool and the Console."""

from __future__ import annotations

import pytest

from career_copilot.service import CopilotError

HEADER = "Organisation Name,Town/City,County,Type & Rating,Route\n"
ROWS = (
    "Wise Payments Limited,London,,Worker (A rating),Skilled Worker\n"
    "Wise,High Wycombe,Buckinghamshire,Temporary Worker (A rating),Religious Worker\n"
    "Aaron Wise Limited,Cardiff,,Worker (A rating),Skilled Worker\n"
    "Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker\n"
)


@pytest.fixture
def register(cp):
    cp.imports_dir.mkdir(parents=True, exist_ok=True)
    (cp.imports_dir / "register.csv").write_text(HEADER + ROWS, encoding="utf-8")
    cp.import_sponsor_register("register.csv")
    return cp


def uk_job(cp, company: str, location: str = "London, United Kingdom"):
    return cp.add_job("Senior QA Engineer", company, location, "")


# ---------------------------------------------------------------------------- import

def test_import_records_counts_and_provenance(register):
    status = register.sponsor_register_status()
    assert status["imported"] is True
    assert status["rows"] == 4
    assert status["file"] == "register.csv"
    assert "Open Government Licence" in status["licence"]
    assert status["source"].startswith("https://www.gov.uk/")
    assert status["stale"] is False
    assert register.store.get_meta("sponsor_register_sha256")


def test_import_is_confined_to_the_imports_folder(cp):
    with pytest.raises(CopilotError, match="imports are limited to"):
        cp.import_sponsor_register("../../../etc/passwd")


def test_import_reports_a_missing_file_with_what_is_available(cp):
    cp.imports_dir.mkdir(parents=True, exist_ok=True)
    (cp.imports_dir / "something-else.csv").write_text(HEADER, encoding="utf-8")
    with pytest.raises(CopilotError, match="something-else.csv"):
        cp.import_sponsor_register("register.csv")


def test_import_rejects_a_csv_without_an_organisation_name(cp):
    cp.imports_dir.mkdir(parents=True, exist_ok=True)
    (cp.imports_dir / "wrong.csv").write_text("Town,County\nLondon,\n", encoding="utf-8")
    with pytest.raises(CopilotError, match="could not read"):
        cp.import_sponsor_register("wrong.csv")


def test_reimport_replaces_rather_than_appends(register):
    (register.imports_dir / "register.csv").write_text(
        HEADER + "Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker\n", encoding="utf-8")
    register.import_sponsor_register("register.csv")
    assert register.sponsor_register_status()["rows"] == 1


def test_import_is_audited(register):
    actions = {(e["actor"], e["action"]) for e in register.audit_log()["entries"]}
    assert ("human", "sponsors.import") in actions


def test_purge_clears_the_register(register):
    assert register.purge("sponsors")["rows"] == 4
    assert register.sponsor_register_status()["imported"] is False


# ---------------------------------------------------------------------------- lookup on a job

def test_uk_job_with_a_clear_match_is_licensed(register):
    job = uk_job(register, "Wise Payments")
    sponsorship = register.get_job(job["id"])["sponsorship"]
    assert sponsorship["status"] == "licensed"
    assert sponsorship["match"]["name"] == "Wise Payments Limited"
    assert sponsorship["match"]["route"] == "Skilled Worker"
    assert "company-level" in sponsorship["note"]


def test_ambiguous_company_asks_instead_of_guessing(register):
    job = uk_job(register, "Wise")
    sponsorship = register.get_job(job["id"])["sponsorship"]
    assert sponsorship["status"] == "needs_confirmation"
    assert sponsorship["match"] is None
    # The religious-worker licence must never be offered as a skilled-work sponsor.
    assert "Wise" not in [c["name"] for c in sponsorship["candidates"]]
    assert "Aaron Wise Limited" not in [c["name"] for c in sponsorship["candidates"]]


def test_unknown_company_is_no_match(register):
    job = uk_job(register, "Definitely Not Real Ltd")
    assert register.get_job(job["id"])["sponsorship"]["status"] == "no_match"


def test_non_uk_job_carries_no_sponsorship_at_all(register):
    job = uk_job(register, "Wise Payments", "Dubai, United Arab Emirates")
    assert "sponsorship" not in register.get_job(job["id"])


def test_empty_register_is_unknown_not_a_refusal(cp):
    job = uk_job(cp, "Wise Payments")
    sponsorship = cp.get_job(job["id"])["sponsorship"]
    assert sponsorship["status"] == "no_register"
    assert "not a" in sponsorship["note"].lower()


def test_job_without_a_company_says_so(register):
    job = uk_job(register, "")
    assert register.get_job(job["id"])["sponsorship"]["status"] == "no_company"


# ---------------------------------------------------------------------------- the tool

def test_check_sponsor_licence_reports_non_uk_as_not_applicable(register):
    job = uk_job(register, "Wise Payments", "Cairo, Egypt")
    result = register.check_sponsor_licence(job["id"])
    assert result["applicable"] is False
    assert "not UK-located" in result["reason"]


def test_check_sponsor_licence_returns_the_match(register):
    job = uk_job(register, "Monzo Bank")
    result = register.check_sponsor_licence(job["id"])
    assert result["applicable"] is True
    assert result["match"]["name"] == "Monzo Bank Ltd"


def test_check_sponsor_licence_rejects_an_unknown_job(register):
    with pytest.raises(CopilotError, match="not found"):
        register.check_sponsor_licence(9999)


# ---------------------------------------------------------------------------- staleness

def test_an_old_import_is_marked_provisional(register):
    register.store.set_meta("sponsor_register_imported_at", "2020-01-01T00:00:00+00:00")
    assert register.sponsor_register_status()["stale"] is True


# ---------------------------------------------------------------------------- UK is recognised at all

def test_uk_locations_are_recognised_by_geo():
    from career_copilot import geo
    for location in ("London, United Kingdom", "Manchester, UK", "Edinburgh, Scotland", "Cardiff, Wales"):
        assert "united kingdom" in geo.countries_in(location), location
    assert "united kingdom" not in geo.countries_in("Dubai, United Arab Emirates")
