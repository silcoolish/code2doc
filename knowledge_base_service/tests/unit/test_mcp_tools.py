import json

import pytest

from app.mcp.tools import KnowledgeBaseTools


class _FakeGraphDB:
    def __init__(self, rows):
        self.rows = rows

    async def get_project_structure(self, repo_id):
        return self.rows


class _FakeVectorDB:
    pass


def _build_structure_rows(duplicate_count: int, unique_count: int):
    rows = []
    for index in range(duplicate_count):
        rows.append({
            "id": f"dup-{index}",
            "path": f"src/dup_{index // 2}.c",
            "labels": ["File"],
            "summary": "summary-" * 40,
        })
    for index in range(unique_count):
        rows.append({
            "id": f"unique-{index}",
            "path": f"src/unique_{index}.c",
            "labels": ["File"],
            "summary": "summary-" * 40,
        })
    return rows


@pytest.mark.asyncio
async def test_get_project_structure_limits_llm_payload_size():
    tools = KnowledgeBaseTools(_FakeGraphDB(_build_structure_rows(100, 700)), _FakeVectorDB())

    data = json.loads(await tools.get_project_structure("repo-1"))

    paths = [item["path"] for item in data["items"]]
    assert data["total_items"] == 800
    assert data["unique_items"] == 750
    assert data["returned_items"] == 500
    assert data["truncated"] is True
    assert len(paths) == len(set(paths))
    assert all(len(item.get("summary", "")) <= 123 for item in data["items"])


@pytest.mark.asyncio
async def test_get_project_structure_does_not_mark_duplicates_as_truncated():
    tools = KnowledgeBaseTools(_FakeGraphDB(_build_structure_rows(100, 0)), _FakeVectorDB())

    data = json.loads(await tools.get_project_structure("repo-1"))

    paths = [item["path"] for item in data["items"]]
    assert data["total_items"] == 100
    assert data["unique_items"] == 50
    assert data["returned_items"] == 50
    assert data["truncated"] is False
    assert len(paths) == len(set(paths))


@pytest.mark.asyncio
async def test_get_project_structure_keeps_items_without_path():
    rows = [
        {"id": "node-1", "path": "", "labels": ["Function"], "summary": "a"},
        {"id": "node-2", "path": "", "labels": ["Function"], "summary": "b"},
    ]
    tools = KnowledgeBaseTools(_FakeGraphDB(rows), _FakeVectorDB())

    data = json.loads(await tools.get_project_structure("repo-1"))

    assert data["unique_items"] == 2
    assert data["returned_items"] == 2
    assert [item["id"] for item in data["items"]] == ["node-1", "node-2"]
