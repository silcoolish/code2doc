from unittest.mock import AsyncMock

import pytest

from app.core.nodes.validate_generation_policy_node import ValidateGenerationPolicyNode
from app.core.state import GenerationStatus, create_initial_state
from app.infrastructure.workspace import GenerationPlanValidationResponse


@pytest.mark.asyncio
async def test_generation_policy_node_allows_plan_within_limit():
    adapter = AsyncMock()
    adapter.validate_generation_plan.return_value = GenerationPlanValidationResponse(
        allowed=True,
        planned_block_count=2,
        block_limit=200,
        message="当前生成计划符合试用额度",
    )
    node = ValidateGenerationPolicyNode(adapter)
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [object(), object()]

    result = await node.execute(state)

    adapter.validate_generation_plan.assert_awaited_once_with(
        repo_id="repo-1",
        planned_block_count=2,
    )
    assert result["error"] is None
    assert result["generation_block_limit"] == 200
    assert result["message"] == "当前生成计划符合试用额度"


@pytest.mark.asyncio
async def test_generation_policy_node_stops_plan_that_exceeds_limit():
    message = (
        "当前仓库预计生成 326 个内容块，超过试用账号 200 个块的生成上限。"
        "试用账号暂不支持生成该规模的仓库文档，请联系管理员调整额度，或缩小文档生成范围。"
    )
    adapter = AsyncMock()
    adapter.validate_generation_plan.return_value = GenerationPlanValidationResponse(
        allowed=False,
        planned_block_count=326,
        block_limit=200,
        error_code="TRIAL_BLOCK_LIMIT_EXCEEDED",
        message=message,
    )
    node = ValidateGenerationPolicyNode(adapter)
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [object()] * 326

    result = await node.execute(state)

    assert result["status"] == GenerationStatus.FAILED.value
    assert result["error"] == message
    assert result["generation_policy_error_code"] == "TRIAL_BLOCK_LIMIT_EXCEEDED"
    assert result["generation_block_limit"] == 200


@pytest.mark.asyncio
async def test_generation_policy_node_fails_closed_when_workspace_is_unavailable():
    adapter = AsyncMock()
    adapter.validate_generation_plan.side_effect = RuntimeError("connection refused")
    node = ValidateGenerationPolicyNode(adapter)
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [object()]

    result = await node.execute(state)

    assert result["status"] == GenerationStatus.FAILED.value
    assert result["error"] == "额度校验服务暂不可用，已停止文档生成，请稍后重试。"
