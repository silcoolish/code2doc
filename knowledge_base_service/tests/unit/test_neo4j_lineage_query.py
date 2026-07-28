from unittest.mock import AsyncMock

import pytest

from app.infrastructure.db.graph.neo4j_client import Neo4jClient


@pytest.mark.asyncio
async def test_get_lineage_graph_page_applies_consistent_filters_and_pagination(
    monkeypatch,
):
    client = Neo4jClient()
    execute_query = AsyncMock(
        side_effect=[
            [
                {"node_type": "File", "count": 2},
                {"node_type": "Class", "count": 1},
                {"node_type": "Method", "count": 3},
            ],
            [
                {
                    "id": "method-repo-src-worker-run",
                    "node_type": "Method",
                    "name": "run",
                    "qualified_name": "Worker.run",
                    "file_path": "src/worker.py",
                },
                {
                    "id": "neo4j-element-id",
                    "node_type": "Method",
                    "name": "sync",
                    "qualified_name": "sync",
                    "file_path": "src/sync.py",
                },
            ],
            [
                {
                    "type": "CALL",
                    "source_id": "method-repo-src-worker-run",
                    "target_id": "method-on-another-page",
                },
                {
                    "type": "CALL",
                    "source_id": "method-on-another-page",
                    "target_id": "neo4j-element-id",
                },
            ],
        ]
    )
    monkeypatch.setattr(client, "_execute_query", execute_query)

    result = await client.get_lineage_graph_page("repo-1", page=2, page_size=2)

    assert result["total"] == 6
    assert result["counts"] == {"File": 2, "Class": 1, "Method": 3}
    assert [node["id"] for node in result["nodes"]] == [
        "method-repo-src-worker-run",
        "neo4j-element-id",
    ]
    assert len(result["relations"]) == 2
    assert execute_query.await_count == 3

    count_call, node_call, relation_call = execute_query.await_args_list
    assert count_call.args[1]["repo_id"] == "repo-1"
    assert "coalesce(n.fileType, 'code') = 'code'" in count_call.args[0]
    assert node_call.args[1]["skip"] == 2
    assert node_call.args[1]["limit"] == 2
    assert "coalesce(n.id, elementId(n)) AS id" in node_call.args[0]
    assert "owner:Class" in node_call.args[0]
    assert "owner_name + '.'" in node_call.args[0]

    relation_query = relation_call.args[0]
    relation_params = relation_call.args[1]
    assert relation_params["node_ids"] == [
        "method-repo-src-worker-run",
        "neo4j-element-id",
    ]
    assert relation_params["node_types"] == [
        "Repository",
        "Directory",
        "File",
        "Class",
        "Method",
        "Module",
        "Workflow",
    ]
    assert "labels(source)" in relation_query
    assert "labels(target)" in relation_query
    assert "coalesce(source.fileType, 'code') = 'code'" in relation_query
    assert "coalesce(target.fileType, 'code') = 'code'" in relation_query
    assert "coalesce(source.id, elementId(source)) IN $node_ids" in relation_query
    assert "coalesce(target.id, elementId(target)) IN $node_ids" in relation_query
    assert "RETURN DISTINCT type(relation) AS type" in relation_query


@pytest.mark.asyncio
async def test_get_lineage_graph_page_skips_relation_query_for_empty_page(monkeypatch):
    client = Neo4jClient()
    execute_query = AsyncMock(
        side_effect=[
            [{"node_type": "File", "count": 1}],
            [],
        ]
    )
    monkeypatch.setattr(client, "_execute_query", execute_query)

    result = await client.get_lineage_graph_page("repo-1", page=3, page_size=10)

    assert result == {
        "total": 1,
        "counts": {"File": 1},
        "nodes": [],
        "relations": [],
    }
    assert execute_query.await_count == 2
