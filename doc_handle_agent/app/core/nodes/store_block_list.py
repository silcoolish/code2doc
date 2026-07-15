"""存储Block列表节点."""

from typing import Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.document_caption import fill_missing_document_block_captions
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

    async def execute(self, state: AgentState) -> AgentState:
        """构建文档.

        1. 构建文档blocks（包含生成的内容）
        2. 调用workspace_service创建/保存文档
        """
        if state.get("error"):
            return state

        logger.info(
            "workflow_node",
            node=self.name,
            repo_id=state["repo_id"],
            block_count=state["total_blocks"],
        )

        try:
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "正在构建最终文档..."

            reporter = state.get("__progress_reporter")
            if reporter:
                await reporter.report_percent(0, "正在构建最终文档...")

            doc_blocks = state.get("doc_blocks", [])
            if not doc_blocks:
                # create_document 只创建占位文档；这里如果拿不到最终块，继续保存会把
                # 任务伪装成成功，因此直接失败交给上层处理。
                raise RuntimeError("No document blocks generated to persist")

            doc_blocks = fill_missing_document_block_captions(doc_blocks)
            state["doc_blocks"] = doc_blocks

            # 清空 block id，交由 workspace 服务生成
            for block in doc_blocks:
                block["id"] = ""

            title = state.get("title") or "项目文档"
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=doc_blocks,
                template_id=state.get("template_id"),
            )

            with log_timing("save_document", block_count=len(doc_blocks)):
                save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to save document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id
            state["status"] = GenerationStatus.BUILDING.value
            if reporter:
                await reporter.report_percent(100, "文档已保存")
            else:
                state["message"] = "文档已保存，正在收尾..."

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
