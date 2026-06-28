"""MCP 工具实现."""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.infrastructure.db import GraphDatabaseClient, VectorDatabaseClient
from app.domain.llm import get_llm_service

logger = logging.getLogger(__name__)

# 获取项目根目录（基于当前文件位置：app/mcp/）
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 统一的向量数据库 collection 名称
VECTOR_COLLECTION_NAME = "code_vectors"


class KnowledgeBaseTools:
    """知识底座工具类."""

    def __init__(self, graph_db: GraphDatabaseClient, vector_db: VectorDatabaseClient):
        self.graph_db = graph_db
        self.vector_db = vector_db
        self.llm_service = get_llm_service()

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def _filter_fields(
        record: Dict[str, Any],
        returns: Optional[List[str]],
        defaults: List[str],
    ) -> Dict[str, Any]:
        """根据 returns 参数过滤返回字段.

        Args:
            record: 原始记录字典
            returns: 用户指定的返回字段列表，None 时使用 defaults
            defaults: 默认返回字段列表

        Returns:
            过滤后的记录字典
        """
        keys = returns if returns else defaults
        return {k: record.get(k) for k in keys if k in record or k in record.get("details", {})}

    @staticmethod
    def _normalize_node_type(labels: List[str]) -> str:
        """从 labels 中提取节点类型."""
        for label in labels:
            if label in ("File", "Class", "Method", "Module", "Workflow", "Directory", "Repository"):
                return label
        return labels[0] if labels else "Unknown"

    @staticmethod
    def _truncate_text(value: Any, max_length: int) -> str:
        """截断工具返回文本，避免大字段撑爆模型上下文."""
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}..."

    async def _search_nodes_by_name_as_fallback(
        self,
        repo_id: str,
        query_text: str,
        node_types: List[str],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """语义搜索不可用时按名称模糊查找节点."""
        try:
            name_results = await self.graph_db.search_nodes_by_name(
                repo_id=repo_id,
                name=query_text,
                node_types=node_types,
                fuzzy=True,
                top_k=top_k,
            )
        except Exception as e:
            logger.warning(f"Name fallback search failed for {query_text}: {e}")
            return []
        fallback_results: List[Dict[str, Any]] = []
        for nr in name_results:
            fallback_results.append({
                "node_id": nr.get("id"),
                "name": nr.get("name"),
                "node_type": self._normalize_node_type(nr.get("types", [])),
                "distance": 0.0,
                "_is_name_fallback": True,
                "summary": nr.get("summary", ""),
                "file_path": nr.get("file_path", ""),
                "docstring": nr.get("docstring", ""),
            })
        return fallback_results

    # ------------------------------------------------------------------ #
    # 仓库统计
    # ------------------------------------------------------------------ #

    async def get_repo_stats(self, repo_id: str) -> str:
        """获取仓库统计信息.

        用于快速了解代码仓库的规模、语言分布和基本统计指标。
        在制定文档生成策略、评估仓库复杂度、判断是否需要分模块处理时调用此工具。

        返回的 `scale` 字段根据代码文件数和总行数自动判定：
        - small: 代码文件 < 100 或总行数 < 1万
        - medium: 代码文件 100-1000 或总行数 1万-10万
        - large: 代码文件 > 1000 或总行数 > 10万

        Args:
            repo_id: 仓库ID

        Returns:
            JSON 字符串，包含仓库规模、统计指标和语言分布
        """
        try:
            # 查询 Repository 节点统计字段
            repo = await self.graph_db.get_repository_stats(repo_id)
            if not repo:
                return json.dumps(
                    {"repo_id": repo_id, "error": "Repository not found"},
                    indent=2, ensure_ascii=False
                )

            # 查询图数据库中的目录/类/方法数量
            stats = await self.graph_db.get_repo_node_counts(repo_id)

            total_files = repo.get("total_files", 0) or 0
            total_code_files = repo.get("total_code_files", 0) or 0
            total_lines = repo.get("total_lines", 0) or 0
            total_size = repo.get("total_size", 0) or 0

            # 规模等级判定
            scale = "small"
            if total_code_files > 1000 or total_lines > 100000:
                scale = "large"
            elif total_code_files > 100 or total_lines > 10000:
                scale = "medium"

            # 派生指标
            code_file_ratio = (
                round(total_code_files / total_files, 2) if total_files > 0 else 0.0
            )
            avg_file_size = (
                round(total_size / total_files) if total_files > 0 else 0
            )
            avg_lines_per_code_file = (
                round(total_lines / total_code_files) if total_code_files > 0 else 0
            )

            result = {
                "repo_id": repo_id,
                "name": repo.get("name", ""),
                "path": repo.get("path", ""),
                "scale": scale,
                "statistics": {
                    "total_files": total_files,
                    "total_code_files": total_code_files,
                    "total_lines": total_lines,
                    "total_size": total_size,
                    "directories": stats.get("directory_count", 0),
                    "classes": stats.get("class_count", 0),
                    "methods": stats.get("method_count", 0),
                },
                "languages": repo.get("languages", []) or [],
                "language_distribution": repo.get("language_distribution", {}) or {},
                "derived_metrics": {
                    "code_file_ratio": code_file_ratio,
                    "avg_file_size": avg_file_size,
                    "avg_lines_per_code_file": avg_lines_per_code_file,
                },
            }

            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to get repo stats for {repo_id}: {e}")
            return json.dumps(
                {"repo_id": repo_id, "error": str(e)},
                indent=2, ensure_ascii=False
            )

    # ------------------------------------------------------------------ #
    # 项目结构
    # ------------------------------------------------------------------ #

    async def get_project_structure(self, repo_id: str) -> str:
        """获取项目目录结构.

        当你需要了解仓库的整体文件组织、模块划分、或生成"项目结构概述"
        类文档段落时调用此工具。返回目录和文件的层级关系及摘要。

        Args:
            repo_id: 仓库ID

        Returns:
            JSON 字符串，包含目录和文件列表（id, path, type, summary）
        """
        results = await self.graph_db.get_project_structure(repo_id)

        if not results:
            return json.dumps({"repo_id": repo_id, "items": []}, indent=2, ensure_ascii=False)

        max_items = 500
        max_summary_length = 120
        items = []
        seen_keys = set()
        unique_total = 0
        for result in results:
            path = result.get("path", "")
            dedupe_key = path or result.get("id", "")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            unique_total += 1
            if len(items) >= max_items:
                continue
            item = {
                "id": result.get("id", ""),
                "path": path,
                "type": self._normalize_node_type(result.get("labels", [])),
            }
            summary = result.get("summary")
            if summary:
                item["summary"] = self._truncate_text(summary, max_summary_length)
            items.append(item)

        return json.dumps({
            "repo_id": repo_id,
            "items": items,
            "total_items": len(results),
            "unique_items": unique_total,
            "returned_items": len(items),
            "truncated": unique_total > len(items),
        }, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 统一搜索入口（合并语义搜索 + 名称搜索）
    # ------------------------------------------------------------------ #

    async def search_nodes(
        self,
        repo_id: str,
        queries: List[Dict[str, Any]],
    ) -> str:
        """统一搜索节点入口（语义搜索 + 名称搜索）.

        这是查找节点的主要工具。根据 search_mode 选择搜索策略：
        - "semantic": 按功能语义搜索（基于向量相似度）。适用于：你想找"做某件事"的代码
          或功能模块，但不知道确切名称的场景，例如"用户认证"、"订单状态流转"。
        - "name": 按节点名称搜索（基于图数据库名称匹配）。适用于：已知类名/方法名/模块名，
          想快速定位的场景，例如"AuthService"、"authenticateUser"。

        搜索后通常需要配合 `batch_get_node_details` 获取源代码和详细摘要。

        Args:
            repo_id: 仓库ID
            queries: 查询参数列表，每个查询包含:
                - query: 搜索关键字 (必需)
                - search_mode: 搜索模式，"semantic" | "name"，默认 "semantic"
                - node_types: 节点类型列表。
                    代码节点: ["File", "Class", "Method"]
                    语义节点: ["Module", "Workflow"]
                    默认 ["File", "Class", "Method"]
                - top_k: 返回结果数量，默认 10
                - fuzzy: 仅 search_mode="name" 时有效，是否模糊匹配，默认 True
                - returns: 指定返回字段列表，如 ["node_id", "name", "summary"]。
                  默认返回: node_id, name, node_type, summary, file_path, distance
                  语义节点额外返回: details

        Returns:
            JSON 字符串，包含批量查询结果
        """
        if not queries:
            return json.dumps({"repo_id": repo_id, "results": []}, indent=2, ensure_ascii=False)

        # 收集所有语义搜索的查询文本，批量生成 embedding
        semantic_queries = [
            (idx, q) for idx, q in enumerate(queries)
            if q.get("search_mode", "semantic") == "semantic" and q.get("query")
        ]
        semantic_embeddings: Dict[int, List[float]] = {}

        if semantic_queries:
            all_texts = [q.get("query", "") for _, q in semantic_queries]
            try:
                embeddings = await self.llm_service.generate_embeddings(all_texts)
                for (idx, _), emb in zip(semantic_queries, embeddings):
                    semantic_embeddings[idx] = emb
            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")

        default_returns = ["node_id", "name", "node_type", "summary", "file_path", "distance"]

        batch_results = []
        for idx, query_params in enumerate(queries):
            query_text = query_params.get("query", "")
            if not query_text:
                continue

            search_mode = query_params.get("search_mode", "semantic")
            node_types = query_params.get("node_types", ["File", "Class", "Method"])
            top_k = query_params.get("top_k", 10)
            returns = query_params.get("returns")
            result_keys = returns if returns else default_returns

            all_results: List[Dict[str, Any]] = []

            if search_mode == "semantic":
                query_vector = semantic_embeddings.get(idx)
                if query_vector is None:
                    fallback_results = await self._search_nodes_by_name_as_fallback(
                        repo_id=repo_id,
                        query_text=query_text,
                        node_types=node_types,
                        top_k=top_k,
                    )
                    batch_results.append({
                        "query": query_text,
                        "search_mode": "semantic",
                        "node_types": node_types,
                        "error": "Failed to generate embedding",
                        "results": [
                            {
                                k: v for k, v in record.items()
                                if k in result_keys and not k.startswith("_")
                            }
                            for record in fallback_results
                        ],
                    })
                    continue

                for node_type in node_types:
                    try:
                        filter_expr = f'repo == "{repo_id}" && type == "{node_type}"'
                        vec_results = await self.vector_db.search(
                            collection_name=VECTOR_COLLECTION_NAME,
                            query_vector=query_vector,
                            top_k=top_k,
                            filter_expr=filter_expr,
                        )
                        for vr in vec_results:
                            node_info = await self.graph_db.get_node_by_id(vr.get("node_id", ""))
                            node = node_info.get("node", {}) if node_info else {}
                            record = {
                                "node_id": vr.get("node_id"),
                                "name": vr.get("name"),
                                "node_type": node_type,
                                "distance": vr.get("distance", 0),
                                "summary": vr.get("summary", ""),
                                "file_path": node.get("filePath") or node.get("path", ""),
                            }
                            if node_type in ("Module", "Workflow"):
                                record["details"] = node.get("detail", "")
                            all_results.append(record)
                    except Exception as e:
                        logger.warning(f"Semantic search failed for {node_type}: {e}")
                        fallback_results = await self._search_nodes_by_name_as_fallback(
                            repo_id=repo_id,
                            query_text=query_text,
                            node_types=[node_type],
                            top_k=top_k,
                        )
                        all_results.extend(fallback_results)

            else:  # search_mode == "name"
                fuzzy = query_params.get("fuzzy", True)
                try:
                    name_results = await self.graph_db.search_nodes_by_name(
                        repo_id=repo_id,
                        name=query_text,
                        node_types=node_types,
                        fuzzy=fuzzy,
                        top_k=top_k,
                    )
                    for nr in name_results:
                        record = {
                            "node_id": nr.get("id"),
                            "name": nr.get("name"),
                            "node_type": self._normalize_node_type(nr.get("types", [])),
                            "file_path": nr.get("file_path", ""),
                            "summary": nr.get("summary", ""),
                            "docstring": nr.get("docstring", ""),
                            "distance": 1.0,  # 名称搜索无距离概念，统一为 1.0
                        }
                        all_results.append(record)
                except Exception as e:
                    logger.warning(f"Name search failed for '{query_text}': {e}")

            # 语义搜索优先保留向量结果，名称兜底只用于补充缺口
            if search_mode == "semantic":
                all_results.sort(
                    key=lambda x: (
                        not x.get("_is_name_fallback", False),
                        x.get("distance") or 0,
                    ),
                    reverse=True,
                )

            # 过滤字段
            filtered_results = []
            for result in all_results[:top_k]:
                filtered = {
                    k: v for k, v in result.items()
                    if k in result_keys and not k.startswith("_")
                }
                filtered_results.append(filtered)

            batch_results.append({
                "query": query_text,
                "search_mode": search_mode,
                "node_types": node_types,
                "results": filtered_results,
            })

        return json.dumps({"repo_id": repo_id, "results": batch_results}, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 关联节点查询
    # ------------------------------------------------------------------ #

    async def get_related_nodes(
        self,
        repo_id: str,
        queries: List[Dict[str, Any]],
    ) -> str:
        """批量获取与指定节点具有特定关系的所有节点.

        这是一个通用关系查询工具，用于替代各种专用的"获取子节点"类操作。
        通过指定节点ID、关系类型和方向，获取所有关联节点。

        典型使用场景：
        - 获取模块下的所有工作流: node_id=模块ID, rel_type="BELONG_TO", direction="in"
        - 获取文件包含的所有类/方法: node_id=文件ID, rel_type="CONTAIN", direction="out"
        - 获取类包含的所有方法: node_id=类ID, rel_type="CONTAIN", direction="out"
        - 获取方法调用的所有方法: node_id=方法ID, rel_type="CALL", direction="out"
        - 获取引用某个文件的所有文件: node_id=文件ID, rel_type="USE", direction="in"

        Args:
            repo_id: 仓库ID
            queries: 查询参数列表，每个查询包含:
                - node_id: 节点ID (必需)
                - rel_type: 关系类型 (必需)。可选枚举值:
                    - "BELONG_TO": 属于关系（如 Workflow 属于 Module）
                    - "CONTAIN": 包含关系（如 File 包含 Class/Method）
                    - "CALL": 调用关系（Method 调用 Method）
                    - "USE": 使用关系（File 使用 File）
                - direction: 关系方向，可选值 ["out", "in", "both"]，默认 "out"
                    - "out": 获取该节点指向的节点（ outgoing ）
                    - "in": 获取指向该节点的节点（ incoming ）
                    - "both": 双向
                - returns: 指定返回字段列表，如 ["node_id", "name", "summary"]。
                  默认返回: node_id, name, node_type, summary, description

        Returns:
            JSON 字符串，包含批量查询结果
        """
        if not queries:
            return json.dumps({"repo_id": repo_id, "results": []}, indent=2, ensure_ascii=False)

        default_returns = ["node_id", "name", "node_type", "summary", "description"]
        batch_results = []

        for query in queries:
            node_id = query.get("node_id")
            rel_type = query.get("rel_type")
            direction = query.get("direction", "out")
            returns = query.get("returns")
            result_keys = returns if returns else default_returns

            if not node_id:
                batch_results.append({"node_id": None, "error": "Missing node_id", "related_nodes": []})
                continue
            if not rel_type:
                batch_results.append({"node_id": node_id, "error": "Missing rel_type", "related_nodes": []})
                continue

            try:
                results = await self.graph_db.get_related_nodes(node_id, rel_type, direction)
                related_nodes = []
                for result in results:
                    record = {
                        "node_id": result.get("id"),
                        "name": result.get("name"),
                        "node_type": self._normalize_node_type(result.get("labels", [])),
                        "summary": result.get("summary", ""),
                        "description": result.get("description", ""),
                    }
                    related_nodes.append({k: v for k, v in record.items() if k in result_keys})

                batch_results.append({
                    "node_id": node_id,
                    "rel_type": rel_type,
                    "direction": direction,
                    "related_nodes": related_nodes,
                })
            except Exception as e:
                logger.error(f"Failed to get related nodes for {node_id} via {rel_type}: {e}")
                batch_results.append({
                    "node_id": node_id,
                    "rel_type": rel_type,
                    "direction": direction,
                    "error": str(e),
                    "related_nodes": [],
                })

        return json.dumps({"repo_id": repo_id, "results": batch_results}, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 节点依赖
    # ------------------------------------------------------------------ #

    async def get_node_dependencies(
        self,
        queries: List[Dict[str, Any]],
    ) -> str:
        """批量获取节点的依赖关系图.

        适用于：生成"模块间调用关系"、"依赖分析"、"系统交互"类文档段落。
        传入节点ID（如方法ID、类ID），返回该节点的上下游依赖关系。

        Args:
            queries: 查询参数列表，每个查询包含:
                - node_id: 节点ID (必需)
                - depth: 依赖深度，默认 1
                - returns: 指定返回字段列表，如 ["source", "target", "distance"]。
                  默认返回: source, target, relationships, distance

        Returns:
            JSON 字符串，包含批量查询结果
        """
        if not queries:
            return json.dumps({"error": "No queries provided", "results": []}, indent=2, ensure_ascii=False)

        default_returns = ["source", "target", "relationships", "distance"]
        batch_results = []

        for query in queries:
            node_id = query.get("node_id")
            depth = query.get("depth", 1)
            returns = query.get("returns")
            result_keys = returns if returns else default_returns

            if not node_id:
                batch_results.append({"node_id": None, "error": "Missing node_id", "dependencies": []})
                continue

            try:
                dependencies = await self.graph_db.get_node_dependencies(node_id, depth)
                filtered = []
                for dep in dependencies:
                    record = {
                        "source": dep.get("source"),
                        "target": dep.get("target"),
                        "relationships": dep.get("relationships", []),
                        "distance": dep.get("distance", 0),
                    }
                    filtered.append({k: v for k, v in record.items() if k in result_keys})
                batch_results.append({"node_id": node_id, "depth": depth, "dependencies": filtered})
            except Exception as e:
                logger.error(f"Failed to get dependencies for node {node_id}: {e}")
                batch_results.append({"node_id": node_id, "depth": depth, "error": str(e), "dependencies": []})

        return json.dumps({"results": batch_results}, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 枚举节点（get_all_nodes + 语义化别名）
    # ------------------------------------------------------------------ #

    async def get_all_nodes(
        self,
        repo_id: str,
        node_types: List[str],
        returns: Optional[List[str]] = None,
    ) -> str:
        """获取仓库中所有指定类型的节点列表.

        适用于：需要"枚举"所有节点的场景，例如生成文档段落标题列表、获取完整的方法清单/类清单。
        如果需要获取节点详情（如代码内容、详细摘要），获取 node_id 后请配合 `batch_get_node_details` 使用。

        Args:
            repo_id: 仓库ID
            node_types: 节点类型列表，决定返回哪些类型的节点。
                可选枚举值：
                - "File": 文件节点
                - "Class": 类节点
                - "Method": 方法节点
                - "Module": 功能模块节点
                - "Workflow": 工作流节点
                - "Directory": 目录节点
                可传入多个类型，如 ["Class", "Method"] 同时返回类和方法。
            returns: 指定返回字段列表，如 ["node_id", "name", "summary"]。
                默认返回: node_id, name, node_type, file_path, summary, description
                可选字段: node_id, name, node_type, file_path, summary, description, language

        Returns:
            JSON 字符串，包含所有节点的简要信息列表
        """
        try:
            results = await self.graph_db.get_all_nodes(repo_id, node_types)
            default_returns = ["node_id", "name", "node_type", "file_path", "summary", "description"]
            result_keys = returns if returns else default_returns

            nodes = []
            for result in results:
                record = {
                    "node_id": result.get("id"),
                    "name": result.get("name"),
                    "node_type": self._normalize_node_type(result.get("types", [])),
                    "file_path": result.get("file_path", ""),
                    "summary": result.get("summary", ""),
                    "language": result.get("language", ""),
                    "description": result.get("description", ""),
                }
                nodes.append({k: v for k, v in record.items() if k in result_keys})

            return json.dumps({"repo_id": repo_id, "total": len(nodes), "nodes": nodes}, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to get all nodes for repo {repo_id}: {e}")
            return json.dumps({"repo_id": repo_id, "error": str(e), "total": 0, "nodes": []}, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 图片 ID
    # ------------------------------------------------------------------ #

    async def batch_get_image_ids(
        self,
        repo_id: str,
        node_ids: List[str],
    ) -> str:
        """批量获取节点对应图片的 ID.

        适用于：文档中需要插入流程图、架构图、方法调用图等图片的场景。
        传入节点ID（通常是 Method 或 Workflow 节点），返回图片的文件 ID。
        使用图片 ID 可通过 /images/{repo_id}/{image_id} 接口下载图片。

        Args:
            repo_id: 仓库ID
            node_ids: 节点 ID 列表

        Returns:
            JSON 字符串，包含每个节点对应的图片 ID 信息
        """
        if not node_ids:
            return json.dumps({"repo_id": repo_id, "success": False, "error": "No node IDs provided", "images": []}, indent=2, ensure_ascii=False)

        image_results = []
        for node_id in node_ids:
            try:
                node_info = await self.graph_db.get_node_by_id(node_id)
                if not node_info:
                    image_results.append({"node_id": node_id, "success": False, "error": "Node not found"})
                    continue

                node = node_info.get("node", {})
                image_id = node.get("image", "")
                node_name = node.get("name", "")
                node_type = node.get("type", "")
                file_path = node.get("filePath") or node.get("path", "")
                start_line = node.get("startLine") or 1
                end_line = node.get("endLine") or start_line

                if not image_id:
                    image_results.append({"node_id": node_id, "node_name": node_name, "node_type": node_type, "success": False, "error": "No image available"})
                    continue

                image_results.append({
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_type": node_type,
                    "file_path": file_path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "source_ref": {
                        "sourceId": node_id,
                        "symbolName": node_name,
                        "filePath": file_path,
                        "lineStart": start_line,
                        "lineEnd": end_line,
                    },
                    "success": True,
                    "image_id": image_id,
                })
            except Exception as e:
                logger.error(f"Failed to get image ID for node {node_id}: {e}")
                image_results.append({"node_id": node_id, "success": False, "error": str(e)})

        success_count = sum(1 for img in image_results if img.get("success"))
        return json.dumps({
            "repo_id": repo_id,
            "success": success_count > 0,
            "total": len(node_ids),
            "success_count": success_count,
            "failed_count": len(node_ids) - success_count,
            "images": image_results,
        }, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # 节点详情
    # ------------------------------------------------------------------ #

    async def batch_get_node_details(
        self,
        repo_id: str,
        node_ids: List[str],
        returns: Optional[List[str]] = None,
    ) -> str:
        """批量根据节点 ID 获取节点详情.

        适用于：生成需要引用源代码、详细摘要或文档字符串的文档段落。
        通常在 `search_nodes` 或 `get_all_nodes` 获取节点ID后，使用此工具获取详细信息。

        Args:
            repo_id: 仓库ID
            node_ids: 节点 ID 列表
            returns: 指定返回字段列表，如 ["node_id", "name", "summary", "code"]。
                默认返回: node_id, name, node_type, file_path, code, summary, docstring, language, suffix

        Returns:
            JSON 字符串，包含每个节点的完整属性信息
        """
        if not node_ids:
            return json.dumps({"repo_id": repo_id, "total": 0, "success_count": 0, "failed_count": 0, "nodes": []}, indent=2, ensure_ascii=False)

        try:
            results = await self.graph_db.batch_get_node_details(repo_id=repo_id, node_ids=node_ids)

            default_returns = ["node_id", "name", "node_type", "file_path", "code", "summary", "docstring", "language", "suffix"]
            result_keys = returns if returns else default_returns

            result_map = {}
            for result in results:
                node_id = result.get("id", "")
                record = {
                    "node_id": node_id,
                    "name": result.get("name", ""),
                    "node_type": self._normalize_node_type(result.get("types", [])),
                    "file_path": result.get("file_path", ""),
                    "code": result.get("code", ""),
                    "summary": result.get("summary", ""),
                    "docstring": result.get("docstring", ""),
                    "language": result.get("language", ""),
                    "suffix": result.get("suffix", ""),
                    "success": True,
                }
                result_map[node_id] = {k: v for k, v in record.items() if k in result_keys or k == "success"}

            node_details = []
            for node_id in node_ids:
                if node_id in result_map:
                    node_details.append(result_map[node_id])
                else:
                    node_details.append({"node_id": node_id, "success": False, "error": "Node not found"})

            success_count = sum(1 for n in node_details if n.get("success"))
            return json.dumps({
                "repo_id": repo_id,
                "total": len(node_ids),
                "success_count": success_count,
                "failed_count": len(node_ids) - success_count,
                "nodes": node_details,
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to batch get node details: {e}")
            return json.dumps({"repo_id": repo_id, "error": str(e), "total": len(node_ids), "success_count": 0, "failed_count": len(node_ids), "nodes": []}, indent=2, ensure_ascii=False)
