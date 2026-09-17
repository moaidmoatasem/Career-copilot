"""A small, explainable skill taxonomy tuned for QA / test automation / AI-quality roles.

Extend it per user in profile.toml under [skills.aliases]. Aliases match case-insensitively on
word boundaries; an alias starting with "re:" is a raw regular expression.
"""

from __future__ import annotations

import re
from functools import lru_cache

TAXONOMY: dict[str, tuple[str, tuple[str, ...]]] = {
    # QA practices
    "test automation": ("qa_practice", ("test automation", "automated testing", "automation testing",
                                        "automation framework", "qa automation", "test automation framework")),
    "manual testing": ("qa_practice", ("manual testing", "exploratory testing")),
    "api testing": ("qa_practice", ("api testing", "api test automation", "api automation", "rest api testing", "api tests")),
    "performance testing": ("qa_practice", ("performance testing", "load testing", "stress testing")),
    "security testing": ("qa_practice", ("security testing", "penetration testing", "pentesting", "owasp")),
    "mobile testing": ("qa_practice", ("mobile testing", "mobile app testing", "mobile automation")),
    "contract testing": ("qa_practice", ("contract testing", "consumer-driven contracts", "pact")),
    "bdd": ("qa_practice", ("bdd", "behavior-driven development", "behaviour-driven development",
                            "behavior driven development", "gherkin")),
    "test strategy": ("qa_practice", ("test strategy", "test strategies", "test planning", "test plan", "test plans")),
    "ai testing": ("ai", ("ai testing", "testing ai", "testing of ai", "ai quality", "ml testing", "llm testing")),
    # QA tools
    "test management": ("qa_tool", ("test management", "testrail", "zephyr", "xray", "qtest")),
    "playwright": ("qa_tool", ("playwright",)),
    "selenium": ("qa_tool", ("selenium", "webdriver")),
    "cypress": ("qa_tool", ("cypress",)),
    "appium": ("qa_tool", ("appium",)),
    "pytest": ("qa_tool", ("pytest",)),
    "junit": ("qa_tool", ("junit",)),
    "testng": ("qa_tool", ("testng",)),
    "rest assured": ("qa_tool", ("rest assured", "rest-assured", "restassured")),
    "postman": ("qa_tool", ("postman", "newman")),
    "jmeter": ("qa_tool", ("jmeter",)),
    "k6": ("qa_tool", ("k6",)),
    "gatling": ("qa_tool", ("gatling",)),
    "cucumber": ("qa_tool", ("cucumber", "specflow")),
    "robot framework": ("qa_tool", ("robot framework",)),
    "soapui": ("qa_tool", ("soapui", "readyapi")),
    "jira": ("qa_tool", ("jira",)),
    # Languages
    "python": ("language", ("python",)),
    "java": ("language", ("java",)),
    "javascript": ("language", ("javascript",)),
    "typescript": ("language", ("typescript",)),
    "c#": ("language", ("c#", "csharp")),
    "sql": ("language", ("sql", "mysql", "postgresql", "postgres", "t-sql", "pl/sql")),
    "bash": ("language", ("bash", "shell scripting", "shell scripts")),
    # DevOps and cloud
    "ci/cd": ("devops", ("ci/cd", "ci / cd", "cicd", "continuous integration", "continuous delivery",
                         "continuous deployment")),
    "jenkins": ("devops", ("jenkins",)),
    "github actions": ("devops", ("github actions",)),
    "gitlab ci": ("devops", ("gitlab ci", "gitlab-ci", "gitlab pipelines")),
    "azure devops": ("devops", ("azure devops",)),
    "docker": ("devops", ("docker", "containerization", "containerisation")),
    "kubernetes": ("devops", ("kubernetes", "k8s", "openshift")),
    "git": ("devops", ("git",)),
    "linux": ("devops", ("linux", "unix")),
    "observability": ("devops", ("observability", "grafana", "prometheus", "kibana", "elk stack", "datadog", "splunk")),
    "aws": ("cloud", ("aws", "amazon web services")),
    "azure": ("cloud", ("microsoft azure", "azure cloud")),
    "gcp": ("cloud", ("gcp", "google cloud")),
    # APIs and architecture
    "rest api": ("api", ("rest api", "rest apis", "restful", "restful api", "restful apis")),
    "graphql": ("api", ("graphql",)),
    "grpc": ("api", ("grpc",)),
    "openapi": ("api", ("openapi", "swagger")),
    "microservices": ("api", ("microservices", "micro-services", "microservice architecture")),
    "kafka": ("api", ("kafka",)),
    "soap": ("api", ("soap api", "soap web services", "soap")),
    # Domains
    "tmf open apis": ("domain", ("tmf open api", "tmf open apis", "tm forum", "tmforum", r"re:tmf\s?6\d{2}")),
    "telecom": ("domain", ("telecom", "telecommunications", "telco", "oss/bss", "bss", "5g")),
    "banking": ("domain", ("banking", "core banking", "payments", "fintech")),
    "e-commerce": ("domain", ("e-commerce", "ecommerce")),
    # AI
    "llm": ("ai", ("llm", "llms", "large language model", "large language models", "generative ai", "genai", "gen ai")),
    "rag": ("ai", ("rag", "retrieval augmented generation", "retrieval-augmented generation")),
    "ai agents": ("ai", ("ai agents", "ai agent", "agentic", "llm agents", "multi-agent")),
    "llm evaluation": ("ai", ("llm evaluation", "llm evals", "ai evaluation", "model evaluation", "evals")),
    "prompt engineering": ("ai", ("prompt engineering",)),
    "mcp": ("ai", ("model context protocol", "mcp server", "mcp servers")),
    "machine learning": ("ai", ("machine learning", "deep learning")),
    "langchain": ("ai", ("langchain", "langgraph")),
    "ollama": ("ai", ("ollama",)),
    # Leadership and process
    "team leadership": ("leadership", ("team lead", "team leadership", "lead a team", "leading a team",
                                       "people management", "line management", "mentoring", "coaching")),
    "stakeholder management": ("leadership", ("stakeholder management", "stakeholders")),
    "agile": ("process", ("agile", "scrum", "kanban")),
    "istqb": ("certification", ("istqb", "ctfl", "ctal")),
}

# Having the key skill means you effectively have the implied ones (applied to the candidate, transitively).
IMPLIES: dict[str, set[str]] = {
    "api testing": {"rest api"}, "openapi": {"rest api"}, "tmf open apis": {"rest api", "telecom"},
    "rest assured": {"api testing"}, "postman": {"api testing"}, "karate": {"api testing"},
    "playwright": {"test automation"}, "selenium": {"test automation"}, "cypress": {"test automation"},
    "appium": {"mobile testing", "test automation"}, "robot framework": {"test automation"},
    "pytest": {"python"}, "k6": {"performance testing"}, "jmeter": {"performance testing"},
    "gatling": {"performance testing"}, "github actions": {"ci/cd"}, "jenkins": {"ci/cd"},
    "gitlab ci": {"ci/cd"}, "azure devops": {"ci/cd"}, "kubernetes": {"docker"},
    "rag": {"llm"}, "ai agents": {"llm"}, "llm evaluation": {"llm"}, "langchain": {"llm"}, "ollama": {"llm"},
    "prompt engineering": {"llm"},
}


def expand_implied(found: set[str]) -> set[str]:
    result, frontier = set(found), list(found)
    while frontier:
        for implied in IMPLIES.get(frontier.pop(), ()):
            if implied not in result:
                result.add(implied)
                frontier.append(implied)
    return result


CATEGORY_HOURS: dict[str, int] = {
    "qa_tool": 12, "qa_practice": 15, "language": 40, "devops": 20, "cloud": 30, "api": 12,
    "domain": 15, "ai": 25, "leadership": 10, "process": 8, "certification": 40, "other": 15,
}

PRACTICE_IDEAS: dict[str, str] = {
    "qa_tool": "Build a small public repo using {skill} against a public demo app or API, run it in CI, "
               "and pin it in your LinkedIn Featured section.",
    "qa_practice": "Write a one-page {skill} approach for a demo system (no employer data) and apply it in a sample project.",
    "language": "Port one of your existing test utilities to {skill} and publish it.",
    "devops": "Run a demo test suite with {skill} in a pipeline and document the setup in the README.",
    "cloud": "Deploy a small demo service on the {skill} free tier and test it end to end.",
    "api": "Add {skill} coverage to an API test project, including schema validation and negative cases.",
    "domain": "Summarise core {skill} concepts in your own notes and link them to projects you have delivered.",
    "ai": "Add a small {skill} experiment to one of your AI tools and write up what you measured.",
    "leadership": "Collect two or three real {skill} examples from your work for interviews (STAR format).",
    "process": "Describe how your team applies {skill} and one improvement you drove.",
    "certification": "Book the {skill} exam date first, then plan study sessions backwards from it.",
    "other": "Find one small, public way to demonstrate {skill} and add it to your profile.",
}

WEIGHT_REQUIRED = 1.0
WEIGHT_NEUTRAL = 0.8
WEIGHT_PREFERRED = 0.4
WEIGHT_CONTEXT = 0.2

_PREFERRED_HEAD = re.compile(
    r"\b(nice to have|nice-to-have|preferred|bonus|desirable|good to have|a plus|advantage|optional)\b", re.I
)
_REQUIRED_HEAD = re.compile(
    r"\b(requirements?|required|must[- ]haves?|qualifications?|what you('ll| will)? (need|bring)"
    r"|what we('re| are) looking for|who you are|about you|skills|experience)\b",
    re.I,
)
_NEUTRAL_HEAD = re.compile(r"\b(responsibilit\w*|what you('ll| will) do|the role|about the role|your role|duties)\b", re.I)
_CONTEXT_HEAD = re.compile(r"\b(about us|about the company|who we are|benefits|what we offer|perks|why join)\b", re.I)
_INLINE_PREFERRED = re.compile(
    r"\b(?:(?:is|are|would be|will be)\s+(?:a|an)?\s*(?:big|huge|strong|great|real|definite)?\s*(?:plus|advantage|bonus)"
    r"|nice to have|preferred|bonus points?|desirable)\b",
    re.I,
)
_OR_SEPARATOR = re.compile(r"\s*(?:,\s*)?(?:or|/)\s*", re.I)


