"""Neo4j 图数据库客户端."""

import logging
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import Neo4jError

from app.config import get_settings
from app.infrastructure.db.base_client import GraphDatabaseClient

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

    async def execute_query(
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
        result = await self.execute_query(
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
        result = await self.execute_query(
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

        result = await self.execute_query(query, params, database)
        return result[0]["created"] > 0 if result else False

    async def delete_repo_data(self, repo_name: str, database: Optional[str] = None) -> int:
        """删除仓库相关数据.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            删除的节点数量
        """
        query = """
        MATCH (n)
        WHERE n.repo = $repo_name OR n.name = $repo_name
        OPTIONAL MATCH (n)-[r]-()
        DELETE r, n
        RETURN count(DISTINCT n) as deleted
        """
        result = await self.execute_query(
            query,
            {"repo_name": repo_name},
            database,
        )
        deleted = result[0]["deleted"] if result else 0
        logger.info(f"Deleted {deleted} nodes for repo: {repo_name}")
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
        result = await self.execute_query(
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

        return await self.execute_query(
            query,
            {"node_id": node_id},
            database,
        )


# 全局客户端实例
_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """获取Neo4j客户端实例."""
    global _neo4j_client
    if _neo4j_client is None:
        _neo4j_client = Neo4jClient()
    return _neo4j_client
