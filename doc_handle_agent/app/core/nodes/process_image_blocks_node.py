"""处理图片块节点.

在内容生成完成后，遍历文档块中的图片类型块，
调用 workspace 资源接口创建 external_url 记录，
将图片块转换为 workspace 期望的标准格式。
"""

from typing import Any, Dict, List, Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.workspace import (
    SaveResourceRequest,
    SaveResourceResponse,
    WorkspaceServiceAdapter,
)
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class ProcessImageBlocksNode(WorkflowNode):
    """处理图片块节点.

    负责：
    1. 识别文档块中的图片类型块
    2. 提取图片 URL 和 caption
    3. 调用 workspace API 创建 external_url 资源记录
    4. 更新图片块为标准格式（blockType="image", attrs.assetId 等）
    """

    def __init__(
        self,
        workspace_adapter: Optional[WorkspaceServiceAdapter] = None,
    ):
        """初始化节点.

        Args:
            workspace_adapter: workspace 服务适配器，默认创建新实例
        """
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()

    @property
    def name(self) -> str:
        return "process_image_blocks"

    async def execute(self, state: AgentState) -> AgentState:
        """处理图片块.

        Args:
            state: 当前工作流状态

        Returns:
            更新后的状态
        """
        if state.get("error"):
            return state

        doc_blocks = state.get("doc_blocks", [])
        if not doc_blocks:
            logger.info("no_doc_blocks_to_process")
            return state

        document_id = state.get("document_id")
        if not document_id:
            logger.error("document_id_not_found")
            state["error"] = "document_id 不存在，无法创建图片资源"
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = "图片资源处理失败: 文档尚未创建"
            return state

        try:
            state["status"] = GenerationStatus.GENERATING.value
            state["message"] = "正在处理图片资源..."

            with log_timing("process_image_blocks", block_count=len(doc_blocks)):
                updated_blocks = await self._process_blocks(
                    doc_blocks,
                    document_id=document_id,
                )

            state["doc_blocks"] = updated_blocks

            logger.info(
                "process_image_blocks_complete",
                total_blocks=len(doc_blocks),
                repo_id=state["repo_id"],
            )

        except Exception as e:
            logger.error(
                "process_image_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"图片资源处理失败: {str(e)}"

        return state

    async def _process_blocks(
        self,
        doc_blocks: List[Dict[str, Any]],
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """处理文档块列表中的图片块.

        Args:
            doc_blocks: 文档块列表
            document_id: 文档 ID

        Returns:
            更新后的文档块列表
        """
        updated_blocks: List[Dict[str, Any]] = []

        for block in doc_blocks:
            if block.get("blockType") == "image":
                processed = await self._process_image_block(block, document_id)
                updated_blocks.append(processed)
            else:
                updated_blocks.append(block)

        return updated_blocks

    async def _process_image_block(
        self,
        block: Dict[str, Any],
        document_id: str,
    ) -> Dict[str, Any]:
        """处理单个图片块.

        提取图片 URL，创建资源记录，更新块格式。

        Args:
            block: 原始图片块数据
            document_id: 文档 ID

        Returns:
            更新后的图片块数据
        """
        image_url = self._extract_image_url(block)
        if not image_url:
            logger.warning(
                "image_url_not_found",
                block_content=block.get("contentText", "")[:100],
            )
            return block

        caption = self._extract_caption(block) or ""

        resource_response = await self._create_resource(
            image_url=image_url,
            document_id=document_id,
            caption=caption,
        )

        if not resource_response.success or not resource_response.resource_id:
            logger.error(
                "create_image_resource_failed",
                image_url=image_url,
                error=resource_response.error,
            )
            return block

        asset_id = resource_response.resource_id
        logger.info(
            "image_resource_created",
            asset_id=asset_id,
            image_url=image_url,
            caption=caption,
        )

        return {
            **block,
            "blockType": "image",
            "contentText": caption,
            "attrs": {
                **block.get("attrs", {}),
                "assetId": asset_id,
                "caption": caption,
                "alt": caption,
            },
        }

    async def _create_resource(
        self,
        image_url: str,
        document_id: str,
        caption: str,
    ) -> SaveResourceResponse:
        """调用 workspace API 创建图片资源记录.

        Args:
            image_url: 图片外部 URL
            document_id: 文档 ID（用作 owner_id）
            caption: 图片标题（用于生成文件名）

        Returns:
            资源创建响应
        """
        file_name = self._extract_file_name(image_url) or "image.png"
        mime_type = self._guess_mime_type(image_url)

        request = SaveResourceRequest(
            owner_type="document",
            owner_id=document_id,
            resource_type="image",
            file_name=file_name,
            mime_type=mime_type,
            storage_path=image_url,
        )

        return await self.workspace_adapter.save_resource(request)

    @staticmethod
    def _extract_image_url(block: Dict[str, Any]) -> Optional[str]:
        """从块数据中提取图片 URL.

        图片 URL 直接存储在 contentText 中。

        Args:
            block: 块数据

        Returns:
            图片 URL 或 None
        """
        content = block.get("contentText", "")
        if not content:
            return None

        stripped = content.strip()
        if stripped.startswith(("http://", "https://")):
            return stripped

        return None

    @staticmethod
    def _extract_caption(block: Dict[str, Any]) -> str:
        """从块数据中提取图片标题/说明.

        直接返回 contentText 的内容（排除纯 URL 的情况）。

        Args:
            block: 块数据

        Returns:
            图片标题
        """
        content = block.get("contentText", "")
        if not content:
            return ""

        # 排除纯 URL 的情况
        stripped = content.strip()
        if not stripped.startswith(("http://", "https://")):
            return stripped

        return ""

    @staticmethod
    def _extract_file_name(url: str) -> Optional[str]:
        """从 URL 中提取文件名.

        Args:
            url: 图片 URL

        Returns:
            文件名或 None
        """
        try:
            from urllib.parse import urlparse

            path = urlparse(url).path
            if path:
                name = path.split("/")[-1]
                if name and "." in name:
                    return name
        except Exception:
            pass
        return None

    @staticmethod
    def _guess_mime_type(url: str) -> str:
        """根据 URL 后缀猜测 MIME 类型.

        Args:
            url: 图片 URL

        Returns:
            MIME 类型字符串
        """
        url_lower = url.lower()
        if url_lower.endswith(".svg"):
            return "image/svg+xml"
        if url_lower.endswith(".png"):
            return "image/png"
        if url_lower.endswith(".jpg") or url_lower.endswith(".jpeg"):
            return "image/jpeg"
        if url_lower.endswith(".gif"):
            return "image/gif"
        if url_lower.endswith(".webp"):
            return "image/webp"
        return "image/png"
