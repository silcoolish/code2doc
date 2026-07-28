from datetime import datetime

import pytest

from app.api.routes import lineage


class FakeGraphClient:
    async def get_lineage_graph_page(self, repo_id, page, page_size):
        assert repo_id == "repo-1"
        assert page == 1
        assert page_size == 2
        return {
            "total": 3,
            "counts": {"File": 1, "Method": 2},
            "nodes": [
                {
                    "id": "method-1",
                    "persistent_id": "method-1",
                    "node_type": "Method",
                    "name": "run",
                    "file_path": "src\\main.py",
                    "qualified_name": "Worker.run",
                    "line_start": 10,
                    "line_end": 20,
                    "summary": "启动流程",
                    "language": "python",
                    "indexed_at": datetime(2026, 7, 28, 10, 0),
                }
            ],
            "relations": [
                {"type": "CALL", "source_id": "method-1", "target_id": "method-2"}
            ],
        }


@pytest.mark.asyncio
async def test_get_repository_lineage_graph_builds_stable_contract(monkeypatch):
    monkeypatch.setattr(lineage, "get_graph_db_client", lambda: FakeGraphClient())

    result = await lineage.get_repository_lineage_graph("repo-1", page=1, page_size=2)

    assert result["hasNext"] is True
    assert result["nodes"][0]["filePath"] == "src/main.py"
    assert result["nodes"][0]["stableKey"] == (
        "repo-1|Method|src/main.py|Worker.run|method-1"
    )
    assert result["nodes"][0]["indexedAt"] == "2026-07-28T10:00:00"
    assert result["relations"] == [
        {"type": "CALL", "sourceId": "method-1", "targetId": "method-2"}
    ]


def test_stable_key_does_not_change_when_symbol_lines_move():
    node = {
        "node_type": "Method",
        "name": "run",
        "qualified_name": "Worker.run",
        "file_path": "src/main.py",
        "line_start": 10,
        "line_end": 20,
    }

    original = lineage._stable_key("repo-1", node)
    node.update(line_start=110, line_end=120)

    assert lineage._stable_key("repo-1", node) == original


def test_stable_key_escapes_delimiter_in_symbol_name():
    node = {
        "node_type": "Method",
        "name": "run|sync",
        "file_path": "src/main.py",
    }

    assert lineage._stable_key("repo-1", node) == "repo-1|Method|src/main.py|run%7Csync"


def test_stable_key_uses_persistent_id_to_disambiguate_overloads():
    first = {
        "node_type": "Method",
        "qualified_name": "Worker.run",
        "file_path": "src/main.java",
        "persistent_id": "method-worker-run-string",
    }
    second = {**first, "persistent_id": "method-worker-run-int"}

    assert lineage._stable_key("repo-1", first) != lineage._stable_key(
        "repo-1", second
    )
