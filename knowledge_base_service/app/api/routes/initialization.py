"""初始化相关 API 路由."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import get_orchestrator
from app.domain.models.pipeline import PipelineStage

router = APIRouter()


class StartInitializationRequest(BaseModel):
    """启动初始化请求."""

    repo_path: str = Field(..., description="仓库路径")
    repo_name: str = Field(..., description="仓库名称")
    config: Optional[Dict[str, Any]] = Field(
        default=None, description="配置选项"
    )


class InitializationResponse(BaseModel):
    """初始化响应."""

    pipeline_id: str
    status: str
    current_stage: str
    created_at: str


class RestartInitializationRequest(BaseModel):
    """重新初始化请求."""

    repo_path: str = Field(..., description="仓库路径")
    repo_name: str = Field(..., description="仓库名称")
    clear_existing: bool = Field(
        default=True, description="是否清除已有数据"
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None, description="配置选项"
    )


class ResumeInitializationRequest(BaseModel):
    """恢复初始化请求."""

    pipeline_id: str = Field(..., description="流水线ID")
    resume_from: str = Field(..., description="恢复阶段")


@router.post("/start", response_model=InitializationResponse)
async def start_initialization(
    request: StartInitializationRequest,
) -> InitializationResponse:
    """启动代码知识底座构建流水线.

    Args:
        request: 启动请求

    Returns:
        初始化响应
    """
    orchestrator = get_orchestrator()

    try:
        pipeline_id = await orchestrator.start(
            repo_path=request.repo_path,
            repo_name=request.repo_name,
            config=request.config,
        )

        # 获取初始状态
        state = await orchestrator.get_state(pipeline_id)
        if not state:
            raise HTTPException(
                status_code=500, detail="Failed to get pipeline state"
            )

        return InitializationResponse(
            pipeline_id=pipeline_id,
            status=state.overall_status.value,
            current_stage=state.current_stage.value,
            created_at=state.created_at.isoformat(),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start initialization: {str(e)}"
        )


@router.post("/restart", response_model=InitializationResponse)
async def restart_initialization(
    request: RestartInitializationRequest,
) -> InitializationResponse:
    """重新启动代码知识底座构建流水线.

    Args:
        request: 重新初始化请求

    Returns:
        初始化响应
    """
    orchestrator = get_orchestrator()

    try:
        pipeline_id = await orchestrator.restart(
            repo_path=request.repo_path,
            repo_name=request.repo_name,
            clear_existing=request.clear_existing,
            config=request.config,
        )

        # 获取初始状态
        state = await orchestrator.get_state(pipeline_id)
        if not state:
            raise HTTPException(
                status_code=500, detail="Failed to get pipeline state"
            )

        return InitializationResponse(
            pipeline_id=pipeline_id,
            status=state.overall_status.value,
            current_stage=state.current_stage.value,
            created_at=state.created_at.isoformat(),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to restart initialization: {str(e)}"
        )


@router.post("/resume", response_model=InitializationResponse)
async def resume_initialization(
    request: ResumeInitializationRequest,
) -> InitializationResponse:
    """从指定阶段恢复流水线.

    Args:
        request: 恢复请求

    Returns:
        初始化响应
    """
    orchestrator = get_orchestrator()

    try:
        # 验证阶段
        try:
            resume_stage = PipelineStage(request.resume_from)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stage: {request.resume_from}",
            )

        # 获取原状态
        old_state = await orchestrator.get_state(request.pipeline_id)
        if not old_state:
            raise HTTPException(
                status_code=404,
                detail=f"Pipeline not found: {request.pipeline_id}",
            )

        # 启动新流水线，从指定阶段恢复
        pipeline_id = await orchestrator.start(
            repo_path=old_state.repo_path,
            repo_name=old_state.repo_name,
            resume_from=resume_stage,
        )

        # 获取状态
        state = await orchestrator.get_state(pipeline_id)
        if not state:
            raise HTTPException(
                status_code=500, detail="Failed to get pipeline state"
            )

        return InitializationResponse(
            pipeline_id=pipeline_id,
            status=state.overall_status.value,
            current_stage=state.current_stage.value,
            created_at=state.created_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to resume initialization: {str(e)}"
        )


@router.post("/{pipeline_id}/cancel")
async def cancel_initialization(pipeline_id: str) -> Dict[str, str]:
    """取消流水线.

    Args:
        pipeline_id: 流水线ID

    Returns:
        取消结果
    """
    orchestrator = get_orchestrator()

    success = await orchestrator.cancel(pipeline_id)
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Pipeline not found or not running: {pipeline_id}"
        )

    return {
        "pipeline_id": pipeline_id,
        "status": "cancelled",
        "message": "Pipeline cancelled successfully",
    }
