"""数据库模块.

提供图数据库和向量数据库的抽象接口，支持通过配置切换不同的数据库实现。
"""

from typing import Optional

from app.config import get_settings
from app.infrastructure.db.base_client import (
    GraphDatabaseClient,
    VectorDatabaseClient,
)
from app.infrastructure.db.milvus_client import MilvusClient, get_milvus_client
from app.infrastructure.db.neo4j_client import Neo4jClient, get_neo4j_client

__all__ = [
    # 抽象基类
    "GraphDatabaseClient",
    "VectorDatabaseClient",
    # 图数据库实现
    "Neo4jClient",
    "get_neo4j_client",
    # 向量数据库实现
    "MilvusClient",
    "get_milvus_client",
    # 工厂函数（推荐用于阶段处理器）
    "get_graph_db_client",
    "get_vector_db_client",
]

# 缓存的客户端实例
_graph_db_client: Optional[GraphDatabaseClient] = None
_vector_db_client: Optional[VectorDatabaseClient] = None


def get_graph_db_client() -> GraphDatabaseClient:
    """获取图数据库客户端实例（基于配置）.

    根据 graph_db_type 配置返回对应的图数据库客户端。
    当前支持: neo4j

    Returns:
        GraphDatabaseClient: 图数据库客户端实例

    Example:
        >>> from app.infrastructure.db import get_graph_db_client
        >>> neo4j = get_graph_db_client()
        >>> result = await neo4j.execute_query("MATCH (n) RETURN n LIMIT 10")
    """
    global _graph_db_client
    if _graph_db_client is None:
        settings = get_settings()
        db_type = settings.graph_db_type.lower()

        if db_type == "neo4j":
            _graph_db_client = get_neo4j_client()
        else:
            raise ValueError(f"Unsupported graph database type: {db_type}")

    return _graph_db_client


def get_vector_db_client() -> VectorDatabaseClient:
    """获取向量数据库客户端实例（基于配置）.

    根据 vector_db_type 配置返回对应的向量数据库客户端。
    当前支持: milvus

    Returns:
        VectorDatabaseClient: 向量数据库客户端实例

    Example:
        >>> from app.infrastructure.db import get_vector_db_client
        >>> milvus = get_vector_db_client()
        >>> results = await milvus.search("collection", query_vector, top_k=10)
    """
    global _vector_db_client
    if _vector_db_client is None:
        settings = get_settings()
        db_type = settings.vector_db_type.lower()

        if db_type == "milvus":
            _vector_db_client = get_milvus_client()
        else:
            raise ValueError(f"Unsupported vector database type: {db_type}")

    return _vector_db_client


def reset_db_clients() -> None:
    """重置数据库客户端实例（用于测试）."""
    global _graph_db_client, _vector_db_client
    _graph_db_client = None
    _vector_db_client = None
