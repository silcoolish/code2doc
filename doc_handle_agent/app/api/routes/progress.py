"""进度查询API路由."""

from fastapi import APIRouter, HTTPException

from app.api.models.schemas import GenerationProgressResponse
from app.core.document_engine import get_document_engine
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["progress"])


@router.get("/{flow_id}/progress", response_model=GenerationProgressResponse)
async def get_generation_progress(
    flow_id: str,
) -> GenerationProgressResponse:
    """获取文档生成进度.

    Args:
        flow_id: 流程ID

    Returns:
        进度响应

    Raises:
        HTTPException: 流程不存在
    """
    engine = get_document_engine()
    progress = engine.get_progress(flow_id)

    if progress.get("status") == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"Generation flow not found: {flow_id}",
        )

    return GenerationProgressResponse(
        flow_id=progress["flow_id"],
        repo_id=progress["repo_id"],
        status=progress["status"],
        progress=progress["progress"],
        current_step=progress["current_step"],
        total_steps=progress["total_steps"],
        message=progress["message"],
        output_path=progress.get("output_path"),
        error=progress.get("error"),
    )


@router.post("/{flow_id}/cancel")
async def cancel_generation(flow_id: str) -> dict:
    """取消文档生成任务.

    Args:
        flow_id: 流程ID

    Returns:
        取消结果

    Raises:
        HTTPException: 流程不存在或无法取消
    """
    logger.info(
        "api_cancel_generation",
        flow_id=flow_id,
    )

    engine = get_document_engine()

    if flow_id not in engine._task_states:
        raise HTTPException(
            status_code=404,
            detail=f"Generation flow not found: {flow_id}",
        )

    success = await engine.cancel_generation(flow_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to cancel generation or generation already completed",
        )

    return {
        "flow_id": flow_id,
        "cancelled": True,
        "message": "Generation cancelled successfully",
    }
