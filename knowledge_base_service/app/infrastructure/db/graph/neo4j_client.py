"""Neo4j 图数据库客户端."""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import Neo4jError

from app.config import get_settings
from app.infrastructure.db.graph.base_client import GraphDatabaseClient

logger = logging.getLogger(__name__)


class Neo4jClient(GraphDatabaseClient):
    """Neo4j 异步客户端封装."""

    _instance: Optional["Neo4jClient"] = None
    _driver: Optional[AsyncDriver] = None

    def __new__(cls) -> "Neo4jClient":
        """单例模式."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self) -> None:
        """建立数据库连接."""
        if self._driver is None:
            settings = get_settings()
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            # 验证连接
            await self._driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {settings.neo4j_uri}")

    async def close(self) -> None:
        """关闭数据库连接."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    async def _execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """执行Cypher查询.

        Args:
            query: Cypher查询语句
            parameters: 查询参数
            database: 目标数据库名称

        Returns:
            查询结果列表
        """
        if self._driver is None:
            await self.connect()

        parameters = parameters or {}
        database = database or "neo4j"

        try:
            async with self._driver.session(database=database) as session:
                result = await session.run(query, **parameters)
                records = await result.data()
                return records
        except Neo4jError as e:
            logger.error(f"Neo4j query failed: {e}")
            raise

    async def create_node(
        self,
        label: str,
        properties: Dict[str, Any],
        database: Optional[str] = None,
    ) -> str:
        """创建节点.

        Args:
            label: 节点标签
            properties: 节点属性
            database: 目标数据库名称

        Returns:
            创建节点的ID
        """
        query = f"""
        CREATE (n:{label} $properties)
        RETURN n.id as node_id
        """
        result = await self._execute_query(
            query,
            {"properties": properties},
            database,
        )
        return result[0]["node_id"] if result else ""

    async def merge_node(
        self,
        label: str,
        key_property: str,
        key_value: str,
        properties: Dict[str, Any],
        database: Optional[str] = None,
    ) -> str:
        """合并节点（存在则更新，不存在则创建）.

        Args:
            label: 节点标签
            key_property: 用于匹配的关键属性名
            key_value: 关键属性值
            properties: 节点属性
            database: 目标数据库名称

        Returns:
            节点ID
        """
        query = f"""
        MERGE (n:{label} {{{key_property}: $key_value}})
        SET n += $properties
        RETURN n.id as node_id
        """
        result = await self._execute_query(
            query,
            {
                "key_value": key_value,
                "properties": properties,
            },
            database,
        )
        return result[0]["node_id"] if result else ""

    async def create_relationship(
        self,
        from_label: str,
        from_key: str,
        from_value: str,
        to_label: str,
        to_key: str,
        to_value: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> bool:
        """创建关系.

        Args:
            from_label: 起始节点标签
            from_key: 起始节点匹配属性
            from_value: 起始节点匹配值
            to_label: 目标节点标签
            to_key: 目标节点匹配属性
            to_value: 目标节点匹配值
            rel_type: 关系类型
            properties: 关系属性
            database: 目标数据库名称

        Returns:
            是否成功创建
        """
        props_str = ""
        params: Dict[str, Any] = {
            "from_value": from_value,
            "to_value": to_value,
        }

        if properties:
            props_str = ", r: $rel_props"
            params["rel_props"] = properties

        query = """
        MATCH (from:%s {%s: $from_value})
        MATCH (to:%s {%s: $to_value})
        CREATE (from)-[r:%s%s]->(to)
        RETURN count(r) as created
        """ % (from_label, from_key, to_label, to_key, rel_type, props_str)

        result = await self._execute_query(query, params, database)
        return result[0]["created"] > 0 if result else False

    async def batch_merge_nodes(
        self,
        label: str,
        nodes: List[Dict[str, Any]],
        database: Optional[str] = None,
    ) -> int:
        """批量合并节点（使用UNWIND优化）.

        将多个同类型节点的MERGE操作合并为一次数据库查询，
        大幅减少网络往返，提升写入性能。

        Args:
            label: 节点标签
            nodes: 节点属性列表，每项为 {"id": str, "properties": dict}
            database: 目标数据库名称

        Returns:
            成功合并的节点数量
        """
        if not nodes:
            return 0

        BATCH_SIZE = 200
        total = 0

        for i in range(0, len(nodes), BATCH_SIZE):
            batch = nodes[i : i + BATCH_SIZE]
            query = f"""
            UNWIND $nodes as node
            MERGE (n:{label} {{id: node.id}})
            SET n += node.properties
            RETURN count(n) as count
            """
            try:
                result = await self._execute_query(
                    query,
                    {"nodes": batch},
                    database,
                )
                total += result[0]["count"] if result else 0
            except Neo4jError as e:
                logger.error(f"Batch merge {label} failed: {e}")
                raise

        return total

    async def batch_create_relationships(
        self,
        rel_type: str,
        relationships: List[Dict[str, str]],
        from_label: Optional[str] = None,
        to_label: Optional[str] = None,
        database: Optional[str] = None,
    ) -> int:
        """批量创建关系（使用UNWIND优化）.

        将多个同类型关系的CREATE操作合并为一次数据库查询。
        当 from_label/to_label 指定时，MATCH 语句会包含标签以利用索引。

        Args:
            rel_type: 关系类型
            relationships: 关系列表，每项为 {"from_id": str, "to_id": str}
            from_label: 起始节点标签（可选，用于优化MATCH）
            to_label: 目标节点标签（可选，用于优化MATCH）
            database: 目标数据库名称

        Returns:
            成功创建的关系数量
        """
        if not relationships:
            return 0

        BATCH_SIZE = 500
        total = 0

        # 构建带标签的 MATCH 模式（如果提供了标签）
        from_pattern = f"(from:{from_label} {{id: rel.from_id}})" if from_label else "(from {id: rel.from_id})"
        to_pattern = f"(to:{to_label} {{id: rel.to_id}})" if to_label else "(to {id: rel.to_id})"

        for i in range(0, len(relationships), BATCH_SIZE):
            batch = relationships[i : i + BATCH_SIZE]
            query = f"""
            UNWIND $relationships as rel
            MATCH {from_pattern}
            MATCH {to_pattern}
            CREATE (from)-[r:{rel_type}]->(to)
            RETURN count(r) as count
            """
            try:
                result = await self._execute_query(
                    query,
                    {"relationships": batch},
                    database,
                )
                total += result[0]["count"] if result else 0
            except Neo4jError as e:
                logger.error(f"Batch create {rel_type} relationships failed: {e}")
                raise

        return total

    async def delete_repo_data(self, repo_id: str, database: Optional[str] = None) -> int:
        """删除仓库相关数据.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            删除的节点数量
        """
        query = """
        MATCH (n)
        WHERE n.repoId = $repo_id
        OPTIONAL MATCH (n)-[r]-()
        DELETE r, n
        RETURN count(DISTINCT n) as deleted
        """
        result = await self._execute_query(
            query,
            {"repo_id": repo_id},
            database,
        )
        deleted = result[0]["deleted"] if result else 0
        logger.info(f"Deleted {deleted} nodes for repo: {repo_id}")
        return deleted

    async def get_node_by_id(
        self,
        node_id: str,
        database: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """根据ID获取节点.

        Args:
            node_id: 节点ID
            database: 目标数据库名称

        Returns:
            节点数据或None
        """
        query = """
        MATCH (n {id: $node_id})
        RETURN n as node, labels(n) as labels
        """
        result = await self._execute_query(
            query,
            {"node_id": node_id},
            database,
        )
        return result[0] if result else None

    async def get_node_relationships(
        self,
        node_id: str,
        direction: str = "both",  # "out", "in", "both"
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取节点的关系.

        Args:
            node_id: 节点ID
            direction: 关系方向
            database: 目标数据库名称

        Returns:
            关系列表
        """
        if direction == "out":
            query = """
            MATCH (n {id: $node_id})-[r]->(m)
            RETURN r as relationship, m as target, type(r) as rel_type
            """
        elif direction == "in":
            query = """
            MATCH (n {id: $node_id})<-[r]-(m)
            RETURN r as relationship, m as source, type(r) as rel_type
            """
        else:
            query = """
            MATCH (n {id: $node_id})-[r]-(m)
            RETURN r as relationship, m as related, type(r) as rel_type
            """

        return await self._execute_query(
            query,
            {"node_id": node_id},
            database,
        )

    async def get_code_files(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定仓库的所有代码文件节点.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 id, path, code, suffix, language 等字段
        """
        query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.fileType = 'code'
        RETURN f.id as id, f.path as path, f.code as code, f.suffix as suffix
        """
        result = await self._execute_query(query, {"repo_id": repo_id}, database)

        # 添加 language 字段
        language_map = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cc": "cpp",
        }

        for file_node in result:
            suffix = file_node.get("suffix", "").lower()
            file_node["language"] = language_map.get(suffix, "")

        return result

    async def get_all_nodes(
        self,
        repo_id: str,
        node_types: List[str],
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定仓库的所有指定类型节点.

        Args:
            repo_id: 仓库ID
            node_types: 节点类型列表，如 ["File", "Class", "Method"]
            database: 目标数据库名称

        Returns:
            节点列表，每项包含 id, name, type, file_path, summary, language 等字段
        """
        if not node_types:
            node_types = ["File", "Class", "Method"]

        results = []
        for node_type in node_types:
            query = """
            MATCH (n:%s)
            WHERE n.repoId = $repo_id
            RETURN n.id as id, n.name as name, labels(n) as types,
                   coalesce(n.filePath, n.path) as file_path,
                   n.summary as summary, n.language as language,
                   n.description as description
            ORDER BY n.name
            """ % node_type

            type_results = await self._execute_query(
                query, {"repo_id": repo_id}, database
            )
            results.extend(type_results)

        return results

    async def get_methods_with_calls(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Method 节点及其 CALL 关系.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 code, docstring, language, name, summary, callee_ids 等字段
        """
        query = """
        MATCH (m:Method)
        WHERE m.repoId = $repo_id
        OPTIONAL MATCH (m)-[:CALL]->(callee:Method)
        RETURN m.id as id, m.code as code, m.docstring as docstring,
               m.language as language, m.name as name, m.summary as summary,
               collect(DISTINCT callee.id) as callee_ids
        """
        return await self._execute_query(query, {"repo_id": repo_id}, database)

    async def get_classes_with_methods(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Class 节点及其包含的 Method summaries.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Class 节点列表，包含 code, docstring, language, name, summary, method_summaries 等字段
        """
        query = """
        MATCH (c:Class)
        WHERE c.repoId = $repo_id
        OPTIONAL MATCH (c)-[:CONTAIN]->(m:Method)
        RETURN c.id as id, c.code as code, c.docstring as docstring,
               c.language as language, c.name as name, c.summary as summary,
               collect(DISTINCT m.summary) as method_summaries
        """
        return await self._execute_query(query, {"repo_id": repo_id}, database)

    async def get_files_for_summary(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 File 节点及其包含的 Class/Method summaries.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 code, file_type, suffix, name, summary, class_summaries, method_summaries 等字段
        """
        query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id
        OPTIONAL MATCH (f)-[:CONTAIN]->(c:Class)
        OPTIONAL MATCH (f)-[:CONTAIN]->(m:Method)
        RETURN f.id as id, f.code as code, f.fileType as file_type,
               f.suffix as suffix, f.name as name, f.summary as summary,
               collect(DISTINCT c.summary) as class_summaries,
               collect(DISTINCT m.summary) as method_summaries
        """
        return await self._execute_query(query, {"repo_id": repo_id}, database)

    async def update_node_summary(
        self,
        label: str,
        node_id: str,
        summary: str,
        database: Optional[str] = None,
    ) -> bool:
        """更新节点的 summary 属性.

        Args:
            label: 节点标签
            node_id: 节点ID
            summary: 摘要内容
            database: 目标数据库名称

        Returns:
            是否成功更新
        """
        query = f"""
        MATCH (n:{label} {{id: $node_id}})
        SET n.summary = $summary
        """
        try:
            await self._execute_query(query, {"node_id": node_id, "summary": summary}, database)
            return True
        except Exception as e:
            logger.warning(f"Failed to update summary for {label} {node_id}: {e}")
            return False

    async def update_node_summaries_batch(
        self,
        label: str,
        updates: List[Tuple[str, str]],
        database: Optional[str] = None,
    ) -> int:
        """批量更新节点的 summary 属性.

        使用 UNWIND 语句优化批量更新性能，减少网络往返。

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, summary) 元组
            database: 目标数据库名称

        Returns:
            成功更新的节点数量
        """
        if not updates:
            return 0

        # 转换为字典列表供 UNWIND 使用
        updates_dict = [
            {"node_id": node_id, "summary": summary}
            for node_id, summary in updates
        ]

        query = f"""
        UNWIND $updates as update
        MATCH (n:{label} {{id: update.node_id}})
        SET n.summary = update.summary
        RETURN count(n) as updated_count
        """

        try:
            result = await self._execute_query(
                query, {"updates": updates_dict}, database
            )
            updated_count = result[0]["updated_count"] if result else 0
            return updated_count
        except Exception as e:
            logger.warning(f"Failed to batch update summaries for {label}: {e}")
            return 0

    async def find_nodes_by_file_path(
        self,
        keyword: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据文件路径关键字查找 Class 或 Method 节点.

        Args:
            keyword: 文件路径关键字
            database: 目标数据库名称

        Returns:
            节点列表，包含 node_id 和 labels 字段
        """
        query = """
        MATCH (n)
        WHERE (n:Class OR n:Method) AND n.filePath CONTAINS $keyword
        RETURN n.id as node_id, labels(n) as labels
        LIMIT 10
        """
        return await self._execute_query(query, {"keyword": keyword}, database)

    async def get_nodes_with_summary(
        self,
        repo_id: str,
        node_type: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定类型的所有包含 summary 的节点.

        Args:
            repo_id: 仓库ID
            node_type: 节点类型 (File, Class, Method, Module, Workflow)
            database: 目标数据库名称

        Returns:
            节点列表，包含 id, name, summary 等字段
        """
        if node_type == "File":
            query = """
            MATCH (f:File)
            WHERE f.repoId = $repo_id AND f.summary IS NOT NULL
            RETURN f.id as id, f.name as name, f.summary as summary, f.path as path
            """
        elif node_type == "Class":
            query = """
            MATCH (c:Class)
            WHERE c.repoId = $repo_id AND c.summary IS NOT NULL
            RETURN c.id as id, c.name as name, c.summary as summary
            """
        elif node_type == "Method":
            query = """
            MATCH (m:Method)
            WHERE m.repoId = $repo_id AND m.summary IS NOT NULL
            RETURN m.id as id, m.name as name, m.summary as summary
            """
        elif node_type == "Module":
            query = """
            MATCH (mod:Module)
            WHERE mod.repoId = $repo_id AND mod.summary IS NOT NULL
            RETURN mod.id as id, mod.name as name, mod.summary as summary
            """
        elif node_type == "Workflow":
            query = """
            MATCH (w:Workflow)
            WHERE w.repoId = $repo_id AND w.summary IS NOT NULL
            RETURN w.id as id, w.name as name, w.summary as summary
            """
        else:
            return []

        return await self._execute_query(query, {"repo_id": repo_id}, database)

    async def count_nodes_with_summary(
        self,
        repo_id: str,
        node_type: str,
        database: Optional[str] = None,
    ) -> int:
        """获取指定类型的包含 summary 的节点总数.

        Args:
            repo_id: 仓库ID
            node_type: 节点类型 (File, Class, Method, Module, Workflow)
            database: 目标数据库名称

        Returns:
            节点总数
        """
        if node_type not in ["File", "Class", "Method", "Module", "Workflow"]:
            return 0

        query = f"""
        MATCH (n:{node_type})
        WHERE n.repoId = $repo_id AND n.summary IS NOT NULL
        RETURN count(n) as total
        """

        result = await self._execute_query(
            query, {"repo_id": repo_id}, database
        )
        return result[0]["total"] if result else 0

    async def get_nodes_with_summary_paginated(
        self,
        repo_id: str,
        node_type: str,
        skip: int = 0,
        limit: int = 100,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """分页获取指定类型的包含 summary 的节点.

        Args:
            repo_id: 仓库ID
            node_type: 节点类型 (File, Class, Method, Module, Workflow)
            skip: 跳过的记录数
            limit: 返回的最大记录数
            database: 目标数据库名称

        Returns:
            节点列表，包含 id, name, summary 等字段
        """
        params = {"repo_id": repo_id, "skip": skip, "limit": limit}

        if node_type == "File":
            query = """
            MATCH (f:File)
            WHERE f.repoId = $repo_id AND f.summary IS NOT NULL
            RETURN f.id as id, f.name as name, f.summary as summary, f.path as path
            ORDER BY f.id
            SKIP $skip LIMIT $limit
            """
        elif node_type == "Class":
            query = """
            MATCH (c:Class)
            WHERE c.repoId = $repo_id AND c.summary IS NOT NULL
            RETURN c.id as id, c.name as name, c.summary as summary
            ORDER BY c.id
            SKIP $skip LIMIT $limit
            """
        elif node_type == "Method":
            query = """
            MATCH (m:Method)
            WHERE m.repoId = $repo_id AND m.summary IS NOT NULL
            RETURN m.id as id, m.name as name, m.summary as summary
            ORDER BY m.id
            SKIP $skip LIMIT $limit
            """
        elif node_type == "Module":
            query = """
            MATCH (mod:Module)
            WHERE mod.repoId = $repo_id AND mod.summary IS NOT NULL
            RETURN mod.id as id, mod.name as name, mod.summary as summary, mod.detail as detail
            ORDER BY mod.id
            SKIP $skip LIMIT $limit
            """
        elif node_type == "Workflow":
            query = """
            MATCH (w:Workflow)
            WHERE w.repoId = $repo_id AND w.summary IS NOT NULL
            RETURN w.id as id, w.name as name, w.summary as summary, w.detail as detail
            ORDER BY w.id
            SKIP $skip LIMIT $limit
            """
        else:
            return []

        return await self._execute_query(query, params, database)

    async def update_node_embedding_id(
        self,
        label: str,
        node_id: str,
        embedding_id: str,
        database: Optional[str] = None,
    ) -> bool:
        """更新节点的 embeddingId 属性.

        Args:
            label: 节点标签
            node_id: 节点ID
            embedding_id: 向量ID
            database: 目标数据库名称

        Returns:
            是否成功更新
        """
        query = f"""
        MATCH (n:{label} {{id: $id}})
        SET n.embeddingId = $embedding_id
        """
        try:
            await self._execute_query(query, {"id": node_id, "embedding_id": embedding_id}, database)
            return True
        except Exception as e:
            logger.warning(f"Failed to update embeddingId for {label} {node_id}: {e}")
            return False

    async def update_node_embedding_ids_batch(
        self,
        label: str,
        updates: List[Tuple[str, str]],
        database: Optional[str] = None,
    ) -> int:
        """批量更新节点的 embeddingId 属性.

        使用 UNWIND 语句优化批量更新性能，减少网络往返。

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, embedding_id) 元组
            database: 目标数据库名称

        Returns:
            成功更新的节点数量
        """
        if not updates:
            return 0

        # 转换为字典列表供 UNWIND 使用
        updates_dict = [
            {"node_id": node_id, "embedding_id": embedding_id}
            for node_id, embedding_id in updates
        ]

        query = f"""
        UNWIND $updates as update
        MATCH (n:{label} {{id: update.node_id}})
        SET n.embeddingId = update.embedding_id
        RETURN count(n) as updated_count
        """

        try:
            result = await self._execute_query(
                query, {"updates": updates_dict}, database
            )
            updated_count = result[0]["updated_count"] if result else 0
            return updated_count
        except Exception as e:
            logger.warning(f"Failed to batch update embeddingIds for {label}: {e}")
            return 0

    async def get_project_structure(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取项目目录结构.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            目录和文件列表，每项包含 id, path, type, labels, summary 字段
        """
        query = """
        MATCH (r:Repository {repoId: $repo_id})-[:CONTAIN*]->(n)
        WHERE n:Directory OR n:File
        RETURN n.id as id, n.path as path, n.type as type, labels(n) as labels, n.summary as summary
        ORDER BY path
        """
        return await self._execute_query(query, {"repo_id": repo_id}, database)

    async def get_modules(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取项目的 Module 列表.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Module 列表，每项包含 id, name, description, summary 字段
        """
        query = """
        MATCH (m:Module)
        WHERE m.repoId = $repo_id
        RETURN m.id as id, m.name as name, m.description as description, m.summary as summary
        """
        return await self._execute_query(
            query,
            {"repo_id": repo_id},
            database,
        )

    async def get_related_nodes(
        self,
        node_id: str,
        rel_type: str,
        direction: str = "out",
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取与指定节点具有特定关系的所有节点.

        Args:
            node_id: 节点ID
            rel_type: 关系类型，如 "BELONG_TO", "CONTAIN", "CALL"
            direction: 关系方向 ("out", "in", "both")
            database: 目标数据库名称

        Returns:
            关联节点列表，每项包含 id, name, labels, summary, description 等字段
        """
        if direction == "out":
            query = """
            MATCH (n {id: $node_id})-[r:%s]->(m)
            RETURN m.id as id, m.name as name, labels(m) as labels,
                   m.summary as summary, m.description as description
            """ % rel_type
        elif direction == "in":
            query = """
            MATCH (n {id: $node_id})<-[r:%s]-(m)
            RETURN m.id as id, m.name as name, labels(m) as labels,
                   m.summary as summary, m.description as description
            """ % rel_type
        else:
            query = """
            MATCH (n {id: $node_id})-[r:%s]-(m)
            RETURN m.id as id, m.name as name, labels(m) as labels,
                   m.summary as summary, m.description as description
            """ % rel_type

        return await self._execute_query(query, {"node_id": node_id}, database)

    async def get_node_dependencies(
        self,
        node_id: str,
        depth: int = 1,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取节点的依赖关系图.

        Args:
            node_id: 节点ID
            depth: 搜索深度
            database: 目标数据库名称

        Returns:
            依赖关系列表，每项包含 source, target, relationships, distance 字段
        """
        query = """
        MATCH path = (n {id: $node_id})-[r*1..$depth]-(m)
        WHERE n <> m
        RETURN n.id as source_id, labels(n) as source_labels,
               m.id as target_id, labels(m) as target_labels,
               [rel in r | type(rel)] as rel_types,
               length(path) as distance
        LIMIT 100
        """
        results = await self._execute_query(
            query,
            {"node_id": node_id, "depth": depth},
            database,
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

        return dependencies

    async def get_methods_by_languages(
        self,
        repo_id: str,
        languages: List[str],
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定仓库中指定语言的所有Method节点.

        Args:
            repo_id: 仓库ID
            languages: 语言列表，如 ["c", "cpp"]
            database: 目标数据库名称

        Returns:
            Method节点列表，包含 id, name, code, language, file_path 等字段
        """
        query = """
        MATCH (m:Method)
        WHERE m.repoId = $repo_id AND m.language IN $languages
        RETURN m.id as id, m.name as name, m.code as code,
               m.language as language, m.filePath as file_path, m.image as image
        """
        return await self._execute_query(
            query,
            {"repo_id": repo_id, "languages": languages},
            database,
        )

    async def update_method_image(
        self,
        method_id: str,
        image_id: str,
        database: Optional[str] = None,
    ) -> bool:
        """更新Method节点的image属性.

        Args:
            method_id: 方法节点ID
            image_id: 图片ID
            database: 目标数据库名称

        Returns:
            是否成功更新
        """
        query = """
        MATCH (m:Method {id: $method_id})
        SET m.image = $image_id
        """
        try:
            await self._execute_query(
                query,
                {"method_id": method_id, "image_id": image_id},
                database,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to update image for Method {method_id}: {e}")
            return False

    async def get_code_files_with_summary(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定仓库的所有代码文件节点及其摘要.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 id, path, name, suffix, summary 等字段
        """
        query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.fileType = 'code'
        RETURN f.id as id, f.path as path, f.name as name,
               f.suffix as suffix, f.summary as summary
        """
        return await self._execute_query(
            query, {"repo_id": repo_id}, database
        )

    async def get_file_use_dependencies(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取文件之间的USE依赖关系.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            依赖关系列表，每项包含 source, target, weight 字段
        """
        query = """
        MATCH (f1:File)-[r:USE]->(f2:File)
        WHERE f1.repoId = $repo_id AND f2.repoId = $repo_id
        RETURN f1.id as source, f2.id as target, count(*) as weight
        """
        return await self._execute_query(
            query, {"repo_id": repo_id}, database
        )

    async def get_file_call_dependencies(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取文件之间的CALL依赖关系（通过方法调用）.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            依赖关系列表，每项包含 source, target, weight 字段
        """
        query = """
        MATCH (m1:Method)-[:CALL]->(m2:Method)
        WHERE m1.repoId = $repo_id AND m2.repoId = $repo_id
        MATCH (f1:File), (f2:File)
        WHERE f1.repoId = $repo_id AND f2.repoId = $repo_id
          AND f1.path = m1.filePath AND f2.path = m2.filePath
          AND f1 <> f2
        RETURN f1.id as source, f2.id as target, count(*) as weight
        """
        return await self._execute_query(
            query, {"repo_id": repo_id}, database
        )

    async def get_classes_by_file_path(
        self,
        file_path: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据文件路径获取该文件中的所有类.

        Args:
            file_path: 文件路径
            database: 目标数据库名称

        Returns:
            Class 节点列表，每项包含 name, summary 字段
        """
        query = """
        MATCH (c:Class)
        WHERE c.filePath = $file_path
        RETURN c.name as name, c.summary as summary
        ORDER BY c.name
        """
        return await self._execute_query(
            query, {"file_path": file_path}, database
        )

    async def get_methods_by_file_path(
        self,
        file_path: str,
        limit: int = 5,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据文件路径获取该文件中的关键方法（按被调用次数排序）.

        Args:
            file_path: 文件路径
            limit: 返回的最大方法数量
            database: 目标数据库名称

        Returns:
            Method 节点列表，每项包含 name, summary, callee_count 字段
        """
        query = """
        MATCH (m:Method)
        WHERE m.filePath = $file_path
        OPTIONAL MATCH (m)-[:CALL]->(callee:Method)
        RETURN m.name as name, m.summary as summary,
               count(callee) as callee_count
        ORDER BY callee_count DESC
        LIMIT $limit
        """
        return await self._execute_query(
            query, {"file_path": file_path, "limit": limit}, database
        )

    async def get_method_call_chains_by_file_paths(
        self,
        file_paths: List[str],
        limit: int = 50,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定文件路径列表中的方法调用链.

        Args:
            file_paths: 文件路径列表
            limit: 返回的最大记录数
            database: 目标数据库名称

        Returns:
            调用链列表，每项包含 method_name, file_path, callees 字段
        """
        query = """
        MATCH (m:Method)
        WHERE m.filePath IN $file_paths
        OPTIONAL MATCH (m)-[:CALL]->(callee:Method)
        WHERE callee.filePath IN $file_paths
        RETURN m.name as method_name, m.filePath as file_path,
               collect(DISTINCT callee.name) as callees
        LIMIT $limit
        """
        return await self._execute_query(
            query, {"file_paths": file_paths, "limit": limit}, database
        )

    async def get_file_contents(
        self,
        repo_id: str,
        file_paths: List[str],
        database: Optional[str] = None,
    ) -> Dict[str, str]:
        """获取指定文件的代码内容.

        Args:
            repo_id: 仓库ID
            file_paths: 文件路径列表
            database: 目标数据库名称

        Returns:
            文件路径到代码内容的映射
        """
        query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.path IN $file_paths
        RETURN f.path as path, f.code as code
        """

        try:
            results = await self._execute_query(
                query,
                {"repo_id": repo_id, "file_paths": file_paths},
                database,
            )

            return {row["path"]: row.get("code", "") for row in results}
        except Exception as e:
            logger.error(f"Failed to get file contents: {e}")
            return {}

    async def search_nodes_by_name(
        self,
        repo_id: str,
        name: str,
        node_types: List[str],
        fuzzy: bool = True,
        top_k: int = 10,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据节点名称搜索代码节点."""
        if fuzzy:
            query = """
            MATCH (n)
            WHERE n.repoId = $repo_id
              AND ANY(label IN labels(n) WHERE label IN $node_types)
              AND n.name CONTAINS $name
            RETURN n.id as id, n.name as name, labels(n) as types,
                   coalesce(n.filePath, n.path) as file_path,
                   n.summary as summary, n.docstring as docstring
            LIMIT $top_k
            """
        else:
            query = """
            MATCH (n)
            WHERE n.repoId = $repo_id
              AND ANY(label IN labels(n) WHERE label IN $node_types)
              AND n.name = $name
            RETURN n.id as id, n.name as name, labels(n) as types,
                   coalesce(n.filePath, n.path) as file_path,
                   n.summary as summary, n.docstring as docstring
            LIMIT $top_k
            """

        return await self._execute_query(
            query,
            {"repo_id": repo_id, "name": name, "node_types": node_types, "top_k": top_k},
            database,
        )

    async def batch_get_node_details(
        self,
        repo_id: str,
        node_ids: List[str],
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """批量根据节点 ID 获取节点详情."""
        query = """
        MATCH (n)
        WHERE n.repoId = $repo_id AND n.id IN $node_ids
        RETURN n.id as id, n.name as name, labels(n) as types,
               coalesce(n.filePath, n.path) as file_path,
               n.code as code, n.summary as summary,
               n.docstring as docstring, n.language as language,
               n.type as node_type, n.suffix as suffix
        """

        return await self._execute_query(
            query,
            {"repo_id": repo_id, "node_ids": node_ids},
            database,
        )

    async def get_repository_stats(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取仓库节点的统计信息.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            包含 name, path, totalFiles, totalCodeFiles, totalLines, totalSize, languages, languageDistribution 等字段的字典，或 None
        """
        query = """
        MATCH (r:Repository {repoId: $repo_id})
        RETURN r.name as name, r.path as path,
               r.totalFiles as total_files, r.totalCodeFiles as total_code_files,
               r.totalLines as total_lines, r.totalSize as total_size,
               r.languages as languages, r.languageDistribution as language_distribution
        """
        results = await self._execute_query(query, {"repo_id": repo_id}, database)
        if not results:
            return None
        result = results[0]
        lang_dist = result.get("language_distribution")
        if isinstance(lang_dist, str) and lang_dist:
            try:
                result["language_distribution"] = json.loads(lang_dist)
            except json.JSONDecodeError:
                result["language_distribution"] = {}
        elif lang_dist is None:
            result["language_distribution"] = {}
        return result

    async def get_repo_node_counts(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> Dict[str, int]:
        """获取仓库中目录、类、方法的数量统计.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            包含 directory_count, class_count, method_count 的字典
        """
        query = """
        MATCH (r:Repository {repoId: $repo_id})
        OPTIONAL MATCH (d:Directory {repoId: $repo_id})
        OPTIONAL MATCH (c:Class {repoId: $repo_id})
        OPTIONAL MATCH (m:Method {repoId: $repo_id})
        RETURN count(DISTINCT d) as directory_count,
               count(DISTINCT c) as class_count,
               count(DISTINCT m) as method_count
        """
        results = await self._execute_query(query, {"repo_id": repo_id}, database)
        if results:
            return {
                "directory_count": results[0].get("directory_count", 0),
                "class_count": results[0].get("class_count", 0),
                "method_count": results[0].get("method_count", 0),
            }
        return {"directory_count": 0, "class_count": 0, "method_count": 0}


# 全局客户端实例
_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """获取Neo4j客户端实例."""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient()
    return _neo4j_client
