"""进度查询 API 路由."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import get_orchestrator
from app.domain.models.pipeline import PipelineStatus

router = APIRouter()


class StageInfo(BaseModel):
    """阶段信息."""

    stage: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    message: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProgressResponse(BaseModel):
    """进度响应."""

    pipeline_id: str
    repo_name: str
    overall_status: str
    current_stage: str
    progress_percent: int
    stages: List[StageInfo]
    created_at: str
    updated_at: str


@router.get("/{pipeline_id}/progress", response_model=ProgressResponse)
async def get_progress(pipeline_id: str) -> ProgressResponse:
    """获取流水线构建进度.

    Args:
        pipeline_id: 流水线ID

    Returns:
        进度响应
    """
    orchestrator = get_orchestrator()

    # 获取状态
    state = await orchestrator.get_state(pipeline_id)
    if not state:
        raise HTTPException(
            status_code=404, detail=f"Pipeline not found: {pipeline_id}"
        )

    # 构建阶段信息列表
    stages = []
    for stage_result in state.stages.values():
        stages.append(
            StageInfo(
                stage=stage_result.stage.value,
                status=stage_result.status.value,
                start_time=stage_result.start_time.isoformat() if stage_result.start_time else None,
                end_time=stage_result.end_time.isoformat() if stage_result.end_time else None,
                duration_seconds=stage_result.duration_seconds,
                message=stage_result.message,
                metadata=stage_result.metadata,
            )
        )

    # 按阶段顺序排序
    stage_order = [
        "repo_traversal",
        "code_parsing",
        "symbol_extraction",
        "structure_graph_build",
        "dependency_analysis",
        "dependency_graph_build",
        "semantic_analysis",
        "embedding_generation",
        "vector_db_store",
        "module_detection",
        "semantic_graph_build",
    ]
    stages.sort(key=lambda s: stage_order.index(s.stage) if s.stage in stage_order else 999)

    return ProgressResponse(
        pipeline_id=state.pipeline_id,
        repo_name=state.repo_name,
        overall_status=state.overall_status.value,
        current_stage=state.current_stage.value,
        progress_percent=state.progress_percent,
        stages=stages,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat(),
    )


@router.get("/{pipeline_id}/status")
async def get_status(pipeline_id: str) -> Dict[str, Any]:
    """获取流水线简要状态.

    Args:
        pipeline_id: 流水线ID

    Returns:
        状态信息
    """
    orchestrator = get_orchestrator()

    # 获取状态
    state = await orchestrator.get_state(pipeline_id)
    if not state:
        raise HTTPException(
            status_code=404, detail=f"Pipeline not found: {pipeline_id}"
        )

    return {
        "pipeline_id": state.pipeline_id,
        "repo_name": state.repo_name,
        "status": state.overall_status.value,
        "current_stage": state.current_stage.value,
        "progress_percent": state.progress_percent,
    }
