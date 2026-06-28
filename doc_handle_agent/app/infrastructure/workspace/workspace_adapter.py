"""Workspace服务适配器.

封装与workspace_service的交互，提供模板获取、文档保存和资源上传功能。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.domain.model.block import TemplateBlock
from app.infrastructure.http import HttpUtils
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SaveDocumentRequest:
    """保存文档请求 - 对齐 workspace DocumentSaveRequest."""

    repo_id: str
    doc_type: str
    target_key: str
    title: str
    blocks: List[Dict[str, Any]]
    description: str = ""
    target_path: Optional[str] = None
    template_id: Optional[str] = None
    source_type: str = "agent"
    status: str = "draft"
    created_by: str = "agent"

    def to_api_payload(self) -> Dict[str, Any]:
        """转换为API请求体."""
        payload: Dict[str, Any] = {
            "repoId": self.repo_id,
            "docType": self.doc_type,
            "targetKey": self.target_key,
            "title": self.title,
            "description": self.description,
            "sourceType": self.source_type,
            "status": self.status,
            "createdBy": self.created_by,
            "blocks": self.blocks,
        }
        if self.target_path is not None:
            payload["targetPath"] = self.target_path
        if self.template_id is not None:
            payload["templateId"] = self.template_id
        return payload


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


@dataclass
class SaveResourceRequest:
    """保存资源请求 - 对齐 workspace DocumentResourceSaveRequest."""

    owner_type: str
    owner_id: str
    resource_type: str
    file_name: str
    mime_type: str
    storage_path: str
    block_id: Optional[str] = None

    def to_api_payload(self) -> Dict[str, Any]:
        """转换为API请求体."""
        payload: Dict[str, Any] = {
            "ownerType": self.owner_type,
            "ownerId": self.owner_id,
            "resourceType": self.resource_type,
            "fileName": self.file_name,
            "mimeType": self.mime_type,
            "storagePath": self.storage_path,
        }
        if self.block_id is not None:
            payload["blockId"] = self.block_id
        return payload


@dataclass
class SaveResourceResponse:
    """保存资源响应."""

    success: bool
    resource_id: Optional[str] = None
    url: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class WorkspaceServiceAdapter:
    """Workspace服务适配器.

    封装与workspace_service的所有交互。
    """

    def __init__(self, base_url: Optional[str] = None, auth_token: Optional[str] = None):
        """初始化适配器.

        Args:
            base_url: workspace服务基础URL，默认从配置读取
            auth_token: 回调workspace服务使用的当前用户登录态
        """
        settings = get_settings()
        self.base_url = base_url or settings.workspace_service_url
        self.auth_token = auth_token.strip() if auth_token and auth_token.strip() else None
        self.document_save_timeout = settings.workspace_document_save_timeout
        self.document_save_retries = max(settings.workspace_document_save_retries, 0)
        self.http = HttpUtils()

        logger.info(
            "workspace_adapter_initialized",
            base_url=self.base_url,
            has_auth=bool(self.auth_token),
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

    def _auth_headers(self) -> Optional[Dict[str, str]]:
        """构建workspace回调鉴权头."""
        if not self.auth_token:
            return None
        return {"Authorization": self.auth_token}

    async def get_block(self, document_id: str, block_id: str) -> Dict[str, Any]:
        """获取单个文档条目.

        Args:
            document_id: 文档ID
            block_id: 条目ID

        Returns:
            条目信息字典

        Raises:
            ValueError: 请求失败或条目不存在
        """
        url = self._build_url(f"/api/documents/{document_id}/blocks/{block_id}")

        logger.info(
            "get_block_request",
            document_id=document_id,
            block_id=block_id,
            url=url,
        )

        try:
            response = await self.http.get(url, headers=self._auth_headers())

            if not response.get("success"):
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "get_block_failed",
                    document_id=document_id,
                    block_id=block_id,
                    error=error_msg,
                )
                raise ValueError(f"Failed to get block: {error_msg}")

            data = response.get("data", {})
            logger.info(
                "get_block_success",
                document_id=document_id,
                block_id=block_id,
            )
            return data

        except Exception as e:
            logger.error(
                "get_block_error",
                document_id=document_id,
                block_id=block_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise

    async def get_document_blocks(self, document_id: str) -> List[Dict[str, Any]]:
        """列取文档所有条目.

        Args:
            document_id: 文档ID

        Returns:
            条目信息字典列表

        Raises:
            ValueError: 请求失败
        """
        url = self._build_url(f"/api/documents/{document_id}/blocks")

        logger.info(
            "get_document_blocks_request",
            document_id=document_id,
            url=url,
        )

        try:
            response = await self.http.get(url, headers=self._auth_headers())

            if not response.get("success"):
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "get_document_blocks_failed",
                    document_id=document_id,
                    error=error_msg,
                )
                raise ValueError(f"Failed to get document blocks: {error_msg}")

            data = response.get("data", [])
            logger.info(
                "get_document_blocks_success",
                document_id=document_id,
                block_count=len(data),
            )
            return data

        except Exception as e:
            logger.error(
                "get_document_blocks_error",
                document_id=document_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise

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
            response = await self.http.get(url, headers=self._auth_headers())

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
                attrs = item.get("attrs", {})
                block = TemplateBlock(
                    id=item.get("id", ""),
                    parent_block_id=item.get("parentBlockId"),
                    block_type=item.get("blockType", "paragraph"),
                    heading_level=item.get("headingLevel", 0),
                    order_no=item.get("orderNo", "") or "",
                    content_text=item.get("contentText", ""),
                    attrs=attrs,
                    source_refs=item.get("sourceRefs", []),
                    block_style=item.get("blockStyle", {}),
                    inline_styles=item.get("inlineStyles", []),
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
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
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
            doc_type=request.doc_type,
            target_key=request.target_key,
            title=request.title,
            block_count=len(request.blocks),
        )

        try:
            timeout = self.document_save_timeout if request.blocks else HttpUtils.DEFAULT_TIMEOUT
            max_retries = self.document_save_retries if request.blocks else HttpUtils.MAX_RETRIES
            logger.info(
                "save_document_http_policy",
                repo_id=request.repo_id,
                block_count=len(request.blocks),
                timeout=timeout,
                max_retries=max_retries,
            )

            response = await self.http.post(
                url,
                json_data=request.to_api_payload(),
                headers=self._auth_headers(),
                timeout=timeout,
                max_retries=max_retries,
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
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return SaveDocumentResponse(
                success=False,
                error=str(e),
            )

    async def save_resource(
        self,
        request: SaveResourceRequest,
    ) -> SaveResourceResponse:
        """创建资源记录.

        调用 workspace /api/resources 接口创建资源元数据记录。
        当 storage_path 为 http URL 且不传 provider/objectKey 时，
        workspace 会自动识别为 external_url 类型。

        Args:
            request: 保存资源请求

        Returns:
            保存资源响应
        """
        url = self._build_url("/api/resources")

        logger.info(
            "save_resource_request",
            owner_type=request.owner_type,
            owner_id=request.owner_id,
            resource_type=request.resource_type,
            storage_path=request.storage_path,
        )

        try:
            response = await self.http.post(
                url,
                json_data=request.to_api_payload(),
                headers=self._auth_headers(),
            )

            if response.get("success"):
                data = response.get("data", {})
                logger.info(
                    "save_resource_success",
                    resource_id=data.get("id"),
                    access_url=data.get("accessUrl"),
                )
                return SaveResourceResponse(
                    success=True,
                    resource_id=data.get("id"),
                    url=data.get("accessUrl") or data.get("url"),
                    message=response.get("message"),
                )
            else:
                error_msg = response.get("message", "Unknown error")
                logger.error(
                    "save_resource_failed",
                    owner_id=request.owner_id,
                    error=error_msg,
                )
                return SaveResourceResponse(
                    success=False,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(
                "save_resource_error",
                owner_id=request.owner_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return SaveResourceResponse(
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

        读取本地文件后委托给 upload_resource_bytes 执行实际上传。

        Args:
            owner_type: 归属类型 (document/template)
            owner_id: 归属对象ID
            resource_type: 资源类型 (image/flowchart/callgraph)
            file_path: 文件路径
            block_id: 所属条目ID（可选）

        Returns:
            上传资源响应
        """
        logger.info(
            "upload_resource_request",
            owner_type=owner_type,
            owner_id=owner_id,
            resource_type=resource_type,
            file_path=str(file_path),
            block_id=block_id,
        )

        try:
            max_size = 50 * 1024 * 1024  # 50MB
            file_size = file_path.stat().st_size
            if file_size > max_size:
                logger.error(
                    "upload_resource_file_too_large",
                    file_path=str(file_path),
                    size=file_size,
                    max_size=max_size,
                )
                return UploadResourceResponse(
                    success=False,
                    error=f"文件大小 {file_size} 超过限制 {max_size}",
                )

            file_content = file_path.read_bytes()
            return await self.upload_resource_bytes(
                owner_type=owner_type,
                owner_id=owner_id,
                resource_type=resource_type,
                file_name=file_path.name,
                file_content=file_content,
                block_id=block_id,
            )
        except Exception as e:
            logger.error(
                "upload_resource_error",
                owner_id=owner_id,
                file_path=str(file_path),
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return UploadResourceResponse(
                success=False,
                error=str(e),
            )

    async def upload_resource_bytes(
        self,
        owner_type: str,
        owner_id: str,
        resource_type: str,
        file_name: str,
        file_content: bytes,
        block_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> UploadResourceResponse:
        """上传资源文件（字节内容）.

        Args:
            owner_type: 归属类型 (document/template)
            owner_id: 归属对象ID
            resource_type: 资源类型 (image/flowchart/callgraph/drawio)
            file_name: 文件名
            file_content: 文件字节内容
            block_id: 所属条目ID（可选）
            client: 可选的共享 HTTP 客户端

        Returns:
            上传资源响应
        """
        url = self._build_url("/api/resources/upload")

        logger.info(
            "upload_resource_bytes_request",
            owner_type=owner_type,
            owner_id=owner_id,
            resource_type=resource_type,
            file_name=file_name,
            block_id=block_id,
        )

        try:
            content_type = self._get_content_type_by_name(file_name)

            files = {
                "file": (
                    file_name,
                    file_content,
                    content_type,
                )
            }

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
                headers=self._auth_headers(),
                client=client,
            )

            if response.get("success"):
                data = response.get("data", {})
                logger.info(
                    "upload_resource_bytes_success",
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
                    "upload_resource_bytes_failed",
                    owner_id=owner_id,
                    error=error_msg,
                )
                return UploadResourceResponse(
                    success=False,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(
                "upload_resource_bytes_error",
                owner_id=owner_id,
                file_name=file_name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
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
        return self._get_content_type_by_name(file_path.name)

    def _get_content_type_by_name(self, file_name: str) -> str:
        """根据文件名获取Content-Type.

        Args:
            file_name: 文件名

        Returns:
            Content-Type字符串
        """
        extension = Path(file_name).suffix.lower()

        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".drawio": "application/vnd.jgraph.mxfile",
        }

        return content_types.get(extension, "application/octet-stream")
