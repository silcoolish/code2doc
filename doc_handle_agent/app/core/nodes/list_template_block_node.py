"""列出模板Block节点."""

from typing import List, Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.workspace import WorkspaceServiceAdapter
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class ListTemplateBlockNode(WorkflowNode):
    """列出模板Block节点.

    从workspace_service获取模板block列表，直接存储到state中。
    不构建层级结构，不展平列表。
    """

    def __init__(self, workspace_adapter: Optional[WorkspaceServiceAdapter] = None):
        """初始化节点.

        Args:
            workspace_adapter: workspace服务适配器，默认创建新实例
        """
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()

    @property
    def name(self) -> str:
        return "list_template_block"

    async def execute(self, state: AgentState) -> AgentState:
        """获取模板block列表.

        1. 调用workspace_service获取模板block列表
        2. 直接存储到state中（保持原有顺序）
        3. 更新状态
        """
        template_id = state["template_id"]
        reporter = state.get("__progress_reporter")
        logger.info(
            "workflow_node",
            node=self.name,
            repo_id=state["repo_id"],
            template_id=template_id,
        )

        try:
            if reporter:
                await reporter.report_percent(0, "正在获取模板内容块列表...")

            with log_timing("list_template_blocks", template_id=template_id):
                blocks = await self.workspace_adapter.get_template_blocks(template_id)

            state["blocks"] = blocks
            state["total_blocks"] = len(blocks)
            state["status"] = GenerationStatus.GENERATING.value
            if reporter:
                await reporter.report_percent(100, f"获取完成，共{len(blocks)}个内容块待生成")
            else:
                state["message"] = f"获取完成，共{len(blocks)}个内容块待生成"

            logger.info(
                "list_template_block_success",
                template_id=template_id,
                block_count=len(blocks),
            )

        except Exception as e:
            logger.error(
                "list_template_block_failed",
                template_id=template_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"获取模板block列表失败: {str(e)}"

        return state
