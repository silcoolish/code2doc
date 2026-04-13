"""MCP 工具实现."""

import base64
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.config import get_settings
from app.infrastructure.db import GraphDatabaseClient, VectorDatabaseClient
from app.domain.llm.client import get_llm_service

logger = logging.getLogger(__name__)


class KnowledgeBaseTools:
    """知识底座工具类."""

    def __init__(self, graph_db: GraphDatabaseClient, vector_db: VectorDatabaseClient):
        self.graph_db = graph_db
        self.vector_db = vector_db
        self.llm_service = get_llm_service()

    async def get_project_structure(self, repo_id: str) -> str:
        """获取项目目录结构."""
        results = await self.graph_db.get_project_structure(repo_id)

        if not results:
            return f"Repository '{repo_id}' not found or empty."

        # 构建树形结构
        structure = {"repository": repo_id, "items": []}
        for result in results:
            item = {
                "id": result.get("id", ""),
                "path": result.get("path", ""),
                "type": result["labels"][0] if result.get("labels") else "Unknown",
            }
            # 添加 summary（如果有）
            summary = result.get("summary")
            if summary:
                item["summary"] = summary
            structure["items"].append(item)

        return json.dumps(structure, indent=2, ensure_ascii=False)

    async def search_code_nodes(
        self,
        repo_id: str,
        query: str,
        node_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> str:
        """根据关键字语义查询代码节点 (FILE, METHOD, CLASS).

        Args:
            repo_id: 仓库ID
            query: 查询关键字
            node_types: 节点类型列表，可选值为 ["File", "Class", "Method"]，默认为全部
            top_k: 返回结果数量

        Returns:
            JSON 字符串，包含查询结果
        """
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
        }

        # 默认搜索所有代码节点类型
        if node_types is None:
            node_types = ["File", "Class", "Method"]

        for node_type in node_types:
            if node_type not in collection_map:
                logger.warning(f"Invalid code node type: {node_type}")
                continue

            collection = collection_map[node_type]

            try:
                filter_expr = f'repo == "{repo_id}"'

                results = await self.vector_db.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    top_k=top_k,
                    filter_expr=filter_expr,
                )

                for result in results:
                    result["node_type"] = node_type
                    result["summary"] = result.get("summary", "")
                    all_results.append(result)

            except Exception as e:
                logger.warning(f"Search failed in {collection}: {e}")

        # 3. 按距离排序并获取详细信息
        all_results.sort(key=lambda x: x["distance"], reverse=True)
        detailed_results = []
        for result in all_results[:top_k]:
            node_info = await self.graph_db.get_node_by_id(result["node_id"])
            if node_info:
                detailed_results.append({
                    "node_id": result["node_id"],
                    "name": result["name"],
                    "type": result["node_type"],
                    "distance": result["distance"],
                    "summary": result.get("summary", ""),
                    "details": node_info.get("node", {}),
                })

        return json.dumps({
            "query": query,
            "results": detailed_results,
        }, indent=2, ensure_ascii=False)

    async def search_semantic_nodes(
        self,
        repo_id: str,
        query: str,
        node_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> str:
        """根据关键字语义查询语义节点 (MODULE, WORKFLOW).

        只使用 summary 进行语义匹配，但会同时返回 detail 字段。

        Args:
            repo_id: 仓库ID
            query: 查询关键字
            node_types: 节点类型列表，可选值为 ["Module", "Workflow"]，默认为全部
            top_k: 返回结果数量

        Returns:
            JSON 字符串，包含查询结果（包含 detail 字段）
        """
        # 1. 将查询向量化
        try:
            embeddings = await self.llm_service.generate_embeddings([query])
            if not embeddings:
                return "Failed to generate embedding for query."
            query_vector = embeddings[0]
        except Exception as e:
            return f"Embedding generation failed: {e}"

        # 2. 搜索 semantic_summary_collection
        all_results = []

        # 默认搜索所有语义节点类型
        if node_types is None:
            node_types = ["Module", "Workflow"]

        for node_type in node_types:
            if node_type not in ["Module", "Workflow"]:
                logger.warning(f"Invalid semantic node type: {node_type}")
                continue

            try:
                filter_expr = f'repo == "{repo_id}" && type == "{node_type}"'

                results = await self.vector_db.search(
                    collection_name="semantic_summary_collection",
                    query_vector=query_vector,
                    top_k=top_k,
                    filter_expr=filter_expr,
                )

                for result in results:
                    result["node_type"] = node_type
                    all_results.append(result)

            except Exception as e:
                logger.warning(f"Search failed for {node_type}: {e}")

        # 3. 按距离排序并构建结果（包含 detail）
        all_results.sort(key=lambda x: x["distance"], reverse=True)
        detailed_results = []
        for result in all_results[:top_k]:
            detailed_results.append({
                "node_id": result["node_id"],
                "name": result["name"],
                "type": result["node_type"],
                "distance": result["distance"],
                "summary": result.get("summary", ""),
                "detail": result.get("detail", ""),  # 返回 detail 字段
            })

        return json.dumps({
            "query": query,
            "results": detailed_results,
        }, indent=2, ensure_ascii=False)

    async def get_modules(self, repo_id: str) -> str:
        """获取项目的 Module 列表."""
        results = await self.graph_db.get_modules(repo_id)

        modules = []
        for result in results:
            modules.append({
                "id": result["id"],
                "name": result["name"],
                "description": result.get("description", ""),
                "summary": result.get("summary", ""),
            })

        return json.dumps({
            "repo_id": repo_id,
            "modules": modules,
        }, indent=2, ensure_ascii=False)

    async def get_module_workflows(self, repo_id: str, module_id: str) -> str:
        """获取 Module 对应的 Workflow 列表."""
        results = await self.graph_db.get_module_workflows(module_id)

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

    async def get_node_dependencies(
        self,
        node_id: str,
        depth: int = 1,
    ) -> str:
        """获取节点的依赖关系图."""
        dependencies = await self.graph_db.get_node_dependencies(node_id, depth)

        return json.dumps({
            "node_id": node_id,
            "depth": depth,
            "dependencies": dependencies,
        }, indent=2, ensure_ascii=False)

    async def batch_download_flowcharts(
        self,
        method_ids: List[str],
    ) -> str:
        """根据 method 节点 ID 列表批量下载流程图图片.

        Args:
            method_ids: Method 节点 ID 列表

        Returns:
            JSON 字符串，包含每个 method 的图片数据（base64 编码）
        """
        if not method_ids:
            return json.dumps({
                "success": False,
                "error": "No method IDs provided",
                "images": [],
            }, indent=2, ensure_ascii=False)

        settings = get_settings()
        image_dir = Path(settings.flowchart_image_dir)

        # 批量查询 method 节点的 image 属性
        method_images = []
        for method_id in method_ids:
            try:
                # 查询节点信息
                node_info = await self.graph_db.get_node_by_id(method_id)
                if not node_info:
                    method_images.append({
                        "method_id": method_id,
                        "success": False,
                        "error": "Node not found",
                    })
                    continue

                node = node_info.get("node", {})
                image_id = node.get("image", "")
                repo_id = node.get("repo_id", "")

                if not image_id:
                    method_images.append({
                        "method_id": method_id,
                        "success": False,
                        "error": "No flowchart image available",
                    })
                    continue

                # 构建图片路径
                image_path = image_dir / repo_id / "image" / f"{image_id}.png"

                if not image_path.exists():
                    method_images.append({
                        "method_id": method_id,
                        "success": False,
                        "error": f"Image file not found: {image_path}",
                    })
                    continue

                # 读取图片并编码为 base64
                with open(image_path, "rb") as f:
                    image_data = f.read()
                    image_base64 = base64.b64encode(image_data).decode("utf-8")

                method_images.append({
                    "method_id": method_id,
                    "method_name": node.get("name", ""),
                    "success": True,
                    "image_id": image_id,
                    "image_data": image_base64,
                    "image_format": "png",
                })

            except Exception as e:
                logger.error(f"Failed to download flowchart for {method_id}: {e}")
                method_images.append({
                    "method_id": method_id,
                    "success": False,
                    "error": str(e),
                })

        success_count = sum(1 for img in method_images if img.get("success"))

        return json.dumps({
            "success": success_count > 0,
            "total": len(method_ids),
            "success_count": success_count,
            "failed_count": len(method_ids) - success_count,
            "images": method_images,
        }, indent=2, ensure_ascii=False)
