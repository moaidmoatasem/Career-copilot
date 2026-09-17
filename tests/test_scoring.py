from pathlib import Path

from career_copilot import skills as sk
from career_copilot.config import load_profile
from career_copilot.scoring import detect_level, score_job, title_similarity

from conftest import CLOSE_DESCRIPTION, MATCHED_DESCRIPTION, PROFILE


def profile(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE, encoding="utf-8")
    return load_profile(path)


def test_strong_job_with_description_is_matched(tmp_path):
    result = score_job("Senior QA Automation Engineer", MATCHED_DESCRIPTION, "Dubai, United Arab Emirates", profile(tmp_path))
    assert result.tier == "matched"
    assert result.confidence != "low"
    assert "kubernetes" in result.missing_preferred
    assert "llm" in result.learning_skills
    assert result.missing_required == []


def test_title_only_job_is_capped_at_promising(tmp_path):
    result = score_job("Senior QA Engineer", "", "Riyadh, Saudi Arabia", profile(tmp_path))
    assert result.confidence == "low"
    assert result.tier == "promising"
    assert any("capped" in reason for reason in result.reasons)


def test_skill_gaps_limit_the_tier(tmp_path):
    result = score_job("Senior QA Engineer", CLOSE_DESCRIPTION, "Cairo, Egypt", profile(tmp_path))
    assert result.tier == "close"
    assert {"java", "selenium", "jmeter"} <= set(result.missing_required)
    assert any("skill coverage" in reason for reason in result.reasons)


def test_excluded_keyword(tmp_path):
    assert score_job("Junior QA Engineer", "", "Dubai", profile(tmp_path)).tier == "excluded"


def test_location_outside_targets_lowers_score(tmp_path):
    p = profile(tmp_path)
    inside = score_job("Senior QA Engineer", "", "Dubai", p)
    outside = score_job("Senior QA Engineer", "", "Berlin, Germany", p)
    assert inside.score > outside.score


def test_level_detection():
    assert detect_level("QA Lead", "")[0] == "lead"
    assert detect_level("IT Quality Assurance Manager", "")[0] == "manager"
    assert detect_level("QA Engineer", "We need 6+ years of experience")[0] == "senior"
    assert detect_level("QA Engineer", "")[0] == "mid"


def test_title_similarity_prefers_role_family():
    qa, _ = title_similarity("Senior SDET", ["Senior Test Automation Engineer", "QA Lead"])
    dev, _ = title_similarity("Senior Backend Developer", ["Senior Test Automation Engineer", "QA Lead"])
    assert qa >= 0.5 > dev


def test_skill_extraction_boundaries_and_aliases():
    found = sk.extract_skills("JavaScript, REST-Assured, CI / CD, K8s, TMF620 and Model Context Protocol")
    assert {"javascript", "rest assured", "ci/cd", "kubernetes", "tmf open apis", "mcp"} <= found
    assert "java" not in found


def test_preferred_section_weighting():
    weights = sk.weighted_job_skills("QA Engineer", "Requirements:\nPython\nNice to have:\nKubernetes\nDocker is a plus")
    assert weights["python"] == sk.WEIGHT_REQUIRED
    assert weights["kubernetes"] == sk.WEIGHT_PREFERRED
    assert weights["docker"] == sk.WEIGHT_PREFERRED


def test_alternatives_count_once_and_any_option_satisfies(tmp_path):
    description = (
        "Requirements:\n- Playwright or Selenium for UI automation\n- CI/CD with Jenkins or GitHub Actions\n"
        "- Python\n\nThis text pads the description so it counts as a full job post for scoring purposes. "
        "It describes the team, the product, and the way releases are shipped every week.\n"
    )
    result = score_job("Senior QA Engineer", description, "Dubai", profile(tmp_path))
    assert result.confidence != "low"
    assert "selenium" not in result.missing_required  # Playwright satisfies the alternative
    ci_tools = [s for s in result.missing_required if s in {"jenkins", "github actions"}]
    assert len(ci_tools) == 1  # one unmet alternative group, reported once
    assert result.alternatives[ci_tools[0]] == sorted({"jenkins", "github actions"} - set(ci_tools))


def test_unmet_alternatives_suggest_one_option(tmp_path):
    description = (
        "Requirements:\n- Java or C# for the automation framework\n- Python scripting\n\n"
        "Padding text so this counts as a full description for scoring purposes in the unit test suite.\n"
    )
    result = score_job("Senior QA Engineer", description, "Dubai", profile(tmp_path))
    assert len([s for s in result.missing_required if s in {"java", "c#"}]) == 1
    assert result.alternatives


def test_implied_skills_are_credited(tmp_path):
    description = ("Requirements:\n- REST API testing experience\n- Performance testing\n\n"
                   "Padding text so this counts as a full description for scoring purposes in the unit test suite.\n")
    result = score_job("Senior QA Engineer", description, "Dubai", profile(tmp_path))
    assert "rest api" not in result.missing_required  # implied by api testing
    assert "performance testing" in result.missing_required


def test_big_advantage_is_preferred():
    weights = sk.weighted_job_skills("QA", "Requirements:\nTelecom experience is a big advantage\nPython")
    assert weights["telecom"] == sk.WEIGHT_PREFERRED and weights["python"] == sk.WEIGHT_REQUIRED
