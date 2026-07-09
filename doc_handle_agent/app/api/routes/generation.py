"""文档生成API路由."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException

from app.api.models.schemas import (
    GenerateDocumentRequest,
    GenerateDocumentResponse,
    ActiveGenerationInfo,
    SystemStatusResponse,
    RewriteBlockRequest,
    RewriteBlockResponse,
    OptimizeDrawioDiagramRequest,
    OptimizeDrawioDiagramResponse,
)
from app.core.nodes.process_image_blocks_node import ProcessImageBlocksNode
from app.core.document_engine import get_document_engine
from app.domain.drawio_architecture import DiagramArtifacts
from app.domain.drawio_diagram_optimize_agent import DrawioDiagramOptimizeAgent
from app.domain.rewrite_agent import RewriteAgent
from app.infrastructure.workspace import WorkspaceServiceAdapter
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/generate", response_model=GenerateDocumentResponse)
async def generate_document(
    request: GenerateDocumentRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> GenerateDocumentResponse:
    """启动文档生成流程.

    Args:
        request: 生成请求

    Returns:
        生成响应

    Raises:
        HTTPException: 参数无效
    """
    logger.info(
        "api_generate_document",
        repo_id=request.repo_id,
        template_id=request.template_id,
        has_workspace_auth=bool(authorization),
    )

    try:
        engine = get_document_engine()

        flow_id = await engine.start_generation(
            repo_id=request.repo_id,
            template_id=request.template_id,
            workspace_auth_token=authorization,
        )

        # 获取初始状态
        state = engine.get_state(flow_id)

        return GenerateDocumentResponse(
            flow_id=flow_id,
            status=state["status"],
            repo_id=request.repo_id,
            template_id=request.template_id,
            document_id=state.get("document_id"),
            created_at=state.get("started_at") or "",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "generate_document_failed",
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start generation: {str(e)}",
        )


@router.get("/active", response_model=List[ActiveGenerationInfo])
async def list_active_generations() -> List[ActiveGenerationInfo]:
    """列出所有活动的生成任务.

    Returns:
        活动生成任务列表
    """
    engine = get_document_engine()
    active = engine.list_active_generations()

    return [
        ActiveGenerationInfo(
            flow_id=item["flow_id"],
            status=item.get("status"),
        )
        for item in active
    ]


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """获取系统状态.

    Returns:
        系统状态响应
    """
    engine = get_document_engine()
    active_count = len(engine.list_active_generations())

    return SystemStatusResponse(
        status="running" if active_count > 0 else "idle",
        active_generations=active_count,
    )


@router.post("/rewrite-block", response_model=RewriteBlockResponse)
async def rewrite_block(request: RewriteBlockRequest) -> RewriteBlockResponse:
    """改写文档条目.

    接收改写请求，调用 RewriteAgent 生成可直接应用的正文。
    不执行写入操作，具体应用方式由前端选择。

    Args:
        request: 改写请求

    Returns:
        改写响应

    Raises:
        HTTPException: 参数无效或改写失败
    """
    logger.info(
        "api_rewrite_block",
        repo_id=request.repo_id,
        block_id=request.block_id,
        action=request.action,
    )

    if not request.block_id:
        raise HTTPException(status_code=400, detail="block_id is required")

    try:
        agent = RewriteAgent()
        response = await agent.rewrite(request)
        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "rewrite_block_failed",
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Rewrite failed: {str(e)}",
        )


@router.post("/optimizeDrawioDiagram", response_model=OptimizeDrawioDiagramResponse)
async def optimize_drawio_diagram(
    request: OptimizeDrawioDiagramRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> OptimizeDrawioDiagramResponse:
    """优化 draw.io 图.

    接收前端当前块上下文，基于当前 draw.io XML 优化并上传 draw.io 源文件
    """
    logger.info(
        "api_optimize_drawio_diagram",
        repo_id=request.repo_id,
        document_id=request.document_id,
        block_id=request.block_id,
        has_current_xml=bool(request.current_xml),
        has_prompt=bool(request.prompt and request.prompt.strip()),
    )

    if not request.block_id:
        raise HTTPException(status_code=400, detail="block_id is required")
    if not request.document_id:
        raise HTTPException(status_code=400, detail="document_id is required")
    if not request.current_xml or not request.current_xml.strip():
        raise HTTPException(status_code=400, detail="current_xml is required")

    try:
        agent = DrawioDiagramOptimizeAgent()
        optimized_xml = await agent.optimize_xml(request)
        title = request.title or str(request.attrs.get("title") or request.attrs.get("caption") or "draw.io 图示")
        artifacts = DiagramArtifacts(
            title=title,
            caption=title,
            spec={},
            svg="",
            drawio_xml=optimized_xml,
        )

        # 上传 draw.io 源文件要沿用当前用户登录态，避免 workspace 回调鉴权失败
        process_node = ProcessImageBlocksNode(
            workspace_adapter=WorkspaceServiceAdapter(auth_token=authorization),
        )
        upload_response = await process_node._upload_drawio_architecture_resource(
            artifacts=artifacts,
            block_id=request.block_id,
            document_id=request.document_id,
        )
        if not upload_response.success or not upload_response.resource_id:
            raise RuntimeError(upload_response.error or "draw.io 资源上传失败")

        attrs = _build_optimized_drawio_attrs(
            request.attrs,
            artifacts=artifacts,
            drawio_asset_id=upload_response.resource_id,
        )
        return OptimizeDrawioDiagramResponse(
            block={
                "id": request.block_id,
                "type": "image",
                "kind": "image",
                "blockType": "image",
                "contentText": artifacts.caption,
                "plainText": artifacts.caption,
                "markdown": f"![{artifacts.caption}](asset://{upload_response.resource_id})",
                "attrs": attrs,
                "renderKind": "drawio",
            },
            drawio_asset_id=upload_response.resource_id,
            drawio_xml=artifacts.drawio_xml,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "optimize_drawio_diagram_failed",
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Optimize draw.io diagram failed: {str(e)}",
        )


def _build_optimized_drawio_attrs(
    attrs: Dict[str, Any],
    artifacts: Any,
    drawio_asset_id: str,
) -> Dict[str, Any]:
    """构造优化后的 draw.io 图块属性."""
    next_attrs = {**(attrs if isinstance(attrs, dict) else {})}
    next_attrs.pop("architectureSpec", None)
    next_attrs["drawioAssetId"] = drawio_asset_id
    next_attrs["editableAssetId"] = drawio_asset_id
    next_attrs["caption"] = artifacts.caption
    next_attrs["alt"] = artifacts.caption
    next_attrs["renderKind"] = "drawio"
    # 前端资产列表刷新前，先用内联 XML 立即替换编辑器画布
    next_attrs["drawioXml"] = artifacts.drawio_xml
    next_attrs["title"] = artifacts.title
    return next_attrs
