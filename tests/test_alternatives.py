"""Alternatives phrasing suite (F3): every way a post says "any one of these" must group the options.

Each case is one requirement line under a "Requirements:" heading. `groups` are the alternative sets
the line must produce; `standalone` are the skills that must still count on their own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from career_copilot import skills as sk
from career_copilot.config import load_profile
from career_copilot.scoring import score_job

from conftest import PROFILE

CASES = [
    # (id, line, expected groups, expected standalone)
    ("x-or-y", "Playwright or Selenium for UI automation",
     [{"playwright", "selenium"}], set()),
    ("x-slash-y", "Jenkins/GitHub Actions pipelines",
     [{"jenkins", "github actions"}], set()),
    ("x-paren-or-y", "Strong Playwright (or Selenium) experience",
     [{"playwright", "selenium"}], set()),
    ("x-y-or-z", "Jenkins, GitLab CI or GitHub Actions",
     [{"jenkins", "gitlab ci", "github actions"}], set()),
    ("x-y-comma-or-z", "Java, C#, or TypeScript for test code",
     [{"java", "c#", "typescript"}], set()),
    ("eg-x-y", "A modern UI framework, e.g. Playwright, Cypress",
     [{"playwright", "cypress"}], set()),
    ("eg-paren", "An API testing tool (e.g. Postman, REST Assured)",
     [{"postman", "rest assured"}], {"api testing"}),
    ("x-y-or-similar", "Postman, REST Assured or similar tools",
     [{"postman", "rest assured"}], set()),
    ("such-as-and", "Performance tools such as JMeter, k6 and Gatling",
     [{"jmeter", "k6"} | ({"gatling"} if "gatling" in sk.TAXONOMY else set())], set()),
    ("and-is-not-or", "Python and Playwright or Selenium",
     [{"playwright", "selenium"}], {"python"}),
    ("plain-list-is-required", "Python, Docker and Jenkins",
     [], {"python", "docker", "jenkins"}),
]


@pytest.mark.parametrize("line, groups, standalone", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_phrasing(line, groups, standalone):
    _, found_groups, found_standalone = sk.job_requirements("", f"Requirements:\n- {line}\n")
    assert sorted(map(sorted, found_groups)) == sorted(map(sorted, groups))
    assert found_standalone == standalone


# Requirements block in the shape of the e& UAE QA posting that showed the bug.
E_AND_DESCRIPTION = """About the role
e& is looking for a Senior QA Automation Engineer to own test automation across our digital channels,
working with product and engineering squads in Dubai.

Requirements:
- 5+ years in software testing, at least 3 in test automation
- Strong Playwright (or Selenium) experience with Python or Java
- API testing with Postman, REST Assured or similar
- CI/CD with Jenkins, GitLab CI or GitHub Actions
- Docker

Nice to have:
- Performance testing tools such as JMeter or k6
"""


def test_e_and_description(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(PROFILE, encoding="utf-8")
    result = score_job("Senior QA Automation Engineer", E_AND_DESCRIPTION, "Dubai, United Arab Emirates",
                       load_profile(path))
    # The profile has Playwright and Python, so "(or Selenium)" and "or Java" are met, not missing.
    for satisfied in ("selenium", "java"):
        assert satisfied not in result.missing_required, f"{satisfied} reported missing though an alternative is met"
    # Unmet groups are reported once each, with the other options listed as alternatives.
    for group in ({"jenkins", "gitlab ci", "github actions"}, {"postman", "rest assured"}):
        missing = [s for s in result.missing_required if s in group]
        assert len(missing) == 1, f"{group} reported as {missing}"
        assert set(result.alternatives[missing[0]]) == group - set(missing)
