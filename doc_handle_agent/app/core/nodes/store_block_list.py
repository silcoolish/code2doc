"""存储Block列表节点."""

from pathlib import Path
from typing import List, Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.model import ImageInfo, TemplateBlock
from app.infrastructure.workspace import (
    SaveDocumentRequest,
    WorkspaceServiceAdapter,
)
from app.utils.logger import get_logger

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
        3. 上传图片资源
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

            # 1. 构建文档blocks
            doc_blocks = self._build_document_blocks(state)

            # 2. 获取文档标题（从第一个标题block或默认）
            title = self._get_document_title(state)

            # 3. 调用API保存文档
            save_request = SaveDocumentRequest(
                repo_id=state["repo_id"],
                title=title,
                blocks=doc_blocks,
            )

            save_response = await self.workspace_adapter.save_document(save_request)

            if not save_response.success:
                raise RuntimeError(f"Failed to save document: {save_response.error}")

            document_id = save_response.document_id
            state["document_id"] = document_id

            logger.info(
                "document_saved",
                document_id=document_id,
                title=title,
                block_count=len(doc_blocks),
            )

            # 4. 上传图片资源
            await self._upload_resources(state, document_id)

            state["status"] = GenerationStatus.COMPLETED.value
            state["message"] = f"文档生成完成，文档ID: {document_id}"

            logger.info(
                "store_block_list_success",
                document_id=document_id,
                total_blocks=state["total_blocks"],
            )

        except Exception as e:
            logger.error(
                "store_block_list_failed",
                error=str(e),
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"文档构建失败: {str(e)}"

        return state

    def _build_document_blocks(self, state: AgentState) -> List[dict]:
        """构建文档blocks.

        将生成的内容整合到block结构中。

        Args:
            state: 工作流状态

        Returns:
            文档block列表
        """
        blocks: List[TemplateBlock] = state.get("blocks", [])
        generated_contents = state.get("generated_contents", {})
        doc_blocks: List[dict] = []

        for block in blocks:
            # 获取生成的内容
            content_results = generated_contents.get(block.id, [])

            # 构建block数据
            block_data = {
                "id": "",  # 新block，id传空
                "blockType": block.block_type,
                "blockTitle": block.block_title,
                "headingLevel": block.heading_level,
                "orderNo": block.order_no,
                "markdownContent": block.markdown_content,
                "textContent": block.text_content,
                "template": block.template,
                "attrs": block.attrs,
                "sourceRefs": block.source_refs,
            }

            # 如果有生成结果，更新text_content
            if content_results:
                if block.is_list:
                    # 列表block，需要合并所有列表项的内容
                    text_contents = []
                    for result in content_results:
                        text_contents.append(result.text_content)
                        # 处理子内容
                        if result.children:
                            for child in result.children:
                                text_contents.append(child.text_content)
                    block_data["textContent"] = "\n".join(text_contents)
                else:
                    # 单一block
                    result = content_results[0]
                    block_data["textContent"] = result.text_content

            doc_blocks.append(block_data)

        return doc_blocks

    def _get_document_title(self, state: AgentState) -> str:
        """获取文档标题.

        从第一个标题block获取，或使用默认标题。

        Args:
            state: 工作流状态

        Returns:
            文档标题
        """
        blocks: List[TemplateBlock] = state.get("blocks", [])

        for block in blocks:
            if block.is_heading and block.block_title:
                return block.block_title

        # 默认标题
        return f"项目技术文档 - {state['repo_id']}"

    async def _upload_resources(
        self,
        state: AgentState,
        document_id: str,
    ) -> None:
        """上传资源文件.

        Args:
            state: 工作流状态
            document_id: 文档ID
        """
        generated_images = state.get("generated_images", {})

        if not generated_images:
            return

        total_images = sum(len(images) for images in generated_images.values())
        logger.info(
            "upload_resources_start",
            document_id=document_id,
            total_images=total_images,
        )

        uploaded_count = 0
        failed_count = 0

        for block_id, images in generated_images.items():
            for image_info in images:
                if not image_info.image_path:
                    continue

                image_path = Path(image_info.image_path)
                if not image_path.exists():
                    logger.warning(
                        "image_file_not_found",
                        block_id=block_id,
                        image_path=str(image_path),
                    )
                    failed_count += 1
                    continue

                try:
                    response = await self.workspace_adapter.upload_resource(
                        owner_type="document",
                        owner_id=document_id,
                        resource_type="flowchart",  # 目前主要是流程图
                        file_path=image_path,
                        block_id=block_id,
                    )

                    if response.success:
                        uploaded_count += 1
                        logger.debug(
                            "resource_uploaded",
                            block_id=block_id,
                            resource_id=response.resource_id,
                        )
                    else:
                        failed_count += 1
                        logger.warning(
                            "resource_upload_failed",
                            block_id=block_id,
                            error=response.error,
                        )

                except Exception as e:
                    failed_count += 1
                    logger.error(
                        "resource_upload_error",
                        block_id=block_id,
                        error=str(e),
                    )

        logger.info(
            "upload_resources_complete",
            document_id=document_id,
            uploaded=uploaded_count,
            failed=failed_count,
        )
