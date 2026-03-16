"""流水线编排器."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4

from app.config import get_settings
from app.domain.models.pipeline import (
    PipelineStage,
    PipelineState,
    PipelineStatus,
    StageResult,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """流水线上下文."""

    pipeline_id: str
    repo_path: str
    repo_name: str
    config: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)


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


class CheckpointManager:
    """断点管理器."""

    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, pipeline_id: str) -> Path:
        """获取断点文件路径."""
        return self.checkpoint_dir / f"{pipeline_id}.json"

    async def save(self, state: PipelineState) -> None:
        """保存流水线状态.

        Args:
            state: 流水线状态
        """
        checkpoint_path = self._get_checkpoint_path(state.pipeline_id)
        try:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"Checkpoint saved: {checkpoint_path}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise

    async def load(self, pipeline_id: str) -> Optional[PipelineState]:
        """加载流水线状态.

        Args:
            pipeline_id: 流水线ID

        Returns:
            流水线状态或None
        """
        checkpoint_path = self._get_checkpoint_path(pipeline_id)
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PipelineState.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None

    async def clear(self, pipeline_id: str) -> None:
        """清除断点数据.

        Args:
            pipeline_id: 流水线ID
        """
        checkpoint_path = self._get_checkpoint_path(pipeline_id)
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            logger.debug(f"Checkpoint cleared: {checkpoint_path}")


class PipelineOrchestrator:
    """流水线编排器."""

    def __init__(self):
        self._handlers: Dict[PipelineStage, PipelineStageHandler] = {}
        self._checkpoint_manager = CheckpointManager(get_settings().checkpoint_dir)
        self._running_pipelines: Dict[str, asyncio.Task] = {}

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
        repo_path: str,
        repo_name: str,
        config: Optional[Dict[str, Any]] = None,
        resume_from: Optional[PipelineStage] = None,
    ) -> str:
        """启动流水线.

        Args:
            repo_path: 仓库路径
            repo_name: 仓库名称
            config: 配置选项
            resume_from: 从指定阶段恢复

        Returns:
            流水线ID
        """
        pipeline_id = str(uuid4())
        context = PipelineContext(
            pipeline_id=pipeline_id,
            repo_path=repo_path,
            repo_name=repo_name,
            config=config or {},
        )

        # 创建任务并执行
        task = asyncio.create_task(
            self._run_pipeline(context, resume_from),
            name=f"pipeline-{pipeline_id}",
        )
        self._running_pipelines[pipeline_id] = task

        logger.info(f"Pipeline started: {pipeline_id}")
        return pipeline_id

    async def _run_pipeline(
        self,
        context: PipelineContext,
        resume_from: Optional[PipelineStage] = None,
    ) -> None:
        """运行流水线.

        Args:
            context: 流水线上下文
            resume_from: 从指定阶段恢复
        """
        # 定义阶段顺序
        stage_order = [
            PipelineStage.REPO_TRAVERSAL,
            PipelineStage.CODE_PARSING,
            PipelineStage.SYMBOL_EXTRACTION,
            PipelineStage.STRUCTURE_GRAPH_BUILD,
            PipelineStage.DEPENDENCY_ANALYSIS,
            PipelineStage.DEPENDENCY_GRAPH_BUILD,
            PipelineStage.SEMANTIC_ANALYSIS,
            PipelineStage.EMBEDDING_GENERATION,
            PipelineStage.VECTOR_DB_STORE,
            PipelineStage.MODULE_DETECTION,
            PipelineStage.SEMANTIC_GRAPH_BUILD,
        ]

        # 创建或加载状态
        if resume_from:
            state = await self._checkpoint_manager.load(context.pipeline_id)
            if state is None:
                raise ValueError(
                    f"Cannot resume pipeline {context.pipeline_id}: checkpoint not found"
                )
        else:
            state = PipelineState(
                pipeline_id=context.pipeline_id,
                repo_path=context.repo_path,
                repo_name=context.repo_name,
                overall_status=PipelineStatus.RUNNING,
            )

        try:
            # 确定起始阶段索引
            start_idx = 0
            if resume_from:
                for i, stage in enumerate(stage_order):
                    if stage == resume_from:
                        start_idx = i
                        break

            # 执行各阶段
            for stage in stage_order[start_idx:]:
                # 检查是否有处理器
                if stage not in self._handlers:
                    logger.warning(f"No handler for stage: {stage.value}, skipping")
                    continue

                # 执行阶段
                result = await self._execute_stage(stage, context)
                state.update_stage(stage, result)

                # 保存断点
                await self._checkpoint_manager.save(state)

                # 如果阶段失败，停止流水线
                if result.status == PipelineStatus.FAILED:
                    state.overall_status = PipelineStatus.FAILED
                    logger.error(
                        f"Pipeline {context.pipeline_id} failed at stage {stage.value}"
                    )
                    break

            # 更新最终状态
            if state.overall_status != PipelineStatus.FAILED:
                state.overall_status = PipelineStatus.COMPLETED
                state.current_stage = PipelineStage.COMPLETED
                logger.info(f"Pipeline {context.pipeline_id} completed successfully")

        except Exception as e:
            state.overall_status = PipelineStatus.FAILED
            logger.exception(f"Pipeline {context.pipeline_id} failed: {e}")

        finally:
            # 保存最终状态
            await self._checkpoint_manager.save(state)

            # 从运行列表中移除
            if context.pipeline_id in self._running_pipelines:
                del self._running_pipelines[context.pipeline_id]

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
        logger.info(f"Stage {stage.value} started")

        try:
            result = await handler.execute(context)
            result.start_time = start_time
            result.end_time = datetime.utcnow()
            result.stage = stage

            logger.info(
                f"Stage {stage.value} completed in {result.duration_seconds:.2f}s"
            )
            return result

        except Exception as e:
            logger.exception(f"Stage {stage.value} failed: {e}")
            return StageResult(
                stage=stage,
                status=PipelineStatus.FAILED,
                start_time=start_time,
                end_time=datetime.utcnow(),
                message=str(e),
            )

    async def get_state(self, pipeline_id: str) -> Optional[PipelineState]:
        """获取流水线状态.

        Args:
            pipeline_id: 流水线ID

        Returns:
            流水线状态或None
        """
        return await self._checkpoint_manager.load(pipeline_id)

    async def cancel(self, pipeline_id: str) -> bool:
        """取消流水线.

        Args:
            pipeline_id: 流水线ID

        Returns:
            是否成功取消
        """
        if pipeline_id not in self._running_pipelines:
            return False

        task = self._running_pipelines[pipeline_id]
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"Pipeline {pipeline_id} cancelled")

        # 更新状态
        state = await self._checkpoint_manager.load(pipeline_id)
        if state:
            state.overall_status = PipelineStatus.PAUSED
            await self._checkpoint_manager.save(state)

        del self._running_pipelines[pipeline_id]
        return True

    async def restart(
        self,
        repo_path: str,
        repo_name: str,
        clear_existing: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """重新启动流水线.

        Args:
            repo_path: 仓库路径
            repo_name: 仓库名称
            clear_existing: 是否清除已有数据
            config: 配置选项

        Returns:
            新流水线ID
        """
        # 如果需要清除数据，执行清除逻辑
        if clear_existing:
            # TODO: 调用存储层清除数据
            logger.info(f"Cleared existing data for repo: {repo_name}")

        # 启动新流水线
        return await self.start(repo_path, repo_name, config)


# 全局编排器实例
_orchestrator: Optional[PipelineOrchestrator] = None


def get_orchestrator() -> PipelineOrchestrator:
    """获取流水线编排器实例."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
    return _orchestrator