def normalise(name: str) -> str:
    return " ".join(name.lower().split())


def canonicalize(name: str, extra: dict[str, list[str]] | None = None) -> str:
    n = normalise(name)
    if n in TAXONOMY or (extra and n in extra):
        return n
    for canon, (_, aliases) in TAXONOMY.items():
        if n in aliases:
            return canon
    if extra:
        for canon, aliases in extra.items():
            if n in aliases:
                return canon
    return n


def category_of(skill: str) -> str:
    return TAXONOMY.get(skill, ("other", ()))[0]


def _freeze(extra: dict[str, list[str]] | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not extra:
        return ()
    return tuple(sorted((k, tuple(sorted(set(v)))) for k, v in extra.items()))


@lru_cache(maxsize=32)
def _compiled(frozen_extra: tuple[tuple[str, tuple[str, ...]], ...]) -> list[tuple[str, re.Pattern[str]]]:
    merged: dict[str, set[str]] = {canon: set(aliases) for canon, (_, aliases) in TAXONOMY.items()}
    for canon, aliases in frozen_extra:
        merged.setdefault(canon, set()).update(aliases)
    compiled = []
    for canon, aliases in merged.items():
        parts = []
        for alias in aliases:
            if alias.startswith("re:"):
                parts.append(alias[3:])
            else:
                parts.append(re.escape(alias.lower()).replace(r"\ ", " ").replace(" ", r"[\s\-]?"))
        if parts:
            body = "|".join(sorted(parts, key=len, reverse=True))
            compiled.append((canon, re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])", re.I)))
    return compiled


def extract_skills(text: str, extra: dict[str, list[str]] | None = None) -> set[str]:
    if not text:
        return set()
    return {canon for canon, pattern in _compiled(_freeze(extra)) if pattern.search(text)}


def skill_spans(text: str, extra: dict[str, list[str]] | None = None) -> list[tuple[int, int, str]]:
    spans = [(m.start(), m.end(), canon) for canon, pattern in _compiled(_freeze(extra)) for m in pattern.finditer(text)]
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:  # drop matches nested inside a longer one ("api testing" inside "rest api testing")
        if kept and span[0] < kept[-1][1]:
            continue
        kept.append(span)
    return kept


def _alternative_groups(line: str, spans: list[tuple[int, int, str]]) -> list[set[str]]:
    """Skills joined by 'or' or '/' ("Playwright or Selenium", "Jenkins/GitHub Actions") are alternatives."""
    groups: list[set[str]] = []
    current: set[str] = set()
    for (_, end, left), (start, _, right) in zip(spans, spans[1:]):
        if _OR_SEPARATOR.fullmatch(line[end:start]) and left != right:
            current |= {left, right}
        elif current:
            groups.append(current)
            current = set()
    if current:
        groups.append(current)
    return groups


def job_requirements(
    title: str, description: str, extra: dict[str, list[str]] | None = None
) -> tuple[dict[str, float], list[set[str]], set[str]]:
    """Return (weights, alternative groups, skills that also appear on their own).

    Weights: 1.0 required, 0.8 neutral, 0.4 preferred, 0.2 company context.
    """
    weights: dict[str, float] = {}
    groups: list[set[str]] = []
    standalone: set[str] = set()

    def bump(found: set[str], weight: float) -> None:
        for skill in found:
            weights[skill] = max(weights.get(skill, 0.0), weight)

    title_skills = extract_skills(title, extra)
    bump(title_skills, WEIGHT_REQUIRED)
    standalone |= title_skills
    mode = WEIGHT_NEUTRAL
    for raw in (description or "").splitlines():
        line = raw.strip(" \t•*-–·:#>")
        if not line:
            continue
        found = extract_skills(line, extra)
        is_heading = raw.rstrip().endswith(":") or (len(line.split()) <= 5 and not found)
        if is_heading and len(line) <= 60:
            if _CONTEXT_HEAD.search(line):
                mode = WEIGHT_CONTEXT
            elif _PREFERRED_HEAD.search(line):
                mode = WEIGHT_PREFERRED
            elif _NEUTRAL_HEAD.search(line):
                mode = WEIGHT_NEUTRAL
            elif _REQUIRED_HEAD.search(line):
                mode = WEIGHT_REQUIRED
        line_weight = WEIGHT_PREFERRED if _INLINE_PREFERRED.search(line) else mode
        bump(found, line_weight)
        if line_weight >= WEIGHT_PREFERRED:
            spans = skill_spans(line, extra)
            line_groups = _alternative_groups(line, spans)
            grouped = set().union(*line_groups) if line_groups else set()
            groups.extend(line_groups)
            standalone |= {canon for _, _, canon in spans if canon not in grouped}
    return weights, groups, standalone


def weighted_job_skills(title: str, description: str, extra: dict[str, list[str]] | None = None) -> dict[str, float]:
    return job_requirements(title, description, extra)[0]
