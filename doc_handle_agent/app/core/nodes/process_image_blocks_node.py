"""处理图片块节点.

在内容生成完成后，遍历文档块中的图片类型块，
下载图片文件并调用 workspace 上传资源文件接口，
将图片块转换为 workspace 期望的标准格式。
同时检查并上传同名的 drawio 资源文件。
"""

import json
import re
import asyncio
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.drawio_architecture import DiagramArtifacts, render_drawio_architecture
from app.infrastructure.workspace import (
    UploadResourceResponse,
    WorkspaceServiceAdapter,
)
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)

# 最大允许下载/上传的文件大小（50MB）
MAX_FILE_SIZE = 50 * 1024 * 1024

# HTTP 下载重试配置
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_DELAY = 1.0
MISSING_BLOCK_PLACEHOLDER_PATTERN = re.compile(
    r"^\[内容块\s+'[^']+'\s+生成缺失\]$"
)
CONFIRMED_MISSING_IMAGE_ATTR = "_confirmedMissingImage"


class ProcessImageBlocksNode(WorkflowNode):
    """处理图片块节点.

    负责：
    1. 识别文档块中的图片类型块
    2. 提取图片 URL 和 caption
    3. 下载图片文件并调用 workspace API 上传资源文件
    4. 检查并上传同名的 drawio 资源文件
    5. 更新图片块为标准格式（blockType="image", attrs.assetId 等）
    """

    def __init__(
        self,
        workspace_adapter: Optional[WorkspaceServiceAdapter] = None,
        mcp_client: Optional[MCPClient] = None,
    ):
        """初始化节点.

        Args:
            workspace_adapter: workspace 服务适配器，默认创建新实例
            mcp_client: 已连接的 MCP 客户端，用于缺失图片 ID 时按 sourceRefs 兜底补图
        """
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()
        self.mcp_client = mcp_client
        settings = get_settings()
        self.kb_base_url = self._resolve_kb_base_url(settings.mcp_server_url)
        self.download_parallelism = max(1, settings.image_download_parallelism)
        self.upload_parallelism = max(1, settings.image_upload_parallelism)
        self.process_drawio = settings.image_process_drawio

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

        repo_id = state.get("repo_id", "")
        reporter = state.get("__progress_reporter")
        try:
            state["status"] = GenerationStatus.GENERATING.value
            if reporter:
                await reporter.report_percent(0, "正在处理图片资源...")
            else:
                state["message"] = "正在处理图片资源..."

            async with httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=max(self.download_parallelism * 2, 16),
                    max_keepalive_connections=max(self.download_parallelism, 8),
                ),
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
            ) as download_client, httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=max(self.upload_parallelism * 2, 16),
                    max_keepalive_connections=max(self.upload_parallelism, 8),
                ),
                timeout=30.0,
                follow_redirects=True,
                http1=True,
                http2=False,
                trust_env=False,
            ) as upload_client:
                with log_timing("process_image_blocks", block_count=len(doc_blocks)):
                    updated_blocks = await self._process_blocks(
                        doc_blocks,
                        document_id=document_id,
                        repo_id=repo_id,
                        reporter=reporter,
                        download_client=download_client,
                        upload_client=upload_client,
                    )

            state["doc_blocks"] = updated_blocks
            if reporter:
                await reporter.report_percent(100, "图片资源处理完成")

            logger.info(
                "process_image_blocks_complete",
                total_blocks=len(doc_blocks),
                repo_id=repo_id,
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
        repo_id: str,
        reporter: Any = None,
        download_client: Optional[httpx.AsyncClient] = None,
        upload_client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """处理文档块列表中的图片块.

        Args:
            doc_blocks: 文档块列表
            document_id: 文档 ID
            repo_id: 仓库 ID
            reporter: 进度报告器（可选）
            download_client: 本轮图片下载共享 HTTP 客户端
            upload_client: 本轮资源上传共享 HTTP 客户端

        Returns:
            更新后的文档块列表
        """
        doc_blocks = await self._fill_missing_image_refs_from_source_refs(doc_blocks, repo_id)
        updated_blocks: List[Optional[Dict[str, Any]]] = [None] * len(doc_blocks)
        image_entries = [
            (index, block)
            for index, block in enumerate(doc_blocks)
            if block.get("blockType") == "image"
        ]
        processed_count = 0
        skipped_missing_count = 0
        processed_lock = asyncio.Lock()
        download_semaphore = asyncio.Semaphore(self.download_parallelism)
        upload_semaphore = asyncio.Semaphore(self.upload_parallelism)

        for index, block in enumerate(doc_blocks):
            if block.get("blockType") != "image":
                updated_blocks[index] = block

        async def process_entry(index: int, block: Dict[str, Any]) -> None:
            nonlocal processed_count, skipped_missing_count
            try:
                processed = await self._process_image_block(
                    block,
                    document_id,
                    repo_id,
                    download_client=download_client,
                    upload_client=upload_client,
                    download_semaphore=download_semaphore,
                    upload_semaphore=upload_semaphore,
                )
            except Exception as exc:
                logger.error(
                    "process_image_block_failed",
                    block_id=block.get("id"),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
                processed = block
            updated_blocks[index] = processed
            async with processed_lock:
                processed_count += 1
                if processed is None:
                    skipped_missing_count += 1
                if reporter:
                    await reporter.report_step(
                        processed_count,
                        len(image_entries),
                        f"正在处理第 {processed_count}/{len(image_entries)} 个图片资源...",
                    )

        logger.info(
            "process_image_blocks_batch",
            total_blocks=len(doc_blocks),
            image_count=len(image_entries),
            download_parallelism=self.download_parallelism,
            upload_parallelism=self.upload_parallelism,
            process_drawio=self.process_drawio,
        )

        if image_entries:
            await asyncio.gather(
                *(process_entry(index, block) for index, block in image_entries)
            )

        if skipped_missing_count:
            logger.info(
                "missing_image_blocks_skipped",
                skipped_count=skipped_missing_count,
                image_count=len(image_entries),
            )

        return [block for block in updated_blocks if block is not None]

    async def _fill_missing_image_refs_from_source_refs(
        self,
        doc_blocks: List[Dict[str, Any]],
        repo_id: str,
    ) -> List[Dict[str, Any]]:
        """按源码引用为缺少 contentText 的图片块批量补充图片 ID."""
        if not self.mcp_client:
            return doc_blocks

        pending_blocks = [
            block for block in doc_blocks
            if block.get("blockType") == "image"
            and not self._extract_image_reference(block)
            and self._extract_source_node_id(block)
        ]
        if not pending_blocks:
            return doc_blocks

        node_ids: List[str] = []
        seen_node_ids: Set[str] = set()
        for block in pending_blocks:
            node_id = self._extract_source_node_id(block)
            if node_id and node_id not in seen_node_ids:
                node_ids.append(node_id)
                seen_node_ids.add(node_id)

        image_refs, missing_node_ids = await self._load_image_ref_status_by_node_id(repo_id, node_ids)
        filled_count = 0
        confirmed_missing_count = 0
        for block in pending_blocks:
            node_id = self._extract_source_node_id(block)
            image_ref = image_refs.get(node_id or "")
            if image_ref:
                block["contentText"] = image_ref
                filled_count += 1
            elif node_id in missing_node_ids:
                attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
                block["attrs"] = {**attrs, CONFIRMED_MISSING_IMAGE_ATTR: True}
                confirmed_missing_count += 1

        logger.info(
            "image_refs_filled_from_source_refs",
            pending_count=len(pending_blocks),
            node_count=len(node_ids),
            filled_count=filled_count,
            confirmed_missing_count=confirmed_missing_count,
        )
        return doc_blocks

    async def _load_image_ref_status_by_node_id(
        self,
        repo_id: str,
        node_ids: List[str],
    ) -> tuple[Dict[str, str], Set[str]]:
        """调用 batch_get_image_ids 获取图片 ID 与明确缺图状态."""
        if not node_ids:
            return {}, set()
        try:
            raw_result = await self.mcp_client.call_tool(
                "batch_get_image_ids",
                {"repo_id": repo_id, "node_ids": node_ids},
            )
        except Exception as exc:
            logger.warning(
                "image_refs_load_failed",
                repo_id=repo_id,
                node_count=len(node_ids),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return {}, set()

        if isinstance(raw_result, dict):
            payload = raw_result
        else:
            try:
                payload = json.loads(raw_result)
            except json.JSONDecodeError:
                try:
                    payload = ast.literal_eval(raw_result)
                except (ValueError, SyntaxError):
                    logger.warning(
                        "image_refs_parse_failed",
                        repo_id=repo_id,
                        raw_result=str(raw_result)[:200],
                    )
                    return {}, set()
            except TypeError:
                logger.warning(
                    "image_refs_parse_failed",
                    repo_id=repo_id,
                    raw_result=str(raw_result)[:200],
                )
                return {}, set()
        if not isinstance(payload, dict):
            logger.warning(
                "image_refs_parse_failed",
                repo_id=repo_id,
                raw_result=str(raw_result)[:200],
            )
            return {}, set()

        refs: Dict[str, str] = {}
        missing_node_ids: Set[str] = set()
        for item in payload.get("images", []):
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            if not node_id:
                continue
            if not item.get("success"):
                error = str(item.get("error") or "").strip()
                if error in {"No image available", "Node not found"}:
                    missing_node_ids.add(node_id)
                continue
            image_id = self._extract_reference_from_value(item)
            if image_id:
                refs[node_id] = image_id
        return refs, missing_node_ids

    async def _process_image_block(
        self,
        block: Dict[str, Any],
        document_id: str,
        repo_id: str,
        download_client: Optional[httpx.AsyncClient] = None,
        upload_client: Optional[httpx.AsyncClient] = None,
        download_semaphore: Optional[asyncio.Semaphore] = None,
        upload_semaphore: Optional[asyncio.Semaphore] = None,
    ) -> Optional[Dict[str, Any]]:
        """处理单个图片块.

        下载图片文件并上传，同时检查并上传同名的 drawio 文件，更新块格式。

        Args:
            block: 原始图片块数据
            document_id: 文档 ID
            repo_id: 仓库 ID
            download_client: 本轮图片下载共享 HTTP 客户端
            upload_client: 本轮资源上传共享 HTTP 客户端
            download_semaphore: 图片下载并发限制
            upload_semaphore: 资源上传并发限制

        Returns:
            更新后的图片块数据，缺少可用图片资源时返回 None 并跳过该块
        """
        if self._is_drawio_architecture_block(block):
            return await self._process_drawio_architecture_block(
                block,
                document_id,
                upload_client=upload_client,
                upload_semaphore=upload_semaphore,
            )

        image_ref = self._extract_image_reference(block)
        if not image_ref:
            content = block.get("contentText")
            attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
            logger.debug(
                "image_reference_not_found",
                block_id=block.get("id"),
                block_content=str(content or "")[:100],
                source_node_id=self._extract_source_node_id(block),
                confirmed_missing=bool(attrs.get(CONFIRMED_MISSING_IMAGE_ATTR)),
            )
            return None if attrs.get(CONFIRMED_MISSING_IMAGE_ATTR) else block

        caption = self._extract_caption(block) or ""
        block_id = block.get("id")
        if not block_id:
            logger.warning(
                "block_id_missing",
                block_type=block.get("blockType"),
                block_content=block.get("contentText", "")[:50],
            )

        # 构造下载 URL：支持外部 URL 和知识底座 image_id
        if image_ref.startswith(("http://", "https://")):
            image_url = image_ref
        else:
            image_url = f"{self.kb_base_url}/images/{repo_id}/{image_ref}"

        image_bytes = await self._download_with_limit(
            image_url,
            client=download_client,
            semaphore=download_semaphore,
        )
        if not image_bytes:
            logger.error(
                "download_image_failed",
                image_url=self._sanitize_url(image_url),
            )
            # 引用存在但资源不可下载时跳过图片块，避免文档里留下空的“图示资源缺失”占位
            return None

        file_name = self._extract_file_name(image_url) or "image.png"
        resource_type = self._resolve_resource_type(image_url)

        image_response = await self._upload_with_limit(
            file_name=file_name,
            file_content=image_bytes,
            document_id=document_id,
            resource_type=resource_type,
            block_id=block_id,
            client=upload_client,
            semaphore=upload_semaphore,
        )

        if not image_response.success or not image_response.resource_id:
            logger.error(
                "upload_image_resource_failed",
                image_url=self._sanitize_url(image_url),
                error=image_response.error,
            )
            # 上传失败的图片没有可绑定资源，继续保留只会在前端显示空图片块
            return None

        asset_id = image_response.resource_id
        logger.info(
            "image_resource_uploaded",
            asset_id=asset_id,
            image_url=self._sanitize_url(image_url),
            caption=caption,
        )

        # 检查并上传同名的 drawio 文件
        drawio_asset_id = None
        if image_ref.startswith(("http://", "https://")):
            drawio_url = self._to_drawio_url(image_ref)
        else:
            drawio_id = self._to_drawio_id(image_ref)
            drawio_url = f"{self.kb_base_url}/images/{repo_id}/{drawio_id}" if drawio_id else None

        if self.process_drawio and drawio_url:
            drawio_bytes = await self._download_with_limit(
                drawio_url,
                max_retries=1,
                client=download_client,
                semaphore=download_semaphore,
            )
            if drawio_bytes:
                drawio_file_name = self._extract_file_name(drawio_url) or "diagram.drawio"
                drawio_response = await self._upload_with_limit(
                    file_name=drawio_file_name,
                    file_content=drawio_bytes,
                    document_id=document_id,
                    resource_type="drawio",
                    block_id=block_id,
                    client=upload_client,
                    semaphore=upload_semaphore,
                )
                if drawio_response.success and drawio_response.resource_id:
                    drawio_asset_id = drawio_response.resource_id
                    logger.info(
                        "drawio_resource_uploaded",
                        drawio_asset_id=drawio_asset_id,
                        drawio_url=self._sanitize_url(drawio_url),
                    )

        attrs = {
            **block.get("attrs", {}),
            "assetId": asset_id,
            "caption": caption,
            "alt": caption,
        }
        if drawio_asset_id:
            attrs["drawioAssetId"] = drawio_asset_id

        return {
            **block,
            "blockType": "image",
            "contentText": caption,
            "attrs": attrs,
        }

    async def _process_drawio_architecture_block(
        self,
        block: Dict[str, Any],
        document_id: str,
        upload_client: Optional[httpx.AsyncClient] = None,
        upload_semaphore: Optional[asyncio.Semaphore] = None,
    ) -> Dict[str, Any]:
        """将结构化架构图内容渲染并上传为 draw.io 资源."""
        block_id = str(block.get("id") or "")
        attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
        artifacts = render_drawio_architecture(
            block.get("contentText"),
            fallback_title=self._resolve_drawio_architecture_title(block, attrs),
        )
        drawio_response = await self._upload_drawio_architecture_resource(
            artifacts=artifacts,
            block_id=block_id,
            document_id=document_id,
            upload_client=upload_client,
            upload_semaphore=upload_semaphore,
        )
        if not drawio_response.success or not drawio_response.resource_id:
            logger.error(
                "upload_drawio_architecture_source_failed",
                block_id=block_id,
                error=drawio_response.error,
            )
            return block

        next_attrs = self._build_drawio_architecture_attrs(attrs, artifacts, drawio_response.resource_id)
        logger.info(
            "drawio_architecture_resource_uploaded",
            block_id=block_id,
            drawio_asset_id=drawio_response.resource_id,
        )
        return {
            **block,
            "blockType": "image",
            "contentText": artifacts.caption,
            "attrs": next_attrs,
        }

    async def _upload_drawio_architecture_resource(
        self,
        artifacts: DiagramArtifacts,
        block_id: str,
        document_id: str,
        upload_client: Optional[httpx.AsyncClient] = None,
        upload_semaphore: Optional[asyncio.Semaphore] = None,
    ) -> UploadResourceResponse:
        """上传 draw.io 架构图源文件."""
        file_stem = self._sanitize_file_stem(block_id or artifacts.title or "architecture")
        return await self._upload_with_limit(
            file_name=f"{file_stem}.drawio",
            file_content=artifacts.drawio_xml.encode("utf-8"),
            document_id=document_id,
            resource_type="drawio",
            block_id=block_id or None,
            client=upload_client,
            semaphore=upload_semaphore,
        )

    @staticmethod
    def _resolve_drawio_architecture_title(block: Dict[str, Any], attrs: Dict[str, Any]) -> str:
        """解析 draw.io 架构图标题兜底值."""
        return (
            str(attrs.get("title") or attrs.get("caption") or block.get("title") or "").strip()
            or "项目架构图"
        )

    @staticmethod
    def _build_drawio_architecture_attrs(
        attrs: Dict[str, Any],
        artifacts: DiagramArtifacts,
        drawio_asset_id: str,
    ) -> Dict[str, Any]:
        """构造 draw.io 架构图块属性."""
        return {
            **attrs,
            "drawioAssetId": drawio_asset_id,
            "editableAssetId": drawio_asset_id,
            "caption": artifacts.caption,
            "alt": artifacts.caption,
            "architectureSpec": artifacts.spec,
            "diagramKind": "drawio_architecture",
            # 预览由前端 draw.io viewer 从同一份源文件生成，避免后端 SVG 与编辑器渲染不一致
            "renderKind": "drawio",
        }

    async def _download_with_limit(
        self,
        url: str,
        max_retries: int = DOWNLOAD_MAX_RETRIES,
        client: Optional[httpx.AsyncClient] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> Optional[bytes]:
        """按下载并发限制读取图片资源."""
        if semaphore:
            async with semaphore:
                return await self._download_file(
                    url,
                    max_retries=max_retries,
                    client=client,
                )
        return await self._download_file(
            url,
            max_retries=max_retries,
            client=client,
        )

    async def _upload_with_limit(
        self,
        file_name: str,
        file_content: bytes,
        document_id: str,
        resource_type: str,
        block_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
    ) -> UploadResourceResponse:
        """按上传并发限制写入 workspace 资源."""
        if semaphore:
            async with semaphore:
                return await self._upload_resource(
                    file_name=file_name,
                    file_content=file_content,
                    document_id=document_id,
                    resource_type=resource_type,
                    block_id=block_id,
                    client=client,
                )
        return await self._upload_resource(
            file_name=file_name,
            file_content=file_content,
            document_id=document_id,
            resource_type=resource_type,
            block_id=block_id,
            client=client,
        )

    async def _upload_resource(
        self,
        file_name: str,
        file_content: bytes,
        document_id: str,
        resource_type: str,
        block_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> UploadResourceResponse:
        """调用 workspace API 上传资源文件.

        Args:
            file_name: 文件名
            file_content: 文件字节内容
            document_id: 文档 ID（用作 owner_id）
            resource_type: 资源类型 (image/drawio/flowchart/callgraph)
            block_id: 所属条目ID（可选）
            client: 本轮资源上传共享 HTTP 客户端

        Returns:
            资源上传响应
        """
        return await self.workspace_adapter.upload_resource_bytes(
            owner_type="document",
            owner_id=document_id,
            resource_type=resource_type,
            file_name=file_name,
            file_content=file_content,
            block_id=block_id,
            client=client,
        )

    async def _download_file(
        self,
        url: str,
        max_retries: int = DOWNLOAD_MAX_RETRIES,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[bytes]:
        """下载文件内容.

        支持 HTTP URL（带重试）和本地文件路径。
        对文件大小做上限检查，避免大文件导致内存溢出。

        Args:
            url: 文件 URL 或本地路径
            max_retries: HTTP 最大尝试次数
            client: 本轮图片下载共享 HTTP 客户端

        Returns:
            文件字节内容，下载失败或超限时返回 None
        """
        try:
            if url.startswith(("http://", "https://")):
                return await self._download_http(
                    url,
                    max_retries=max_retries,
                    client=client,
                )
            else:
                path = Path(url)
                if path.exists():
                    size = path.stat().st_size
                    if size > MAX_FILE_SIZE:
                        logger.warning(
                            "local_file_too_large",
                            path=str(path),
                            size=size,
                            max_size=MAX_FILE_SIZE,
                        )
                        return None
                    return path.read_bytes()
                logger.warning("local_file_not_found", path=str(path))
        except (httpx.HTTPError, OSError) as e:
            logger.warning(
                "download_file_error",
                url=self._sanitize_url(url),
                error_type=type(e).__name__,
                error=str(e),
            )
        return None

    async def _download_http(
        self,
        url: str,
        max_retries: int = DOWNLOAD_MAX_RETRIES,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[bytes]:
        """下载 HTTP 文件（带重试和内容校验）.

        复用单个 AsyncClient，优先通过 Content-Length 头预检查文件大小，
        避免大文件下载到内存后才拒绝。

        Args:
            url: HTTP URL
            max_retries: 最大尝试次数
            client: 本轮图片下载共享 HTTP 客户端

        Returns:
            文件字节内容，下载失败返回 None
        """
        request_client = client
        owns_client = request_client is None
        if request_client is None:
            request_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
            )
        try:
            assert request_client is not None
            for attempt in range(max(1, max_retries)):
                try:
                    async with request_client.stream("GET", url) as response:
                        if response.status_code == 200:
                            return await self._read_download_response(url, response)
                        if 400 <= response.status_code < 500:
                            logger.warning(
                                "http_download_client_error",
                                url=self._sanitize_url(url),
                                status_code=response.status_code,
                            )
                            return None
                        logger.warning(
                            "http_download_failed",
                            url=self._sanitize_url(url),
                            status_code=response.status_code,
                            attempt=attempt + 1,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(DOWNLOAD_RETRY_DELAY * (2 ** attempt))
                except httpx.HTTPError as e:
                    logger.warning(
                        "http_download_error",
                        url=self._sanitize_url(url),
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(DOWNLOAD_RETRY_DELAY * (2 ** attempt))
            return None
        finally:
            if owns_client:
                await request_client.aclose()

    async def _read_download_response(self, url: str, response: httpx.Response) -> Optional[bytes]:
        """读取下载响应并校验大小与类型."""
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > MAX_FILE_SIZE:
                logger.warning(
                    "http_file_too_large",
                    url=self._sanitize_url(url),
                    size=size,
                    max_size=MAX_FILE_SIZE,
                )
                return None
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            logger.warning(
                "http_unexpected_content_type",
                url=self._sanitize_url(url),
                content_type=content_type,
            )
            return None
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > MAX_FILE_SIZE:
                logger.warning(
                    "http_file_too_large",
                    url=self._sanitize_url(url),
                    size=len(chunks),
                    max_size=MAX_FILE_SIZE,
                )
                return None
        return bytes(chunks)

    @staticmethod
    def _to_drawio_url(image_url: str) -> Optional[str]:
        """从图片 URL 推导出 drawio 文件 URL.

        去除查询参数和 fragment 后，将已知图片后缀替换为 .drawio。

        Args:
            image_url: 图片 URL

        Returns:
            drawio URL 或 None
        """
        parsed = urlparse(image_url)
        path_lower = parsed.path.lower()
        for ext in (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if path_lower.endswith(ext):
                new_path = parsed.path[: -len(ext)] + ".drawio"
                return parsed._replace(path=new_path).geturl()
        return None

    @staticmethod
    def _to_drawio_id(image_id: str) -> Optional[str]:
        """从图片 ID 推导出 drawio 文件 ID.

        将已知图片后缀替换为 .drawio。

        Args:
            image_id: 图片 ID（如 xxx.svg）

        Returns:
            drawio ID 或 None
        """
        path_lower = image_id.lower()
        for ext in (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if path_lower.endswith(ext):
                return image_id[: -len(ext)] + ".drawio"
        return None

    @staticmethod
    def _resolve_resource_type(url: str) -> str:
        """根据 URL 中的文件名后缀解析资源类型.

        Args:
            url: 文件 URL

        Returns:
            资源类型字符串
        """
        parsed = urlparse(url)
        file_name = parsed.path.split("/")[-1].lower()
        if file_name.endswith(".flowchart.svg") or file_name.endswith(".flowchart.png"):
            return "flowchart"
        if file_name.endswith(".callgraph.svg") or file_name.endswith(".callgraph.png"):
            return "callgraph"
        return "image"

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """脱敏 URL，去除查询参数中的敏感信息.

        Args:
            url: 原始 URL

        Returns:
            仅保留 scheme + netloc + path 的 URL 字符串
        """
        if not isinstance(url, str):
            return str(url) if url is not None else ""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    @staticmethod
    def _is_drawio_architecture_block(block: Dict[str, Any]) -> bool:
        """判断是否为需要本地生成的 draw.io 架构图块."""
        attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
        value = attrs.get("format") or attrs.get("outputFormat") or attrs.get("diagramKind")
        return str(value or "").strip().lower() == "drawio_architecture"

    @staticmethod
    def _sanitize_file_stem(value: str) -> str:
        """生成适合资源文件名的稳定前缀."""
        stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", value or "").strip("-")
        return stem[:80] or "architecture"

    @staticmethod
    def _extract_image_reference(block: Dict[str, Any]) -> Optional[str]:
        """从块数据中提取图片引用（URL 或 image_id）.

        图片引用直接存储在 contentText 中，可能是完整 URL 或知识底座图片 ID。

        Args:
            block: 块数据

        Returns:
            图片引用（URL 或 image_id）或 None
        """
        content = block.get("contentText", "")
        content_ref = ProcessImageBlocksNode._extract_reference_from_value(content)
        if content_ref:
            return content_ref

        attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
        for key in ("image_id", "imageId", "src", "url"):
            attr_ref = ProcessImageBlocksNode._extract_reference_from_value(
                attrs.get(key)
            )
            if attr_ref:
                return attr_ref

        return None

    @staticmethod
    def _extract_reference_from_value(value: Any) -> Optional[str]:
        """从字符串或结构化值中提取真实图片引用."""
        if value is None:
            return None

        if isinstance(value, dict):
            # 兼容 LLM 直接回传工具结果 JSON 的情况，优先提取真正可下载的字段，
            # 避免把“函数流程图”这类标题文本误当成图片资源。
            for key in ("image_id", "imageId", "image_url", "imageUrl", "url", "src"):
                ref = ProcessImageBlocksNode._extract_reference_from_value(value.get(key))
                if ref:
                    return ref
            images = value.get("images")
            if isinstance(images, list):
                for item in images:
                    ref = ProcessImageBlocksNode._extract_reference_from_value(item)
                    if ref:
                        return ref
            return None

        if isinstance(value, list):
            for item in value:
                ref = ProcessImageBlocksNode._extract_reference_from_value(item)
                if ref:
                    return ref
            return None

        if not isinstance(value, str):
            return None

        stripped = value.strip()
        if not stripped or MISSING_BLOCK_PLACEHOLDER_PATTERN.match(stripped):
            return None

        parsed_ref = ProcessImageBlocksNode._extract_reference_from_json_text(stripped)
        if parsed_ref:
            return parsed_ref

        markdown_match = re.search(r"!\[[^\]]*\]\(([^)\s]+)\)", stripped)
        if markdown_match:
            ref = markdown_match.group(1).strip()
            if ProcessImageBlocksNode._is_valid_image_reference(ref):
                return ref

        url_match = re.search(r"https?://[^\s)\"']+", stripped)
        if url_match:
            ref = url_match.group(0).rstrip(".,;，。；")
            if ProcessImageBlocksNode._is_valid_image_reference(ref):
                return ref

        return (
            stripped
            if ProcessImageBlocksNode._is_valid_image_reference(stripped)
            else None
        )

    @staticmethod
    def _extract_source_node_id(block: Dict[str, Any]) -> Optional[str]:
        """从 sourceRefs 中提取节点 ID."""
        source_refs = block.get("sourceRefs") or block.get("source_refs") or []
        if not isinstance(source_refs, list):
            return None
        for source_ref in source_refs:
            if not isinstance(source_ref, dict):
                continue
            for key in ("sourceId", "source_id", "nodeId", "node_id", "source_ref"):
                value = source_ref.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _extract_reference_from_json_text(text: str) -> Optional[str]:
        """解析 LLM 可能原样返回的工具 JSON，提取 image_id/image_url."""
        if not text.startswith(("{", "[")):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return ProcessImageBlocksNode._extract_reference_from_value(data)

    @staticmethod
    def _is_valid_image_reference(value: str) -> bool:
        """判断字符串是否像可下载图片 URL 或知识库图片 ID."""
        if not isinstance(value, str):
            return False
        stripped = value.strip()
        if not stripped or any(ch.isspace() for ch in stripped):
            return False
        parsed = urlparse(stripped)
        path = parsed.path if parsed.scheme in ("http", "https") else stripped
        lower = path.lower()
        return lower.endswith((".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"))

    @staticmethod
    def _extract_caption(block: Dict[str, Any]) -> str:
        """从块数据中提取图片标题/说明.

        排除纯 URL 和图片 ID（含常见图片后缀）的情况。

        Args:
            block: 块数据

        Returns:
            图片标题
        """
        content = block.get("contentText", "")
        if not content:
            return ""

        stripped = content.strip()
        if MISSING_BLOCK_PLACEHOLDER_PATTERN.match(stripped):
            return ""
        # 排除纯 URL
        if stripped.startswith(("http://", "https://")):
            return ""
        # 排除常见图片 ID 格式（如 xxx.svg, xxx.png）
        lower = stripped.lower()
        for ext in (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".drawio"):
            if lower.endswith(ext):
                return ""

        return stripped

    @staticmethod
    def _extract_file_name(url: str) -> Optional[str]:
        """从 URL 中提取文件名.

        Args:
            url: 图片 URL

        Returns:
            文件名或 None
        """
        try:
            path = urlparse(url).path
            if path:
                name = path.split("/")[-1]
                if name and "." in name:
                    return name
        except Exception:
            pass
        return None

    @staticmethod
    def _resolve_kb_base_url(mcp_server_url: str) -> str:
        """从 MCP 服务器 URL 推导知识底座服务基础 URL.

        去掉 /mcp、/sse 等常见后缀路径。

        Args:
            mcp_server_url: MCP 服务器 URL（如 http://localhost:8000/mcp）

        Returns:
            知识底座服务基础 URL（如 http://localhost:8000）
        """
        url = mcp_server_url.rstrip("/")
        for suffix in ("/mcp", "/sse"):
            if url.endswith(suffix):
                return url[: -len(suffix)]
        return url

