"""文档生成API路由."""

from typing import List

from fastapi import APIRouter, HTTPException

from app.api.models.schemas import (
    GenerateDocumentRequest,
    GenerateDocumentResponse,
    ActiveGenerationInfo,
    SystemStatusResponse,
    RewriteBlockRequest,
    RewriteBlockResponse,
)
from app.core.document_engine import get_document_engine
from app.domain.rewrite_agent import RewriteAgent
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/generate", response_model=GenerateDocumentResponse)
async def generate_document(
    request: GenerateDocumentRequest,
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
    )

    try:
        engine = get_document_engine()

        flow_id = await engine.start_generation(
            repo_id=request.repo_id,
            template_id=request.template_id,
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
