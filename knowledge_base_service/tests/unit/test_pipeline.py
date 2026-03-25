"""流水线单元测试."""

import pytest
import asyncio
from datetime import datetime

from app.core.pipeline import (
    PipelineOrchestrator,
    PipelineContext,
    get_orchestrator,
)
from app.core.pipeline_logger import PipelineLogManager
from app.domain.models.pipeline import (
    PipelineStage,
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
            repo_id="test-repo-id",
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


class TestPipelineLogManager:
    """测试流水线日志管理器."""

    @pytest.fixture
    def log_manager(self, tmp_path):
        return PipelineLogManager(str(tmp_path))

    @pytest.mark.asyncio
    async def test_save_and_load_context(self, log_manager):
        """测试保存和加载上下文."""
        ctx = PipelineContext(
            pipeline_id="test-id",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test-repo",
        )
        ctx.overall_status = PipelineStatus.RUNNING
        ctx.current_stage = PipelineStage.CODE_PARSING

        # 保存
        await log_manager.save_context(ctx)

        # 通过repo_id加载
        loaded = await log_manager.load_context_by_repo_id("test-repo-id")

        assert loaded is not None
        assert loaded.pipeline_id == "test-id"
        assert loaded.repo_id == "test-repo-id"
        assert loaded.repo_name == "test-repo"
        assert loaded.current_stage == PipelineStage.CODE_PARSING

    @pytest.mark.asyncio
    async def test_load_nonexistent_context(self, log_manager):
        """测试加载不存在的上下文."""
        loaded = await log_manager.load_context_by_repo_id("nonexistent-repo-id")
        assert loaded is None


class TestPipelineContext:
    """测试流水线上下文."""

    def test_progress_initial(self):
        """测试初始进度."""
        ctx = PipelineContext(
            pipeline_id="test",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test",
        )

        assert ctx.progress == 0.0

    def test_progress_after_stage_completion(self):
        """测试阶段完成后的进度."""
        ctx = PipelineContext(
            pipeline_id="test",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test",
        )

        # 完成第一个阶段
        ctx.update_stage(
            PipelineStage.REPO_TRAVERSAL,
            StageResult(
                stage=PipelineStage.REPO_TRAVERSAL,
                status=PipelineStatus.COMPLETED,
            ),
        )

        # 应该有进度 (1/11 ≈ 9.09%)
        assert ctx.progress > 0
        assert ctx.progress == pytest.approx(9.09, abs=0.01)

    def test_get_stage_result(self):
        """测试获取阶段结果."""
        ctx = PipelineContext(
            pipeline_id="test",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test-repo",
        )

        result = StageResult(
            stage=PipelineStage.REPO_TRAVERSAL,
            status=PipelineStatus.COMPLETED,
        )

        ctx.update_stage(PipelineStage.REPO_TRAVERSAL, result)

        # 可以获取已完成的阶段
        retrieved = ctx.get_stage_result(PipelineStage.REPO_TRAVERSAL)
        assert retrieved == result

        # 未开始的阶段返回 None
        assert ctx.get_stage_result(PipelineStage.CODE_PARSING) is None

    def test_update_stage_updates_timestamp(self):
        """测试更新阶段会更新时间戳."""
        ctx = PipelineContext(
            pipeline_id="test",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test-repo",
        )

        old_updated_at = ctx.updated_at

        # 稍微等待确保时间变化
        import time
        time.sleep(0.01)

        ctx.update_stage(
            PipelineStage.REPO_TRAVERSAL,
            StageResult(
                stage=PipelineStage.REPO_TRAVERSAL,
                status=PipelineStatus.COMPLETED,
            ),
        )

        assert ctx.updated_at > old_updated_at
