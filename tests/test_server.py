import json

import pytest
from mcp import Client

import career_copilot.server as server

pytestmark = pytest.mark.anyio


@pytest.fixture
def srv(home):
    server._service = None
    yield server.mcp
    if server._service is not None:
        server._service.store.close()
    server._service = None


async def test_tool_surface_has_no_approval_path(srv):
    async with Client(srv) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"ingest_email", "list_jobs", "draft_message_reply", "mark_executed", "build_learning_plan",
            "check_sponsor_licence", "import_sponsor_register"} <= set(tools)
    assert not [name for name in tools if name.startswith(("approve", "reject", "send", "post_", "apply"))]
    assert tools["list_jobs"].annotations.read_only_hint is True
    assert tools["draft_post"].annotations.destructive_hint is False
    assert tools["refresh_news"].annotations.open_world_hint is True
    # The register check only reads the local database: no network, nothing to change.
    assert tools["check_sponsor_licence"].annotations.read_only_hint is True
    assert tools["check_sponsor_licence"].annotations.open_world_hint is False


async def test_round_trip_and_errors_over_protocol(srv):
    async with Client(srv) as client:
        added = await client.call_tool("add_job", {"title": "Senior QA Engineer", "company": "Acme", "location": "Dubai"})
        assert not added.is_error
        listed = await client.call_tool("list_jobs", {})
        payload = json.loads(listed.content[0].text)
        assert payload["jobs"][0]["title"] == "Senior QA Engineer"
        missing = await client.call_tool("get_job", {"job_id": 999})
        assert missing.is_error and "not found" in missing.content[0].text
        bad_enum = await client.call_tool("list_jobs", {"tier": "amazing"})
        assert bad_enum.is_error


async def test_prompts(srv):
    async with Client(srv) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        assert names == {"daily_triage", "weekly_career_review", "job_deep_dive", "profile_refresh"}
        prompt = await client.get_prompt("daily_triage", {"days": "2"})
        assert "from:linkedin.com newer_than:2d" in prompt.messages[0].content.text
