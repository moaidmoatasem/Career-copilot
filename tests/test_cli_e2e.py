import pytest
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

SRC = str(Path(__file__).resolve().parents[1] / "src")

pytestmark = pytest.mark.anyio


def _env(home):
    env = dict(os.environ)
    env.update({"CAREER_COPILOT_HOME": str(home), "PYTHONPATH": SRC})
    env.pop("CAREER_COPILOT_PROFILE", None)
    return env


def test_review_refuses_without_a_terminal(tmp_path):
    result = subprocess.run([sys.executable, "-m", "career_copilot.cli", "review"], input="a\n",
                            capture_output=True, text=True, env=_env(tmp_path))
    assert result.returncode == 2
    assert "interactive terminal" in result.stderr


def test_init_creates_profile_and_prints_config(tmp_path):
    result = subprocess.run([sys.executable, "-m", "career_copilot.cli", "init"], capture_output=True, text=True,
                            env=_env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "profile.toml").exists() and (tmp_path / "imports").is_dir()
    assert '"career-copilot"' in result.stdout


async def test_stdio_server_end_to_end(tmp_path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "career_copilot.server"], env=_env(tmp_path))
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        assert len(tools) >= 25
        status = await client.call_tool("get_status", {})
        assert json.loads(status.content[0].text)["profile_configured"] is False
