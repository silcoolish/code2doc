from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.domain.content_generator_agent import ContentGeneratorAgent


class _McpClient:
    client = object()

    def __init__(self):
        self.calls = []

    def get_available_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_nodes",
                    "description": "search nodes",
                    "parameters": {
                        "type": "object",
                        "properties": {"repo_id": {"type": "string"}},
                    },
                },
            }
        ]

    async def call_tool(self, tool_name, tool_args):
        self.calls.append((tool_name, tool_args))
        return '{"nodes":[{"name":"Sensor_Init"}]}'


class _BoundToolModel:
    async def ainvoke(self, messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_nodes",
                    "args": {"repo_id": "wrong-repo"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        )


class _FinalizingModel:
    model_name = "test-model"

    def bind_tools(self, tools):
        return _BoundToolModel()

    async def ainvoke(self, messages):
        return AIMessage(content='["Sensor_Init"]')


@pytest.mark.asyncio
async def test_generate_with_tools_finalizes_after_last_iteration_tool_call(monkeypatch):
    agent_logger = MagicMock()
    monkeypatch.setattr(
        "app.domain.content_generator_agent.get_agent_logger",
        lambda **kwargs: agent_logger,
    )
    mcp_client = _McpClient()
    agent = ContentGeneratorAgent(mcp_client, llm_client=_FinalizingModel())

    result = await agent.generate_with_tools(
        system_prompt="只返回 JSON 数组",
        task_message="列出函数",
        repo_id="repo-1",
        max_iterations=1,
    )

    assert result == '["Sensor_Init"]'
    assert mcp_client.calls[0][0] == "search_nodes"
    assert mcp_client.calls[0][1]["repo_id"] == "repo-1"
    completion = agent_logger.log_agent_completion.call_args.kwargs
    assert completion["reason"] == "max_iterations_finalized"
    assert completion["final_content"] == '["Sensor_Init"]'


class _RetryingFinalizationModel(_FinalizingModel):
    def __init__(self):
        self.finalization_calls = 0

    async def ainvoke(self, messages):
        self.finalization_calls += 1
        if self.finalization_calls == 1:
            return AIMessage(
                content=(
                    '<｜｜DSML｜｜tool_calls>\n'
                    '<｜｜DSML｜｜invoke name="search_nodes">'
                )
            )
        return AIMessage(content='["Sensor_Init"]')


@pytest.mark.asyncio
async def test_generate_with_tools_retries_textual_tool_call_during_finalization(monkeypatch):
    agent_logger = MagicMock()
    monkeypatch.setattr(
        "app.domain.content_generator_agent.get_agent_logger",
        lambda **kwargs: agent_logger,
    )
    model = _RetryingFinalizationModel()
    agent = ContentGeneratorAgent(_McpClient(), llm_client=model)

    result = await agent.generate_with_tools(
        system_prompt="只返回 JSON 数组",
        task_message="列出函数",
        repo_id="repo-1",
        max_iterations=1,
    )

    assert result == '["Sensor_Init"]'
    assert model.finalization_calls == 2
    completion = agent_logger.log_agent_completion.call_args.kwargs
    assert completion["reason"] == "max_iterations_finalized"


class _PersistentToolCallModel(_FinalizingModel):
    async def ainvoke(self, messages):
        return AIMessage(content="<||DSML||tool_calls>\n<||DSML||invoke>")


@pytest.mark.asyncio
async def test_generate_with_tools_rejects_persistent_textual_tool_calls(monkeypatch):
    agent_logger = MagicMock()
    monkeypatch.setattr(
        "app.domain.content_generator_agent.get_agent_logger",
        lambda **kwargs: agent_logger,
    )
    agent = ContentGeneratorAgent(_McpClient(), llm_client=_PersistentToolCallModel())

    with pytest.raises(RuntimeError, match="最终收口阶段"):
        await agent.generate_with_tools(
            system_prompt="只返回 JSON 数组",
            task_message="列出函数",
            repo_id="repo-1",
            max_iterations=1,
        )

    completion = agent_logger.log_agent_completion.call_args.kwargs
    assert completion["reason"] == "max_iterations_finalization_failed"
