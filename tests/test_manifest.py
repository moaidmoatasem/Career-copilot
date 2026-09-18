"""The Claude Desktop bundle manifest.

A manifest rots silently: a tool gets added, the manifest still advertises the old list, and nobody
notices until someone installs the extension. These tests make that a CI failure instead.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "manifest.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"
MCPBIGNORE = REPO_ROOT / ".mcpbignore"

needs_repo = pytest.mark.skipif(not MANIFEST.exists(), reason="not running from a source checkout")

pytestmark = needs_repo


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_required_fields_are_present(manifest):
    for field in ("manifest_version", "name", "version", "description", "author", "server"):
        assert manifest.get(field), f"manifest.json is missing {field}"
    assert manifest["author"].get("name")


def test_version_matches_pyproject(manifest):
    packaged = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert manifest["version"] == packaged, (
        f"manifest.json says {manifest['version']}, pyproject.toml says {packaged}"
    )


def test_server_launches_through_uv_from_the_bundle_directory(manifest):
    server = manifest["server"]
    assert server["type"] == "uv", "uv resolves Python and dependencies at install time"
    assert Path(REPO_ROOT / server["entry_point"]).exists(), "entry_point must point at a real file"

    config = server["mcp_config"]
    assert config["command"] == "uv"
    args = config["args"]
    assert "--directory" in args
    assert args[args.index("--directory") + 1] == "${__dirname}", (
        "must run from the installed bundle, not a hard-coded path"
    )
    assert "career-copilot-mcp" in args


def test_data_directory_is_user_configurable(manifest):
    home = manifest["server"]["mcp_config"]["env"]["CAREER_COPILOT_HOME"]
    assert home == "${user_config.data_directory}"
    option = manifest["user_config"]["data_directory"]
    assert option["type"] == "directory"
    assert option["default"].startswith("${HOME}")


def test_compatibility_matches_the_projects_python_floor(manifest):
    requires = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["requires-python"]
    declared = manifest["compatibility"]["runtimes"]["python"]
    assert declared.replace(" ", "") == requires.replace(" ", ""), (
        f"manifest says python {declared}, pyproject requires-python says {requires}"
    )


@pytest.mark.anyio
async def test_declared_tools_match_the_live_server(manifest):
    """The advertised tool list must be the real one."""
    from career_copilot import server as srv

    live = {tool.name for tool in await srv.mcp.list_tools()}
    declared = {entry["name"] for entry in manifest["tools"]}
    assert declared == live, (
        f"only in manifest: {sorted(declared - live)}; only on the server: {sorted(live - declared)}"
    )


def test_every_declared_tool_has_a_description(manifest):
    for entry in manifest["tools"]:
        assert entry.get("description", "").strip(), f"{entry['name']} has no description"


def test_bundle_excludes_personal_data_and_secrets():
    """A bundle is built from the working tree, not from git, so .gitignore does not protect it."""
    patterns = {
        line.strip()
        for line in MCPBIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for must_exclude in ("profile.toml", "my-profile.toml", "gmail-token.json",
                         "gmail-credentials.json", ".env", "*.db", "imports/", "tests/"):
        assert must_exclude in patterns, f".mcpbignore does not exclude {must_exclude}"


def test_manifest_is_valid_json_with_trailing_newline():
    text = MANIFEST.read_text(encoding="utf-8")
    assert text.endswith("\n")
    json.loads(text)
