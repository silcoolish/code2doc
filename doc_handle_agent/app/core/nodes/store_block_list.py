"""存储Block列表节点."""

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


class StoreBlockListNode(WorkflowNode):
    """存储Block列表节点.

    调用workspace_service API创建/保存文档和上传资源。
    """

    def __init__(self, workspace_adapter: Optional[WorkspaceServiceAdapter] = None):
        """初始化节点.

        Args:
            workspace_adapter: workspace服务适配器，默认创建新实例
        """
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()

    @property
    def name(self) -> str:
        return "store_block_list"

    def _extract_title(self, state: AgentState) -> str:
        """从生成的blocks中提取文档标题.

        优先使用第一个一级标题(heading_level=1)的content_text，
        其次使用任意heading类型block，最后返回默认标题。
        """
        blocks = state.get("blocks", [])
        if not blocks:
            return "项目文档"

        # 优先找一级标题
        for block in blocks:
            if block.block_type == "heading" and block.heading_level == 1:
                return block.content_text or "项目文档"

        # 其次找任意heading
        for block in blocks:
            if block.block_type == "heading":
                return block.content_text or "项目文档"

        return "项目文档"

    async def execute(self, state: AgentState) -> AgentState:
        """构建文档.

        1. 构建文档blocks（包含生成的内容）
        2. 调用workspace_service创建/保存文档
        """
        logger.info(
            "workflow_node",
            node=self.name,
            repo_id=state["repo_id"],
            block_count=state["total_blocks"],
        )

        try:
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "正在构建最终文档..."

            doc_blocks = state.get("doc_blocks", [])
            if not doc_blocks:
                logger.warning("no_doc_blocks_in_state")

            # 清空 block id，交由 workspace 服务生成
            for block in doc_blocks:
                block["id"] = ""

            title = self._extract_title(state)
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=doc_blocks,
            )

            with log_timing("save_document", block_count=len(doc_blocks)):
                save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to save document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id
            state["status"] = GenerationStatus.COMPLETED.value
            state["message"] = "文档生成完成"

            logger.info(
                "store_block_list_success",
                document_id=document_id,
                title=title,
                block_count=len(doc_blocks),
                total_blocks=state["total_blocks"],
            )

        except Exception as e:
            logger.error(
                "store_block_list_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"文档构建失败: {str(e)}"

        return state
