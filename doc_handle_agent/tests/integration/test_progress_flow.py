"""Integration tests for fine-grained progress flow."""

import pytest
from app.core.document_engine import DocumentEngine
from app.core.state import create_initial_state, GenerationStatus


class TestProgressFlow:
    def test_progress_monotonically_increases_across_nodes(self):
        """验证进度在模拟多节点执行后是单调递增的."""
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value

        # 模拟 list_template_block 完成 (5%)
        state["current_node"] = "list_template_block"
        state["progress"] = 5.0
        engine._task_states["flow_test"] = state.copy()

        p1 = engine.get_progress("flow_test")
        assert p1["progress"] == 5.0

        # 模拟 generate_blocks 第 2/4 块 (15% + 55% * 0.5 = 42.5%)
        state["current_node"] = "generate_blocks"
        state["progress"] = 42.5
        state["message"] = "正在生成第 2/4 个内容块..."
        engine._task_states["flow_test"] = state.copy()

        p2 = engine.get_progress("flow_test")
        assert p2["progress"] == 42.5
        assert "2/4" in p2["message"]

        # 模拟 process_image_blocks 第 1/2 块 (70% + 15% * 0.5 = 77.5%)
        state["current_node"] = "process_image_blocks"
        state["progress"] = 77.5
        state["message"] = "正在处理第 1/2 个图片资源..."
        engine._task_states["flow_test"] = state.copy()

        p3 = engine.get_progress("flow_test")
        assert p3["progress"] == 77.5

    def test_old_task_without_progress_field(self):
        """验证没有 progress 字段的旧任务回退到旧映射."""
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "create_document"
        # Do NOT set progress
        engine._task_states["flow_old"] = state

        result = engine.get_progress("flow_old")
        assert result["progress"] == 70

    def test_node_weights_sum_to_one(self):
        """验证节点权重总和为 1.0."""
        weights = DocumentEngine._NODE_WEIGHTS.values()
        assert sum(weights) == pytest.approx(1.0)
