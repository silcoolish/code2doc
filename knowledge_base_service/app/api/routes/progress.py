"""进度查询 API 路由."""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.pipeline import get_orchestrator

router = APIRouter()


class ProgressResponse(BaseModel):
    """进度响应."""

    pipeline_id: str
    repo_name: str
    overall_status: str
    current_stage: str
    progress: float
    created_at: str
    updated_at: str


@router.get("/{repo_id}/progress", response_model=ProgressResponse)
async def get_progress(repo_id: str) -> ProgressResponse:
    """获取流水线构建进度.

    Args:
        repo_id: 仓库ID

    Returns:
        进度响应
    """
    orchestrator = get_orchestrator()

    # 获取运行中的流水线上下文
    ctx = orchestrator.get_running_context(repo_id)

    if not ctx:
        raise HTTPException(
            status_code=404, detail=f"Pipeline not found for repo: {repo_id}"
        )

    return ProgressResponse(
        pipeline_id=ctx.pipeline_id,
        repo_name=ctx.repo_name,
        overall_status=ctx.overall_status.value,
        current_stage=ctx.current_stage.value,
        progress=ctx.progress,
        created_at=ctx.created_at.isoformat(),
        updated_at=ctx.updated_at.isoformat(),
    )
