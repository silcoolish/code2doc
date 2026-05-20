"""创建文档节点.

负责调用 workspace_service API 创建文档，获取 document_id。
"""

from typing import Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.workspace import (
    SaveDocumentRequest,
    WorkspaceServiceAdapter,
)
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class CreateDocumentNode(WorkflowNode):
    """创建文档节点.

    调用 workspace_service API 创建文档，获取 document_id 供后续节点使用。
    """

    def __init__(self, workspace_adapter: Optional[WorkspaceServiceAdapter] = None):
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()

    @property
    def name(self) -> str:
        return "create_document"

    async def execute(self, state: AgentState) -> AgentState:
        """创建文档.

        1. 从 blocks 中提取标题
        2. 调用 workspace_service 创建文档（blocks 留空，后续节点补充）
        3. 保存 document_id 到 state
        """
        if state.get("error"):
            return state

        doc_blocks = state.get("doc_blocks", [])
        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "正在创建文档..."

            if reporter:
                await reporter.report_percent(0, "正在创建文档...")

            title = self._extract_title(state)
            state["title"] = title

            # 创建文档时不传 blocks，由 store_block_list 统一保存
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=[],
            )

            with log_timing("create_document", repo_id=state["repo_id"]):
                save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to create document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id
            if reporter:
                await reporter.report_percent(100, "文档创建成功")
            else:
                state["message"] = "文档创建成功"

            logger.info(
                "create_document_success",
                document_id=document_id,
                title=title,
                repo_id=state["repo_id"],
            )

        except Exception as e:
            logger.error(
                "create_document_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"文档创建失败: {str(e)}"

        return state

    def _extract_title(self, state: AgentState) -> str:
        """从生成的 blocks 中提取文档标题."""
        blocks = state.get("blocks", [])
        if not blocks:
            return "项目文档"

        for block in blocks:
            if block.block_type == "heading" and block.heading_level == 1:
                return block.content_text or "项目文档"

        for block in blocks:
            if block.block_type == "heading":
                return block.content_text or "项目文档"

        return "项目文档"
