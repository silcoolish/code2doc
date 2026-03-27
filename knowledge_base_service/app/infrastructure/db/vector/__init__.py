"""向量数据库模块.

提供向量数据库的抽象基类和客户端实现。
"""

from app.infrastructure.db.vector.base_client import VectorDatabaseClient
from app.infrastructure.db.vector.milvus_client import MilvusClient, get_milvus_client

__all__ = [
    "VectorDatabaseClient",
    "MilvusClient",
    "get_milvus_client",
]
