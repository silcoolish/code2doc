"""流水线单元测试."""

import pytest
import asyncio
from datetime import datetime

from app.core.pipeline import (
    PipelineOrchestrator,
    PipelineContext,
    CheckpointManager,
    get_orchestrator,
)
from app.domain.models.pipeline import (
    PipelineStage,
    PipelineState,
    PipelineStatus,
    StageResult,
)


class TestPipelineOrchestrator:
    """测试流水线编排器."""

    @pytest.fixture
    def orchestrator(self):
        return PipelineOrchestrator()

    @pytest.fixture
    def context(self):
        return PipelineContext(
            pipeline_id="test-pipeline",
            repo_path="/test/repo",
            repo_name="test-repo",
        )

    def test_get_orchestrator_singleton(self):
        """测试单例模式."""
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2

    def test_register_handler(self, orchestrator):
        """测试注册处理器."""
        from app.core.pipeline import PipelineStageHandler

        class TestHandler(PipelineStageHandler):
            stage = PipelineStage.REPO_TRAVERSAL

            async def execute(self, context):
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                )

        handler = TestHandler()
        orchestrator.register_handler(PipelineStage.REPO_TRAVERSAL, handler)

        assert orchestrator._handlers[PipelineStage.REPO_TRAVERSAL] is handler


class TestCheckpointManager:
    """测试断点管理器."""

    @pytest.fixture
    def checkpoint_manager(self, tmp_path):
        return CheckpointManager(str(tmp_path))

    @pytest.mark.asyncio
    async def test_save_and_load(self, checkpoint_manager):
        """测试保存和加载."""
        state = PipelineState(
            pipeline_id="test-id",
            repo_path="/test",
            repo_name="test-repo",
            current_stage=PipelineStage.CODE_PARSING,
            overall_status=PipelineStatus.RUNNING,
        )

        # 保存
        await checkpoint_manager.save(state)

        # 加载
        loaded = await checkpoint_manager.load("test-id")

        assert loaded is not None
        assert loaded.pipeline_id == "test-id"
        assert loaded.repo_name == "test-repo"
        assert loaded.current_stage == PipelineStage.CODE_PARSING

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, checkpoint_manager):
        """测试加载不存在的断点."""
        loaded = await checkpoint_manager.load("nonexistent-id")
        assert loaded is None


class TestPipelineState:
    """测试流水线状态."""

    def test_progress_percent(self):
        """测试进度计算."""
        state = PipelineState(
            pipeline_id="test",
            repo_path="/test",
            repo_name="test",
        )

        # 初始进度
        assert state.progress_percent == 0

        # 完成几个阶段
        state.update_stage(
            PipelineStage.REPO_TRAVERSAL,
            StageResult(
                stage=PipelineStage.REPO_TRAVERSAL,
                status=PipelineStatus.COMPLETED,
            ),
        )

        # 应该有进度
        assert state.progress_percent > 0
