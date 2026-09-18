"""Sponsor-register name matching: rank, report confidence, refuse to guess.

The register rows below are real entries from the UK Register of Licensed Sponsors, kept
verbatim because the defects this module exists to prevent are all real collisions in it.
"""

from __future__ import annotations

import pytest

from career_copilot import sponsors
from career_copilot.util import companies_match

# Real rows. Note "Wise" is a High Wycombe *religious worker* licence, and the fintech is
# registered as "Wise Payments Limited".
REGISTER = [
    {"name": "Wise", "route": "Religious Worker", "type_rating": "Temporary Worker (A rating)",
     "town": "High Wycombe", "county": "Buckinghamshire"},
    {"name": "Wise Payments Limited", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "London", "county": ""},
    {"name": "Aaron Wise Limited", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "Cardiff", "county": ""},
    {"name": "UK Wise Group Ltd", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "Romford", "county": "Essex"},
    {"name": "Wise Legal Limited", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "London", "county": ""},
    {"name": "Monzo Bank Ltd", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "London", "county": ""},
    {"name": "Google (UK) Limited", "route": "Skilled Worker", "type_rating": "Worker (A rating)",
     "town": "London", "county": ""},
    {"name": "Wise Children Limited", "route": "Creative Worker", "type_rating": "Temporary Worker (A rating)",
     "town": "Bristol", "county": ""},
]


def names(candidates) -> list[str]:
    return [c.name for c in candidates]


# ---------------------------------------------------------------------------- normalisation

def test_normalise_strips_case_punctuation_and_accents():
    assert sponsors.normalise_name("Google (UK) Limited") == "google uk limited"
    assert sponsors.normalise_name("  Nestlé   S.A. ") == "nestle s a"
    assert sponsors.normalise_name("Marks & Spencer") == "marks and spencer"


def test_core_name_drops_legal_noise_but_never_everything():
    assert sponsors.core_name("Monzo Bank Ltd") == "monzo bank"
    assert sponsors.core_name("Google (UK) Limited") == "google"
    # Stripping would empty this one, so the normalised tokens are kept instead.
    assert sponsors.core_name("The Company Ltd") == "the company ltd"


# ---------------------------------------------------------------------------- scoring cascade

def test_exact_match_scores_one():
    assert sponsors.score_match("Monzo Bank Ltd", "Monzo Bank Ltd") == (1.0, "exact")
    assert sponsors.score_match("monzo  bank   ltd", "Monzo Bank Ltd") == (1.0, "exact")


def test_legal_suffix_difference_is_a_strong_match():
    assert sponsors.score_match("Monzo Bank", "Monzo Bank Ltd") == (0.97, "normalised")
    assert sponsors.score_match("Google", "Google (UK) Limited") == (0.97, "normalised")


def test_leading_prefix_scores_below_auto_confirm():
    score, basis = sponsors.score_match("Wise", "Wise Payments Limited")
    assert basis == "prefix"
    assert score == pytest.approx(0.825)
    assert score < sponsors.AUTO_CONFIRM_SCORE


def test_mid_name_token_is_not_a_match():
    """The defect this module exists to prevent: "Wise" is not "Aaron Wise Limited"."""
    score, _ = sponsors.score_match("Wise", "Aaron Wise Limited")
    assert score < sponsors.MIN_CANDIDATE_SCORE
    assert "Aaron Wise Limited" not in names(sponsors.rank_candidates("Wise", REGISTER))


def test_core_excavated_from_the_middle_does_not_auto_confirm():
    """Stripping noise reduces "UK Wise Group Ltd" to "wise", which must not confirm as Wise."""
    score, basis = sponsors.score_match("Wise", "UK Wise Group Ltd")
    assert score < sponsors.AUTO_CONFIRM_SCORE
    assert basis != "normalised"


def test_unrelated_names_score_zero():
    assert sponsors.score_match("Monzo Bank", "Google (UK) Limited")[0] == 0.0


def test_empty_and_single_character_queries_have_no_answer():
    assert sponsors.rank_candidates("", REGISTER) == []
    assert sponsors.rank_candidates("W", REGISTER) == []
    assert sponsors.rank_candidates("   ", REGISTER) == []
    assert sponsors.score_match("", "Monzo Bank Ltd")[0] == 0.0


# ---------------------------------------------------------------------------- route filter

def test_non_work_routes_are_excluded_before_scoring():
    """A religious-worker licence is not a skilled-work sponsorship, whatever the name matches."""
    assert sponsors.score_match("Wise", "Wise") == (1.0, "exact")
    assert sponsors.is_work_route("Religious Worker") is False
    assert "Wise" not in names(sponsors.rank_candidates("Wise", REGISTER))
    assert "Wise Children Limited" not in names(sponsors.rank_candidates("Wise Children", REGISTER))


def test_work_routes_are_recognised():
    for route in ("Skilled Worker", "Global Business Mobility: Senior or Specialist Worker",
                  "Global Business Mobility: Graduate Trainee", "Scale-up", "Intra-company Routes"):
        assert sponsors.is_work_route(route) is True
    for route in ("Creative Worker", "International Sportsperson", "Charity Worker",
                  "Tier 2 Ministers of Religion", "Seasonal Worker", "Government Authorised Exchange", ""):
        assert sponsors.is_work_route(route) is False


# ---------------------------------------------------------------------------- deciding

def test_unambiguous_leader_is_confirmed():
    confirmed, needs = sponsors.decide(sponsors.rank_candidates("Wise Payments", REGISTER))
    assert confirmed is not None
    assert confirmed.name == "Wise Payments Limited"
    assert confirmed.town == "London"
    assert needs is False


def test_ambiguous_query_asks_rather_than_guesses():
    candidates = sponsors.rank_candidates("Wise", REGISTER)
    confirmed, needs = sponsors.decide(candidates)
    assert confirmed is None
    assert needs is True
    assert candidates, "the user still gets something to choose from"


def test_no_candidates_is_not_a_question():
    confirmed, needs = sponsors.decide(sponsors.rank_candidates("Deliveroo", REGISTER))
    assert confirmed is None
    assert needs is False


def test_two_exact_matches_need_a_human():
    twins = [
        {"name": "Acme Ltd", "route": "Skilled Worker", "type_rating": "Worker (A rating)", "town": "Leeds"},
        {"name": "Acme Ltd", "route": "Skilled Worker", "type_rating": "Worker (A rating)", "town": "Bath"},
    ]
    confirmed, needs = sponsors.decide(sponsors.rank_candidates("Acme Ltd", twins))
    assert confirmed is None
    assert needs is True


def test_candidates_are_ranked_and_capped():
    candidates = sponsors.rank_candidates("Wise", REGISTER, limit=2)
    assert len(candidates) <= 2
    assert candidates == sorted(candidates, key=lambda c: (-c.score, c.name))
    assert all(c.score >= sponsors.MIN_CANDIDATE_SCORE for c in candidates)


def test_ranking_is_deterministic_and_does_not_mutate_input():
    before = [dict(row) for row in REGISTER]
    first = [c.to_dict() for c in sponsors.rank_candidates("Wise", REGISTER)]
    for _ in range(20):
        assert [c.to_dict() for c in sponsors.rank_candidates("Wise", REGISTER)] == first
    assert REGISTER == before


def test_existing_companies_match_is_too_loose_for_this():
    """Why util.companies_match isn't reused: it is a token-subset test, which is the defect.

    It stays as it is — find_referrals wants that looseness — so the register needs its own.
    """
    assert companies_match("Wise", "Aaron Wise Limited") is True
    assert sponsors.score_match("Wise", "Aaron Wise Limited")[0] < sponsors.MIN_CANDIDATE_SCORE


# ---------------------------------------------------------------------------- CSV parsing

HEADER = "Organisation Name,Town/City,County,Type & Rating,Route\n"


def test_parse_register_csv_reads_the_gov_uk_shape(tmp_path):
    path = tmp_path / "register.csv"
    path.write_text(
        HEADER
        + "Wise Payments Limited,London,,Worker (A rating),Skilled Worker\n"
        + "Wise,High Wycombe,Buckinghamshire,Temporary Worker (A rating),Religious Worker\n",
        encoding="utf-8",
    )
    rows, report = sponsors.parse_register_csv(path)
    assert len(rows) == 2
    assert rows[0] == {"name": "Wise Payments Limited", "town": "London", "county": "",
                       "type_rating": "Worker (A rating)", "route": "Skilled Worker"}
    assert report["rows"] == 2
    assert report["work_route_rows"] == 1


def test_parse_register_csv_accepts_alternative_column_names(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text(
        "Organisation,Town,County,Type and Rating,Sub Category (where applicable)\n"
        "Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker\n",
        encoding="utf-8",
    )
    rows, _ = sponsors.parse_register_csv(path)
    assert rows[0]["name"] == "Monzo Bank Ltd"
    assert rows[0]["route"] == "Skilled Worker"


def test_parse_register_csv_handles_a_byte_order_mark(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + (HEADER + "Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker\n").encode())
    rows, _ = sponsors.parse_register_csv(path)
    assert rows[0]["name"] == "Monzo Bank Ltd"


def test_parse_register_csv_skips_rows_without_a_name(tmp_path):
    path = tmp_path / "gappy.csv"
    path.write_text(HEADER + ",London,,Worker (A rating),Skilled Worker\n"
                    + "Monzo Bank Ltd,London,,Worker (A rating),Skilled Worker\n", encoding="utf-8")
    rows, report = sponsors.parse_register_csv(path)
    assert len(rows) == 1
    assert report["skipped_without_name"] == 1


def test_parse_register_csv_rejects_a_file_with_no_name_column(tmp_path):
    path = tmp_path / "wrong.csv"
    path.write_text("Town,County\nLondon,Greater London\n", encoding="utf-8")
    with pytest.raises(ValueError, match="organisation-name column"):
        sponsors.parse_register_csv(path)
