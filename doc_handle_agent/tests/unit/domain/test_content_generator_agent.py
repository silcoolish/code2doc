from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from app.domain.content_generator_agent import ContentGeneratorAgent


class _McpClient:
    client = object()

    def get_available_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_nodes",
                    "description": "search nodes",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    async def call_tool(self, tool_name, tool_args):
        return '{"nodes":[{"name":"Sensor_Init"}]}'


class _BoundToolModel:
    async def ainvoke(self, messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_nodes",
                    "args": {},
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
    agent = ContentGeneratorAgent(_McpClient(), llm_client=_FinalizingModel())

    result = await agent.generate_with_tools(
        system_prompt="只返回 JSON 数组",
        task_message="列出函数",
        repo_id="repo-1",
        max_iterations=1,
    )

    assert result == '["Sensor_Init"]'
    completion = agent_logger.log_agent_completion.call_args.kwargs
    assert completion["reason"] == "max_iterations_finalized"
    assert completion["final_content"] == '["Sensor_Init"]'
