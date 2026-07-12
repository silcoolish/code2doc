import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.content_generator_agent import ContentGeneratorAgent


def _build_agent(call_tool):
    mcp_client = MagicMock()
    mcp_client.call_tool = call_tool
    llm_client = SimpleNamespace(model_name="test-model")
    return ContentGeneratorAgent(mcp_client, llm_client=llm_client)


@pytest.mark.asyncio
async def test_call_tool_reuses_identical_inflight_request():
    release = asyncio.Event()
    call_count = 0

    async def call_tool(tool_name, tool_args):
        nonlocal call_count
        call_count += 1
        await release.wait()
        return f"{tool_name}:{tool_args['repo_id']}"

    agent = _build_agent(call_tool)
    tasks = [
        asyncio.create_task(agent.call_tool("get_project_structure", {"repo_id": "repo-1"}))
        for _ in range(10)
    ]
    await asyncio.sleep(0)
    release.set()

    results = await asyncio.gather(*tasks)

    assert call_count == 1
    assert results == ["get_project_structure:repo-1"] * 10
    assert not agent._tool_result_inflight


@pytest.mark.asyncio
async def test_call_tool_keeps_different_arguments_independent():
    call_count = 0

    async def call_tool(tool_name, tool_args):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)
        return tool_args["repo_id"]

    agent = _build_agent(call_tool)

    results = await asyncio.gather(
        agent.call_tool("get_project_structure", {"repo_id": "repo-1"}),
        agent.call_tool("get_project_structure", {"repo_id": "repo-2"}),
    )

    assert call_count == 2
    assert results == ["repo-1", "repo-2"]


@pytest.mark.asyncio
async def test_call_tool_cancellation_does_not_cancel_shared_request():
    release = asyncio.Event()
    call_count = 0

    async def call_tool(tool_name, tool_args):
        nonlocal call_count
        call_count += 1
        await release.wait()
        return "ok"

    agent = _build_agent(call_tool)
    cancelled_waiter = asyncio.create_task(
        agent.call_tool("get_project_structure", {"repo_id": "repo-1"})
    )
    surviving_waiter = asyncio.create_task(
        agent.call_tool("get_project_structure", {"repo_id": "repo-1"})
    )
    await asyncio.sleep(0)
    cancelled_waiter.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter
    assert await surviving_waiter == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_call_tool_reuses_and_caches_shared_failure():
    call_count = 0

    async def call_tool(tool_name, tool_args):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)
        raise RuntimeError("knowledge service unavailable")

    agent = _build_agent(call_tool)

    results = await asyncio.gather(*(
        agent.call_tool("get_project_structure", {"repo_id": "repo-1"})
        for _ in range(10)
    ))
    cached_result = await agent.call_tool(
        "get_project_structure",
        {"repo_id": "repo-1"},
    )

    expected = "工具调用失败: knowledge service unavailable"
    assert call_count == 1
    assert results == [expected] * 10
    assert cached_result == expected
