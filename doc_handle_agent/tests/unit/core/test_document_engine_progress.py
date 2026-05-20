import pytest
from app.core.document_engine import DocumentEngine
from app.core.state import create_initial_state, GenerationStatus


class TestDocumentEngineProgress:
    def test_get_progress_uses_fine_grained_when_available(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "generate_blocks"
        state["progress"] = 62.5
        state["message"] = "正在生成第 3/12 块..."
        engine._task_states["flow_1"] = state

        result = engine.get_progress("flow_1")

        assert result["progress"] == 62.5
        assert result["message"] == "正在生成第 3/12 块..."
        assert result["current_step"] == 4

    def test_get_progress_falls_back_to_old_mapping(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.GENERATING.value
        state["current_node"] = "generate_blocks"
        # Do NOT set progress
        engine._task_states["flow_2"] = state

        result = engine.get_progress("flow_2")

        assert result["progress"] == 55

    def test_get_progress_completed_state(self):
        engine = DocumentEngine()
        state = create_initial_state(repo_id="r1", template_id="t1")
        state["status"] = GenerationStatus.COMPLETED.value
        state["document_id"] = "doc_1"
        engine._task_states["flow_3"] = state

        result = engine.get_progress("flow_3")

        assert result["progress"] == 100
        assert result["document_id"] == "doc_1"
