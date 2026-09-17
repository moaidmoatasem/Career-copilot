"""The version is written in two places and shipped in a third. Keep them honest.

`pyproject.toml` sets the distribution version; `__init__.py` sets the one the MCP server
advertises and the news fetcher puts in its User-Agent. They drifted once; this catches it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import career_copilot

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

needs_repo = pytest.mark.skipif(not PYPROJECT.exists(), reason="not running from a source checkout")


@needs_repo
def test_package_version_matches_pyproject():
    packaged = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert career_copilot.__version__ == packaged, (
        f"__init__.py says {career_copilot.__version__}, pyproject.toml says {packaged}"
    )


@needs_repo
def test_current_version_has_a_changelog_entry():
    released = set(re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), re.M))
    assert career_copilot.__version__ in released, (
        f"CHANGELOG.md has no '## [{career_copilot.__version__}]' section"
    )


def test_version_is_a_release_number():
    assert re.fullmatch(r"\d+\.\d+\.\d+", career_copilot.__version__)
