"""代码—文档追溯图查询API."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Query

from app.infrastructure.db import get_graph_db_client

router = APIRouter()


def _serialize_temporal(value: Any) -> Optional[str]:
    """把 Neo4j 时间值转换为 JSON 兼容字符串."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _stable_key(repo_id: str, node: Dict[str, Any]) -> str:
    """构建索引重建后仍可用于降级匹配的稳定锚点."""
    parts = [
        repo_id,
        str(node.get("node_type") or ""),
        str(node.get("file_path") or "").replace("\\", "/"),
        str(node.get("qualified_name") or node.get("name") or ""),
    ]
    # 持久节点ID可区分同一类中的重载方法，elementId 降级节点仍沿用语义锚点
    persistent_id = str(node.get("persistent_id") or "").strip()
    if persistent_id:
        parts.append(persistent_id)
    return "|".join(quote(part, safe="/._-$") for part in parts)


def _to_node(repo_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
    """把图客户端字段转换为前端稳定契约."""
    return {
        "id": node.get("id"),
        "stableKey": _stable_key(repo_id, node),
        "nodeType": node.get("node_type"),
        "name": node.get("name"),
        "filePath": str(node.get("file_path") or "").replace("\\", "/"),
        "lineStart": node.get("line_start"),
        "lineEnd": node.get("line_end"),
        "summary": node.get("summary") or "",
        "language": node.get("language") or "",
        "indexedAt": _serialize_temporal(node.get("indexed_at")),
    }


def _to_relations(relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把关系字段转换为前端稳定契约."""
    return [
        {
            "type": relation.get("type"),
            "sourceId": relation.get("source_id"),
            "targetId": relation.get("target_id"),
        }
        for relation in relations
        if relation.get("source_id") and relation.get("target_id")
    ]


@router.get("/repositories/{repo_id}/graph")
async def get_repository_lineage_graph(
    repo_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, alias="pageSize", ge=1, le=1000),
) -> Dict[str, Any]:
    """分页读取仓库完整代码图及当前页节点相关关系."""
    graph_client = get_graph_db_client()
    result = await graph_client.get_lineage_graph_page(repo_id, page, page_size)
    total = int(result.get("total") or 0)
    return {
        "available": True,
        "repoId": repo_id,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "hasNext": page * page_size < total,
        "counts": result.get("counts") or {},
        "nodes": [_to_node(repo_id, node) for node in result.get("nodes") or []],
        "relations": _to_relations(result.get("relations") or []),
    }
