"""文档生成额度校验节点."""

from typing import Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.workspace import WorkspaceServiceAdapter
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ValidateGenerationPolicyNode(WorkflowNode):
    """在大纲展开后校验当前账号的文档生成额度."""

    def __init__(
        self,
        workspace_adapter: Optional[WorkspaceServiceAdapter] = None,
    ):
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()

    @property
    def name(self) -> str:
        return "validate_generation_policy"

    async def execute(self, state: AgentState) -> AgentState:
        """提交最终预计块数并在正文生成前完成额度拦截."""
        if state.get("error"):
            return state

        blocks = state.get("blocks", [])
        planned_block_count = len(blocks)
        reporter = state.get("__progress_reporter")
        if planned_block_count <= 0:
            return state

        if reporter:
            await reporter.report_percent(0, "正在校验文档生成额度...")

        try:
            result = await self.workspace_adapter.validate_generation_plan(
                repo_id=state["repo_id"],
                planned_block_count=planned_block_count,
            )
            state["generation_block_limit"] = result.block_limit
            state["generation_policy_error_code"] = result.error_code
            if not result.allowed:
                message = result.message or "当前文档生成计划超过试用账号额度"
                state["error"] = message
                state["status"] = GenerationStatus.FAILED.value
                state["message"] = message
                if reporter:
                    await reporter.report_percent(100, message)
                logger.warning(
                    "generation_policy_rejected",
                    repo_id=state["repo_id"],
                    planned_block_count=planned_block_count,
                    block_limit=result.block_limit,
                    error_code=result.error_code,
                )
                return state

            message = result.message or "文档生成额度校验通过"
            state["message"] = message
            if reporter:
                await reporter.report_percent(100, message)
            logger.info(
                "generation_policy_allowed",
                repo_id=state["repo_id"],
                planned_block_count=planned_block_count,
                block_limit=result.block_limit,
            )
        except Exception as exc:
            message = "额度校验服务暂不可用，已停止文档生成，请稍后重试。"
            state["error"] = message
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = message
            if reporter:
                await reporter.report_percent(100, message)
            logger.error(
                "generation_policy_validation_failed",
                repo_id=state["repo_id"],
                planned_block_count=planned_block_count,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )

        return state
