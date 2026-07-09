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
    RegenerateDrawioArchitectureRequest,
    RegenerateDrawioArchitectureResponse,
)
from app.core.nodes.process_image_blocks_node import ProcessImageBlocksNode
from app.core.document_engine import get_document_engine
from app.domain.drawio_architecture import DiagramArtifacts, render_drawio_architecture
from app.domain.drawio_architecture_regenerate_agent import DrawioArchitectureRegenerateAgent
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


@router.post("/optimizeDrawioDiagram", response_model=RegenerateDrawioArchitectureResponse)
@router.post("/regenerateDrawioArchitecture", response_model=RegenerateDrawioArchitectureResponse)
async def optimize_drawio_diagram(
    request: RegenerateDrawioArchitectureRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> RegenerateDrawioArchitectureResponse:
    """优化 draw.io 图.

    接收前端当前块上下文，按 current_xml 决定走 XML 优化或 JSON 重生成，并上传 draw.io 源文件
    """
    logger.info(
        "api_optimize_drawio_diagram",
        repo_id=request.repo_id,
        document_id=request.document_id,
        block_id=request.block_id,
        has_current_spec=bool(request.current_spec),
        has_current_xml=bool(request.current_xml),
        has_prompt=bool(request.prompt and request.prompt.strip()),
    )

    if not request.block_id:
        raise HTTPException(status_code=400, detail="block_id is required")
    if not request.document_id:
        raise HTTPException(status_code=400, detail="document_id is required")

    try:
        agent = DrawioArchitectureRegenerateAgent()
        if request.current_xml and request.current_xml.strip():
            # 编辑器 AI 优化以当前 XML 为事实源，避免 JSON renderer 重排用户手动改过的图
            optimized_xml = await agent.optimize_xml(request)
            raw_architecture_spec = request.current_spec or request.attrs.get("architectureSpec") or {}
            architecture_spec = raw_architecture_spec if isinstance(raw_architecture_spec, dict) else {}
            title = request.title or str(architecture_spec.get("title") or request.attrs.get("title") or "项目总体架构图")
            artifacts = DiagramArtifacts(
                title=title,
                caption=title,
                spec=architecture_spec,
                svg="",
                drawio_xml=optimized_xml,
            )
        else:
            architecture_spec = await agent.regenerate(request)
            title = request.title or str(architecture_spec.get("title") or "项目总体架构图")
            artifacts = render_drawio_architecture(architecture_spec, fallback_title=title)

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

        attrs = _build_regenerated_drawio_attrs(
            request.attrs,
            artifacts=artifacts,
            drawio_asset_id=upload_response.resource_id,
        )
        return RegenerateDrawioArchitectureResponse(
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
            architecture_spec=artifacts.spec,
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
            detail=f"Regenerate draw.io architecture failed: {str(e)}",
        )


def _build_regenerated_drawio_attrs(
    attrs: Dict[str, Any],
    artifacts: Any,
    drawio_asset_id: str,
) -> Dict[str, Any]:
    """构造重生成后的架构图块属性."""
    next_attrs = ProcessImageBlocksNode._build_drawio_architecture_attrs(
        attrs if isinstance(attrs, dict) else {},
        artifacts,
        drawio_asset_id,
    )
    # 前端资产列表刷新前，先用内联 XML 立即替换编辑器画布
    next_attrs["drawioXml"] = artifacts.drawio_xml
    next_attrs["format"] = "drawio_architecture"
    next_attrs["title"] = artifacts.title
    return next_attrs
