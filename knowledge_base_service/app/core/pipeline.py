"""流水线编排器."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from app.core.pipeline_logger import get_pipeline_log_manager
from app.domain.models.pipeline import (
    PipelineStage,
    PipelineStatus,
    PipelineContext,
    StageResult,
    STAGE_ORDER,
)
from app.infrastructure.csv_storage import (
    get_repo_status_storage,
    InitializationStatus,
)

logger = logging.getLogger(__name__)




class PipelineStageHandler:
    """流水线阶段处理器基类."""

    stage: PipelineStage

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行阶段任务.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        raise NotImplementedError


class PipelineOrchestrator:
    """流水线编排器."""

    def __init__(self):
        self._handlers: Dict[PipelineStage, PipelineStageHandler] = {}
        self._log_manager = get_pipeline_log_manager()
        self._running_pipelines: Dict[str, asyncio.Task] = {}
        # 正在运行中的流水线上下文
        self._running_repos_contexts: Dict[str, PipelineContext] = {}

    def register_handler(
        self,
        stage: PipelineStage,
        handler: PipelineStageHandler,
    ) -> None:
        """注册阶段处理器.

        Args:
            stage: 阶段枚举
            handler: 阶段处理器
        """
        self._handlers[stage] = handler
        logger.debug(f"Registered handler for stage: {stage.value}")

    async def start(
        self,
        repo_id: str,
        repo_path: str,
        repo_name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """启动新流水线.

        Args:
            repo_id: 仓库ID
            repo_path: 仓库路径
            repo_name: 仓库名称
            config: 配置选项

        Returns:
            流水线ID
        """
        pipeline_id = str(uuid4())
        context = PipelineContext(
            pipeline_id=pipeline_id,
            repo_id=repo_id,
            repo_path=repo_path,
            repo_name=repo_name,
            config=config or {},
        )

        # 为新流水线准备日志目录（会归档旧日志）
        self._log_manager.prepare_new_pipeline(repo_id)

        # 确定起始阶段为新流水线的第一个阶段
        start_stage = STAGE_ORDER[0]

        self._running_repos_contexts[repo_id] = context

        # 创建CSV记录（Pending状态）
        repo_storage = get_repo_status_storage()
        repo_storage.create_record(
            repo_id=repo_id,
            repo_name=repo_name,
            repo_path=repo_path,
            status=InitializationStatus.PENDING,
        )

        # 记录流水线启动
        self._log_manager.log_pipeline_started(
            repo_id=context.repo_id,
            pipeline_id=context.pipeline_id,
            repo_name=context.repo_name,
            repo_path=context.repo_path
        )

        # 创建任务并执行
        task = asyncio.create_task(
            self._run_pipeline(context, start_stage),
            name=f"pipeline-{pipeline_id}",
        )
        self._running_pipelines[repo_id] = task

        return pipeline_id

    async def resume(
        self,
        repo_id: str,
    ) -> str:
        """恢复流水线.

        Args:
            repo_id: 仓库ID

        Returns:
            流水线ID

        Raises:
            ValueError: 如果找不到流水线上下文
        """
        # 加载已有上下文
        context = await self._log_manager.load_context(repo_id)
        if context is None:
            raise ValueError(
                f"Cannot resume repo {repo_id} pipeline: context not found"
            )
        self._running_repos_contexts[repo_id] = context

        # 记录流水线恢复
        self._log_manager.log_pipeline_resumed(
            repo_id=context.repo_id,
            pipeline_id=context.pipeline_id,
            completed_stages=[
                stage for stage, result in context.stages.items()
                if result.status == PipelineStatus.COMPLETED
            ],
            resume_from=context.current_stage
        )

        # 创建任务并执行
        task = asyncio.create_task(
            self._run_pipeline(context, context.current_stage),
            name=f"pipeline-{context.pipeline_id}",
        )
        self._running_pipelines[context.pipeline_id] = task

        return context.pipeline_id

    async def _run_pipeline(
        self,
        context: PipelineContext,
        start_stage: PipelineStage,
    ) -> None:
        """运行流水线.

        Args:
            context: 流水线上下文
            start_stage: 起始阶段
        """
        context.overall_status = PipelineStatus.RUNNING

        try:
            # 确定起始阶段索引
            start_idx = 0
            for i, stage in enumerate(STAGE_ORDER):
                if stage == start_stage:
                    start_idx = i
                    break

            # 执行各阶段
            for stage in STAGE_ORDER[start_idx:]:

                context.current_stage = stage
                # 保存上下文, 保证执行阶段失败可恢复
                await self._log_manager.save_context(context)

                # 记录阶段开始
                self._log_manager.log_stage_started(
                    repo_id=context.repo_id,
                    pipeline_id=context.pipeline_id,
                    stage=stage,
                )

                # 检查是否有处理器
                if stage not in self._handlers:
                    error_msg = f"No handler registered for stage: {stage.value}"
                    context.overall_status = PipelineStatus.FAILED
                    self._log_manager.log_stage_failed(
                        repo_id=context.repo_id,
                        pipeline_id=context.pipeline_id,
                        stage=stage,
                        duration=0.0,
                        error=error_msg,
                    )
                    break

                # 执行阶段
                result = await self._execute_stage(stage, context)
                context.update_stage(stage, result)

                # 记录阶段结果
                if result.status == PipelineStatus.COMPLETED:
                    self._log_manager.log_stage_completed(
                        repo_id=context.repo_id,
                        pipeline_id=context.pipeline_id,
                        stage=stage,
                        duration=result.duration_seconds or 0.0,
                    )
                else:
                    self._log_manager.log_stage_failed(
                        repo_id=context.repo_id,
                        pipeline_id=context.pipeline_id,
                        stage=stage,
                        duration=result.duration_seconds or 0.0,
                        error=result.message,
                    )

                    # 如果阶段失败，停止流水线
                    context.overall_status = PipelineStatus.FAILED
                    break

            # 更新最终状态
            if context.overall_status != PipelineStatus.FAILED:
                context.overall_status = PipelineStatus.COMPLETED
                context.current_stage = PipelineStage.COMPLETED


        except Exception as e:
            context.overall_status = PipelineStatus.FAILED

        finally:
            # 更新CSV记录状态
            repo_storage = get_repo_status_storage()
            if context.overall_status == PipelineStatus.COMPLETED:
                self._log_manager.log_pipeline_completed(
                    repo_id=context.repo_id,
                    pipeline_id=context.pipeline_id,
                )
                repo_storage.update_status(context.repo_id, InitializationStatus.COMPLETED)
            else:
                self._log_manager.log_pipeline_failed(
                    repo_id=context.repo_id,
                    pipeline_id=context.pipeline_id,
                    failed_stage=context.current_stage,
                )
                repo_storage.update_status(context.repo_id, InitializationStatus.FAILED)

            # 从运行列表中移除
            if context.pipeline_id in self._running_pipelines:
                del self._running_pipelines[context.pipeline_id]
            if context.repo_id in self._running_repos_contexts:
                del self._running_repos_contexts[context.repo_id]

    async def _execute_stage(
        self,
        stage: PipelineStage,
        context: PipelineContext,
    ) -> StageResult:
        """执行单个阶段.

        Args:
            stage: 阶段枚举
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        handler = self._handlers[stage]
        start_time = datetime.utcnow()

        try:
            result = await handler.execute(context)
            result.start_time = start_time
            result.end_time = datetime.utcnow()
            result.stage = stage
            return result

        except Exception as e:
            return StageResult(
                stage=stage,
                status=PipelineStatus.FAILED,
                start_time=start_time,
                end_time=datetime.utcnow(),
                message=str(e),
            )

    def get_running_context(self, repo_id: str) -> Optional[PipelineContext]:
        """通过repo_id获取正在运行的流水线上下文.

        Args:
            repo_id: 仓库ID

        Returns:
            流水线上下文或None
        """
        if repo_id in self._running_repos_contexts:
            return self._running_repos_contexts[repo_id]
        return None

    def get_static_context(self, repo_id: str) -> Optional[PipelineContext] :
        """通过repo_id获取日志文件中的上下文.

        Args:
            repo_id: 仓库ID

        Returns:
            流水线上下文或None
        """
        return self._log_manager.load_context(repo_id)




# 全局编排器实例
_orchestrator: Optional[PipelineOrchestrator] = None


def get_orchestrator() -> PipelineOrchestrator:
    """获取流水线编排器实例."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator
