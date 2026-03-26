"""MCP 工具实现."""

import json
import logging
from typing import Dict, List, Optional, Any

from app.infrastructure.db import GraphDatabaseClient, VectorDatabaseClient
from app.domain.llm.client import get_llm_service

logger = logging.getLogger(__name__)


class KnowledgeBaseTools:
    """知识底座工具类."""

    def __init__(self, neo4j: GraphDatabaseClient, milvus: VectorDatabaseClient):
        self.neo4j = neo4j
        self.milvus = milvus
        self.llm_service = get_llm_service()

    async def get_project_structure(self, repo_name: str) -> str:
        """获取项目目录结构."""
        query = """
        MATCH (r:Repository {name: $repo_name})-[:CONTAIN*]->(n)
        WHERE n:Directory OR n:File
        RETURN n.path as path, n.type as type, labels(n) as labels
        ORDER BY path
        """
        results = await self.neo4j.execute_query(query, {"repo_name": repo_name})

        if not results:
            return f"Repository '{repo_name}' not found or empty."

        # 构建树形结构
        structure = {"repository": repo_name, "items": []}
        for result in results:
            structure["items"].append({
                "path": result["path"],
                "type": result["labels"][0] if result["labels"] else "Unknown",
            })

        return json.dumps(structure, indent=2, ensure_ascii=False)

    async def search_nodes(
        self,
        repo_name: str,
        query: str,
        node_types: List[str],
        top_k: int = 10,
    ) -> str:
        """根据关键字语义查询节点."""
        # 1. 将查询向量化
        try:
            embeddings = await self.llm_service.generate_embeddings([query])
            if not embeddings:
                return "Failed to generate embedding for query."
            query_vector = embeddings[0]
        except Exception as e:
            return f"Embedding generation failed: {e}"

        # 2. 根据节点类型搜索不同的 collection
        all_results = []

        collection_map = {
            "File": "file_summary_collection",
            "Class": "class_summary_collection",
            "Method": "method_summary_collection",
            "Module": "semantic_summary_collection",
            "Workflow": "semantic_summary_collection",
        }

        for node_type in node_types:
            collection = collection_map.get(node_type)
            if not collection:
                continue

            try:
                filter_expr = f'repo == "{repo_name}"'
                if node_type in ["Module", "Workflow"]:
                    filter_expr += f' && type == "{node_type}"'

                results = await self.milvus.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    top_k=top_k,
                    filter_expr=filter_expr,
                )

                for result in results:
                    result["node_type"] = node_type
                    all_results.append(result)

            except Exception as e:
                logger.warning(f"Search failed in {collection}: {e}")

        # 3. 获取详细信息
        detailed_results = []
        for result in all_results[:top_k]:
            node_info = await self.neo4j.get_node_by_id(result["node_id"])
            if node_info:
                detailed_results.append({
                    "node_id": result["node_id"],
                    "name": result["name"],
                    "type": result["node_type"],
                    "distance": result["distance"],
                    "details": node_info.get("node", {}),
                })

        return json.dumps({
            "query": query,
            "results": detailed_results,
        }, indent=2, ensure_ascii=False)

    async def get_modules(self, repo_name: str) -> str:
        """获取项目的 Module 列表."""
        query = """
        MATCH (m:Module)
        WHERE m.repo = $repo_name OR m.id STARTS WITH $repo_prefix
        RETURN m.id as id, m.name as name, m.description as description, m.summary as summary
        """
        results = await self.neo4j.execute_query(
            query,
            {"repo_name": repo_name, "repo_prefix": f"module_{repo_name}_"},
        )

        modules = []
        for result in results:
            modules.append({
                "id": result["id"],
                "name": result["name"],
                "description": result.get("description", ""),
                "summary": result.get("summary", ""),
            })

        return json.dumps({
            "repo_name": repo_name,
            "modules": modules,
        }, indent=2, ensure_ascii=False)

    async def get_module_workflows(self, repo_name: str, module_id: str) -> str:
        """获取 Module 对应的 Workflow 列表."""
        query = """
        MATCH (w:Workflow)-[:BELONG_TO]->(m:Module {id: $module_id})
        RETURN w.id as id, w.name as name, w.description as description, w.summary as summary
        """
        results = await self.neo4j.execute_query(query, {"module_id": module_id})

        workflows = []
        for result in results:
            workflows.append({
                "id": result["id"],
                "name": result["name"],
                "description": result.get("description", ""),
                "summary": result.get("summary", ""),
            })

        return json.dumps({
            "module_id": module_id,
            "workflows": workflows,
        }, indent=2, ensure_ascii=False)

    async def get_node_by_id(self, node_id: str) -> str:
        """根据节点 ID 获取节点信息."""
        # 获取节点基本信息
        node_info = await self.neo4j.get_node_by_id(node_id)
        if not node_info:
            return f"Node not found: {node_id}"

        # 获取节点关系
        relationships = await self.neo4j.get_node_relationships(node_id)

        return json.dumps({
            "node": node_info.get("node", {}),
            "labels": node_info.get("labels", []),
            "relationships": relationships,
        }, indent=2, ensure_ascii=False)

    async def get_node_dependencies(
        self,
        node_id: str,
        depth: int = 1,
    ) -> str:
        """获取节点的依赖关系图."""
        query = """
        MATCH path = (n {id: $node_id})-[r*1..$depth]-(m)
        WHERE n <> m
        RETURN n.id as source_id, labels(n) as source_labels,
               m.id as target_id, labels(m) as target_labels,
               [rel in r | type(rel)] as rel_types,
               length(path) as distance
        LIMIT 100
        """
        results = await self.neo4j.execute_query(
            query,
            {"node_id": node_id, "depth": depth},
        )

        dependencies = []
        for result in results:
            dependencies.append({
                "source": {
                    "id": result["source_id"],
                    "labels": result["source_labels"],
                },
                "target": {
                    "id": result["target_id"],
                    "labels": result["target_labels"],
                },
                "relationships": result["rel_types"],
                "distance": result["distance"],
            })

        return json.dumps({
            "node_id": node_id,
            "depth": depth,
            "dependencies": dependencies,
        }, indent=2, ensure_ascii=False)

    async def get_file_content(self, file_id: str) -> str:
        """获取文件内容."""
        # 获取文件节点
        node_info = await self.neo4j.get_node_by_id(file_id)
        if not node_info:
            return f"File not found: {file_id}"

        node = node_info.get("node", {})
        file_path = node.get("path", "")
        repo_path = node.get("repo", "")

        # 尝试读取文件
        try:
            from pathlib import Path
            full_path = Path(f"./repos/{repo_path}/{file_path}")
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                return json.dumps({
                    "file_id": file_id,
                    "path": file_path,
                    "content": content,
                }, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to read file {file_id}: {e}")

        # 返回节点信息作为备用
        return json.dumps({
            "file_id": file_id,
            "path": file_path,
            "note": "File content not available, returning metadata",
            "metadata": node,
        }, indent=2, ensure_ascii=False)

    async def search_code(
        self,
        repo_name: str,
        query: str,
        top_k: int = 10,
    ) -> str:
        """语义搜索代码."""
        # 1. 将查询向量化
        try:
            embeddings = await self.llm_service.generate_embeddings([query])
            if not embeddings:
                return "Failed to generate embedding for query."
            query_vector = embeddings[0]
        except Exception as e:
            return f"Embedding generation failed: {e}"

        # 2. 在代码 collection 中搜索
        all_results = []

        collections = ["class_code_collection", "method_code_collection"]

        for collection in collections:
            try:
                results = await self.milvus.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    top_k=top_k,
                    filter_expr=f'repo == "{repo_name}"',
                )

                for result in results:
                    result["collection"] = collection
                    all_results.append(result)

            except Exception as e:
                logger.warning(f"Search failed in {collection}: {e}")

        # 3. 获取代码详情
        detailed_results = []
        for result in all_results[:top_k]:
            node_info = await self.neo4j.get_node_by_id(result["node_id"])
            if node_info:
                node = node_info.get("node", {})
                detailed_results.append({
                    "node_id": result["node_id"],
                    "name": result["name"],
                    "type": "Class" if "class" in result["collection"] else "Method",
                    "path": node.get("filePath", ""),
                    "code": node.get("code", "")[:500],  # 限制代码长度
                    "distance": result["distance"],
                })

        return json.dumps({
            "query": query,
            "results": detailed_results,
        }, indent=2, ensure_ascii=False)
