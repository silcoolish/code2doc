"""Workspace服务适配器.

封装与workspace_service的交互，提供模板获取、文档保存和资源上传功能。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.infrastructure.http import HttpUtils
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TemplateBlock:
    """模板条目（Block）数据类.

    对应workspace_service返回的block结构。
    """

    id: str
    parent_block_id: Optional[str]
    block_type: str  # "heading" | "paragraph"
    block_title: str
    heading_level: int
    order_no: int
    markdown_content: str
    text_content: str
    template: str  # "static" | "template"
    attrs: Dict[str, Any] = field(default_factory=dict)
    source_refs: List[str] = field(default_factory=list)

    @property
    def is_template(self) -> bool:
        """是否为模板内容块."""
        return self.template == "template"

    @property
    def is_heading(self) -> bool:
        """是否为标题."""
        return self.block_type == "heading"

    @property
    def is_list(self) -> bool:
        """是否生成列表."""
        return self.attrs.get("list", False)

    @property
    def prompt(self) -> Optional[str]:
        """获取生成提示词."""
        return self.attrs.get("prompt")

    @property
    def min_length(self) -> Optional[int]:
        """获取最小长度限制."""
        value = self.attrs.get("min_length")
        return int(value) if value is not None else None

    @property
    def max_length(self) -> Optional[int]:
        """获取最大长度限制."""
        value = self.attrs.get("max_length")
        return int(value) if value is not None else None

    @property
    def example(self) -> Optional[str]:
        """获取参考示例."""
        return self.attrs.get("example")

    @property
    def img(self) -> Optional[str]:
        """获取图片搜索提示词."""
        return self.attrs.get("img")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "parent_block_id": self.parent_block_id,
            "block_type": self.block_type,
            "block_title": self.block_title,
            "heading_level": self.heading_level,
            "order_no": self.order_no,
            "markdown_content": self.markdown_content,
            "text_content": self.text_content,
            "template": self.template,
            "attrs": self.attrs,
            "source_refs": self.source_refs,
        }


@dataclass
class SaveDocumentRequest:
    """保存文档请求."""

    repo_id: str
    title: str
    blocks: List[Dict[str, Any]]
    document_kind: str = "project"
    node_id: str = "__project__"
    subtitle: str = ""
    summary: str = ""
    focus_path: Optional[str] = None
    raw_markdown: str = ""
    snapshot_hash: str = ""
    source: str = "agent"
    status: str = "draft"
    created_by: str = "agent"

    def to_api_payload(self) -> Dict[str, Any]:
        """转换为API请求体."""
        return {
            "repoId": self.repo_id,
            "documentKind": self.document_kind,
            "nodeId": self.node_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "summary": self.summary,
            "focusPath": self.focus_path,
            "rawMarkdown": self.raw_markdown,
            "snapshotHash": self.snapshot_hash,
            "source": self.source,
            "status": self.status,
            "createdBy": self.created_by,
            "blocks": self.blocks,
        }


@dataclass
class SaveDocumentResponse:
    """保存文档响应."""

    success: bool
    document_id: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


@dataclass
class UploadResourceResponse:
    """上传资源响应."""

    success: bool
    resource_id: Optional[str] = None
    url: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class WorkspaceServiceAdapter:
    """Workspace服务适配器.

    封装与workspace_service的所有交互。
    """

    def __init__(self, base_url: Optional[str] = None):
        """初始化适配器.

        Args:
            base_url: workspace服务基础URL，默认从配置读取
        """
        settings = get_settings()
        self.base_url = base_url or settings.workspace_service_url
        self.http = HttpUtils()

        logger.info(
            "workspace_adapter_initialized",
            base_url=self.base_url,
        )

    def _build_url(self, path: str) -> str:
        """构建完整URL.

        Args:
            path: API路径

        Returns:
            完整URL
        """
        base = self.base_url.rstrip("/")
        path = path.lstrip("/")
        return f"{base}/{path}"

    async def get_template_blocks(self, template_id: str) -> List[TemplateBlock]:
        """获取模板条目列表.

        Args:
            template_id: 模板ID

        Returns:
            Block列表

        Raises:
            httpx.HTTPError: 请求失败
            ValueError: 响应格式错误
        """
        url = self._build_url(f"/api/templates/{template_id}/blocks")

        logger.info(
            "get_template_blocks_request",
            template_id=template_id,
            url=url,
        )

        try:
            response = await self.http.get(url)

            if not response.get("success"):
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "get_template_blocks_failed",
                    template_id=template_id,
                    error=error_msg,
                )
                raise ValueError(f"Failed to get template blocks: {error_msg}")

            data = response.get("data", [])
            blocks = []

            for item in data:
                block = TemplateBlock(
                    id=item.get("id", ""),
                    parent_block_id=item.get("parentBlockId"),
                    block_type=item.get("blockType", "paragraph"),
                    block_title=item.get("blockTitle", ""),
                    heading_level=item.get("headingLevel", 0),
                    order_no=item.get("orderNo", 0),
                    markdown_content=item.get("markdownContent", ""),
                    text_content=item.get("textContent", ""),
                    template=item.get("templateType", "static"),
                    attrs=item.get("attrs", {}),
                    source_refs=item.get("sourceRefs", []),
                )
                blocks.append(block)

            logger.info(
                "get_template_blocks_success",
                template_id=template_id,
                block_count=len(blocks),
            )

            return blocks

        except Exception as e:
            logger.error(
                "get_template_blocks_error",
                template_id=template_id,
                error=str(e),
            )
            raise

    async def save_document(self, request: SaveDocumentRequest) -> SaveDocumentResponse:
        """创建或保存文档.

        Args:
            request: 保存文档请求

        Returns:
            保存文档响应
        """
        url = self._build_url("/api/documents/save")

        logger.info(
            "save_document_request",
            repo_id=request.repo_id,
            title=request.title,
            block_count=len(request.blocks),
        )

        try:
            response = await self.http.post(
                url,
                json_data=request.to_api_payload(),
            )

            if response.get("success"):
                logger.info(
                    "save_document_success",
                    repo_id=request.repo_id,
                    document_id=response.get("data", {}).get("id"),
                )
                return SaveDocumentResponse(
                    success=True,
                    document_id=response.get("data", {}).get("id"),
                    message=response.get("message"),
                )
            else:
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "save_document_failed",
                    repo_id=request.repo_id,
                    error=error_msg,
                )
                return SaveDocumentResponse(
                    success=False,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(
                "save_document_error",
                repo_id=request.repo_id,
                error=str(e),
            )
            return SaveDocumentResponse(
                success=False,
                error=str(e),
            )

    async def upload_resource(
        self,
        owner_type: str,
        owner_id: str,
        resource_type: str,
        file_path: Path,
        block_id: Optional[str] = None,
    ) -> UploadResourceResponse:
        """上传资源文件.

        Args:
            owner_type: 归属类型 (document/template)
            owner_id: 归属对象ID
            resource_type: 资源类型 (image/flowchart/callgraph)
            file_path: 文件路径
            block_id: 所属条目ID（可选）

        Returns:
            上传资源响应
        """
        url = self._build_url("/api/resources/upload")

        logger.info(
            "upload_resource_request",
            owner_type=owner_type,
            owner_id=owner_id,
            resource_type=resource_type,
            file_path=str(file_path),
            block_id=block_id,
        )

        try:
            # 读取文件内容
            with open(file_path, "rb") as f:
                file_content = f.read()

            # 获取文件类型
            content_type = self._get_content_type(file_path)

            # 构建文件字典
            files = {
                "file": (
                    file_path.name,
                    file_content,
                    content_type,
                )
            }

            # 构建表单数据
            data = {
                "ownerType": owner_type,
                "ownerId": owner_id,
                "resourceType": resource_type,
            }
            if block_id:
                data["blockId"] = block_id

            response = await self.http.post_multipart(
                url,
                files=files,
                data=data,
            )

            if response.get("success"):
                data = response.get("data", {})
                logger.info(
                    "upload_resource_success",
                    owner_id=owner_id,
                    resource_id=data.get("id"),
                )
                return UploadResourceResponse(
                    success=True,
                    resource_id=data.get("id"),
                    url=data.get("url"),
                    message=response.get("message"),
                )
            else:
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "upload_resource_failed",
                    owner_id=owner_id,
                    error=error_msg,
                )
                return UploadResourceResponse(
                    success=False,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(
                "upload_resource_error",
                owner_id=owner_id,
                file_path=str(file_path),
                error=str(e),
            )
            return UploadResourceResponse(
                success=False,
                error=str(e),
            )

    def _get_content_type(self, file_path: Path) -> str:
        """根据文件扩展名获取Content-Type.

        Args:
            file_path: 文件路径

        Returns:
            Content-Type字符串
        """
        extension = file_path.suffix.lower()

        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
        }

        return content_types.get(extension, "application/octet-stream")
