"""初始化相关 API 路由."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pipeline import get_orchestrator
from app.infrastructure.csv_storage import get_repo_status_storage, InitializationStatus

router = APIRouter()


class StartInitializationRequest(BaseModel):
    """启动初始化请求."""

    repo_id: str = Field(..., description="仓库ID")
    repo_path: str = Field(..., description="仓库路径")
    repo_name: str = Field(..., description="仓库名称")
    config: Optional[Dict[str, Any]] = Field(
        default=None, description="配置选项"
    )


class InitializationResponse(BaseModel):
    """初始化响应."""

    pipeline_id: str
    repo_id: str
    status: str
    current_stage: str
    created_at: str


class RestartInitializationRequest(BaseModel):
    """重新初始化请求."""

    repo_id: str = Field(..., description="仓库ID")
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

    repo_id: str = Field(..., description="仓库ID")


class InitializationStatusResponse(BaseModel):
    """初始化状态响应."""

    repo_id: str
    status: str = Field(..., description="初始化状态: NotInitialized, Pending, Completed, Failed, Running")
    repo_name: Optional[str] = None
    repo_path: Optional[str] = None
    message: Optional[str] = None


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
            repo_id=request.repo_id,
            repo_path=request.repo_path,
            repo_name=request.repo_name,
            config=request.config,
        )

        # 获取初始上下文
        ctx = orchestrator.get_running_context(request.repo_id)
        if not ctx:
            raise HTTPException(
                status_code=500, detail="Failed to get pipeline context"
            )

        return InitializationResponse(
            pipeline_id=pipeline_id,
            repo_id=request.repo_id,
            status=ctx.overall_status.value,
            current_stage=ctx.current_stage.value,
            created_at=ctx.created_at.isoformat(),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start initialization: {str(e)}"
        )


@router.post("/resume", response_model=InitializationResponse)
async def resume_initialization(
    request: ResumeInitializationRequest,
) -> InitializationResponse:
    """恢复流水线.

    从已有流水线上下文恢复执行

    Args:
        request: 恢复请求

    Returns:
        初始化响应
    """
    orchestrator = get_orchestrator()

    try:
        # 恢复流水线
        pipeline_id = await orchestrator.resume(
            repo_id=request.repo_id,
        )

        # 获取上下文
        ctx = orchestrator.get_running_context(request.repo_id)
        if not ctx:
            raise HTTPException(
                status_code=500, detail="Failed to get pipeline context"
            )

        return InitializationResponse(
            pipeline_id=pipeline_id,
            repo_id=ctx.repo_id,
            status=ctx.overall_status.value,
            current_stage=ctx.current_stage.value,
            created_at=ctx.created_at.isoformat(),
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to resume initialization: {str(e)}"
        )


@router.get("/{repo_id}/status", response_model=InitializationStatusResponse)
async def get_initialization_status(repo_id: str) -> InitializationStatusResponse:
    """获取仓库初始化状态.

    根据repoId从CSV文件中查询对应信息：
    - 查不到记录: 未进行初始化 (NotInitialized)
    - 记录为Pending且正在运行: 初始化中 (Running)
    - 记录为Pending但不在运行: 挂起/等待恢复 (Pending)
    - 记录为Completed: 初始化成功 (Completed)
    - 记录为Failed: 初始化失败 (Failed)

    Args:
        repo_id: 仓库ID

    Returns:
        初始化状态响应
    """
    orchestrator = get_orchestrator()
    repo_storage = get_repo_status_storage()

    # 从CSV获取记录
    record = repo_storage.get_record(repo_id)

    # 检查是否正在运行
    running_context = orchestrator.get_running_context(repo_id)
    is_running = running_context is not None

    if record is None:
        # 未找到记录，表示未进行初始化
        return InitializationStatusResponse(
            repo_id=repo_id,
            status="NotInitialized",
            message="Repository has not been initialized",
        )

    # 根据记录状态和运行状态确定最终状态
    if record.initial_status == InitializationStatus.COMPLETED:
        return InitializationStatusResponse(
            repo_id=repo_id,
            status="Completed",
            repo_name=record.repo_name,
            repo_path=record.repo_path,
            message="Initialization completed successfully",
        )
    elif record.initial_status == InitializationStatus.FAILED:
        return InitializationStatusResponse(
            repo_id=repo_id,
            status="Failed",
            repo_name=record.repo_name,
            repo_path=record.repo_path,
            message="Initialization failed",
        )
    elif record.initial_status == InitializationStatus.PENDING:
        if is_running:
            return InitializationStatusResponse(
                repo_id=repo_id,
                status="Running",
                repo_name=record.repo_name,
                repo_path=record.repo_path,
                message="Initialization is in progress",
            )
        else:
            return InitializationStatusResponse(
                repo_id=repo_id,
                status="Pending",
                repo_name=record.repo_name,
                repo_path=record.repo_path,
                message="Initialization is pending or can be resumed",
            )

    # 未知状态
    return InitializationStatusResponse(
        repo_id=repo_id,
        status="Unknown",
        repo_name=record.repo_name,
        repo_path=record.repo_path,
        message=f"Unknown initialization status: {record.initial_status}",
    )
