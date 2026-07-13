"""创建文档节点.

负责调用 workspace_service API 创建文档，获取 document_id。
"""

import asyncio
import re
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

        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "正在创建文档..."

            if reporter:
                await reporter.report_percent(0, "正在创建文档...")

            title = await self._resolve_title(state)
            state["title"] = title

            # 创建文档时不传 blocks，由 store_block_list 统一保存
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                doc_type="project",
                target_key="__project__",
                title=title,
                blocks=[],
                template_id=state.get("template_id"),
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

    async def _resolve_title(self, state: AgentState) -> str:
        """按项目名称和模板名称生成稳定的文档标题

        元数据读取失败时不影响文档生成，依次退化为可用的单项名称、
        大纲首个标题和固定默认名称

        Args:
            state: 当前工作流状态

        Returns:
            用于创建文档的标题
        """
        repo_result, template_result = await asyncio.gather(
            self.workspace_adapter.get_repo_name(state.get("repo_id", "")),
            self.workspace_adapter.get_template_name(state.get("template_id", "")),
            return_exceptions=True,
        )
        if isinstance(repo_result, Exception):
            logger.warning(
                "document_title_repo_name_unavailable",
                repo_id=state.get("repo_id"),
                error=str(repo_result),
            )
        if isinstance(template_result, Exception):
            logger.warning(
                "document_title_template_name_unavailable",
                template_id=state.get("template_id"),
                error=str(template_result),
            )
        repo_name = repo_result if isinstance(repo_result, str) else ""
        template_name = template_result if isinstance(template_result, str) else ""
        document_type = re.sub(r"\s*模板\s*$", "", template_name).strip()

        if repo_name and document_type:
            return f"{repo_name} - {document_type}"
        if document_type:
            return document_type
        if repo_name:
            return repo_name
        return self._extract_outline_title(state)

    @staticmethod
    def _extract_outline_title(state: AgentState) -> str:
        """从大纲提取旧版兼容标题"""
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
