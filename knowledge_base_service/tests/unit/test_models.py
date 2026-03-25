"""模型单元测试."""

import pytest
from datetime import datetime

from app.domain.models.graph import (
    Repository,
    Directory,
    File,
    Class,
    Method,
    Module,
)
from app.domain.models.pipeline import (
    PipelineStage,
    PipelineStatus,
    StageResult,
)
from app.core.pipeline import PipelineContext


class TestGraphModels:
    """测试图模型."""

    def test_repository_to_dict(self):
        """测试 Repository 转换为字典."""
        repo = Repository(
            id="repo_1",
            name="test-repo",
            path="/path/to/repo",
        )

        data = repo.to_dict()

        assert data["id"] == "repo_1"
        assert data["name"] == "test-repo"
        assert data["type"] == "Repository"
        assert data["path"] == "/path/to/repo"

    def test_file_to_dict(self):
        """测试 File 转换为字典."""
        file_node = File(
            id="file_1",
            name="test.py",
            path="src/test.py",
            file_type="code",
            suffix=".py",
        )

        data = file_node.to_dict()

        assert data["id"] == "file_1"
        assert data["name"] == "test.py"
        assert data["type"] == "File"
        assert data["path"] == "src/test.py"
        assert data["fileType"] == "code"
        assert data["suffix"] == ".py"

    def test_class_to_dict(self):
        """测试 Class 转换为字典."""
        class_node = Class(
            id="class_1",
            name="TestClass",
            file_path="src/test.py",
            start_line=10,
            end_line=50,
            language="python",
            code="class TestClass: pass",
        )

        data = class_node.to_dict()

        assert data["id"] == "class_1"
        assert data["name"] == "TestClass"
        assert data["type"] == "Class"
        assert data["filePath"] == "src/test.py"
        assert data["startLine"] == 10
        assert data["endLine"] == 50


class TestPipelineModels:
    """测试流水线模型."""

    def test_stage_result_duration(self):
        """测试阶段执行时长计算."""
        result = StageResult(
            stage=PipelineStage.REPO_TRAVERSAL,
            status=PipelineStatus.COMPLETED,
            start_time=datetime(2024, 1, 1, 12, 0, 0),
            end_time=datetime(2024, 1, 1, 12, 1, 30),
        )

        assert result.duration_seconds == 90.0

    def test_stage_result_duration_none(self):
        """测试无时长的情况."""
        result = StageResult(
            stage=PipelineStage.REPO_TRAVERSAL,
            status=PipelineStatus.RUNNING,
        )

        assert result.duration_seconds is None

    def test_pipeline_context_update_stage(self):
        """测试 PipelineContext 更新阶段."""
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

        assert ctx.current_stage == PipelineStage.REPO_TRAVERSAL
        assert ctx.stages[PipelineStage.REPO_TRAVERSAL] == result
        assert ctx.progress > 0

    def test_pipeline_context_progress(self):
        """测试 PipelineContext 进度计算."""
        ctx = PipelineContext(
            pipeline_id="test",
            repo_id="test-repo-id",
            repo_path="/test",
            repo_name="test-repo",
        )

        # 初始进度
        assert ctx.progress == 0.0

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
