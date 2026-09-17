from __future__ import annotations

import pytest

from career_copilot.service import Copilot

PROFILE = """
[candidate]
name = "Test User"
linkedin_url = "https://www.linkedin.com/in/test-user"
seniority = "senior"
acceptable_seniority = ["senior", "lead", "manager"]

[targets]
titles = ["Senior QA Engineer", "Senior Test Automation Engineer", "QA Lead"]
locations = ["United Arab Emirates", "Saudi Arabia", "Egypt"]
remote_ok = false
exclude_title_keywords = ["intern", "junior"]

[skills]
have = ["python", "playwright", "api testing", "test automation", "ci/cd", "docker"]
learning = ["llm"]

[privacy]
retention_days = 90

[news]
interests = ["playwright", "test automation", "ai testing"]

[[news.feeds]]
name = "Example feed"
url = "https://example.com/feed.xml"
"""

MATCHED_DESCRIPTION = """About the role
You will own test automation for a large web platform used by millions of customers across the region.

Requirements:
- 5+ years in test automation
- Strong Python and Playwright
- API testing
- CI/CD pipelines and Docker

Nice to have:
- Kubernetes
- Experience testing LLM features

About us
A growing technology company with teams in Dubai and Cairo.
"""

CLOSE_DESCRIPTION = """What you'll bring:
- Python scripting for test tooling
- Java and Selenium WebDriver
- JMeter for load tests
- Exposure to LLM products is a plus

We work in small teams and ship weekly. This paragraph exists to make the description long enough.
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_COPILOT_HOME", str(tmp_path))
    monkeypatch.delenv("CAREER_COPILOT_PROFILE", raising=False)
    (tmp_path / "profile.toml").write_text(PROFILE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def cp(home):
    copilot = Copilot(home)
    yield copilot
    try:
        copilot.store.close()
    except Exception:
        pass
