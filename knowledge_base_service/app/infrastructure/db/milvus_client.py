"""Milvus 向量数据库客户端."""

import logging
from typing import Any, Dict, List, Optional

from pymilvus import (
    AsyncMilvusClient,
    DataType,
    FieldSchema,
    CollectionSchema,
    utility,
    Collection,
)

from app.config import get_settings
from app.domain.models.vector import (
    FileSummaryRecord,
    ClassSummaryRecord,
    MethodSummaryRecord,
    SemanticSummaryRecord,
    SemanticDetailRecord,
)
from app.infrastructure.db.base_client import VectorDatabaseClient

logger = logging.getLogger(__name__)

# Collection 名称常量
COLLECTIONS = {
    "file_summary": "file_summary_collection",
    "class_summary": "class_summary_collection",
    "method_summary": "method_summary_collection",
    "semantic_summary": "semantic_summary_collection",
    "semantic_detail": "semantic_detail_collection",
}


class MilvusClient(VectorDatabaseClient):
    """Milvus 异步客户端封装."""

    _instance: Optional["MilvusClient"] = None
    _client: Optional[AsyncMilvusClient] = None
    _dimensions: int = 3072

    def __new__(cls) -> "MilvusClient":
        """单例模式."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self) -> None:
        """建立数据库连接."""
        if self._client is None:
            settings = get_settings()
            self._dimensions = settings.embedding_dimensions

            self._client = AsyncMilvusClient(
                uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
            )
            logger.info(
                f"Connected to Milvus at {settings.milvus_host}:{settings.milvus_port}"
            )

            # 初始化 collections
            await self._init_collections()

    async def close(self) -> None:
        """关闭数据库连接."""
        if self._client:
            # Milvus 客户端无需显式关闭
            self._client = None
            logger.info("Milvus connection closed")

    async def _init_collections(self) -> None:
        """初始化所有 collections."""
        for collection_name in COLLECTIONS.values():
            await self._create_collection_if_not_exists(collection_name)

    async def _create_collection_if_not_exists(self, collection_name: str) -> None:
        """如果不存在则创建 collection."""
        if not await self._client.has_collection(collection_name):
            # 定义字段
            fields = [
                FieldSchema(
                    name="id",
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    max_length=64,
                ),
                FieldSchema(
                    name="name",
                    dtype=DataType.VARCHAR,
                    max_length=256,
                ),
                FieldSchema(
                    name="node_id",
                    dtype=DataType.VARCHAR,
                    max_length=64,
                ),
                FieldSchema(
                    name="repo",
                    dtype=DataType.VARCHAR,
                    max_length=128,
                ),
                FieldSchema(
                    name="embedding",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=self._dimensions,
                ),
            ]

            # 根据 collection 类型添加额外字段
            if "summary" in collection_name:
                fields.append(
                    FieldSchema(
                        name="summary",
                        dtype=DataType.VARCHAR,
                        max_length=4096,
                    )
                )

            if "semantic" in collection_name:
                fields.append(
                    FieldSchema(
                        name="type",
                        dtype=DataType.VARCHAR,
                        max_length=32,
                    )
                )

            if "detail" in collection_name:
                fields.append(
                    FieldSchema(
                        name="detail",
                        dtype=DataType.VARCHAR,
                        max_length=8192,
                    )
                )

            if "code" in collection_name:
                fields.extend([
                    FieldSchema(
                        name="path",
                        dtype=DataType.VARCHAR,
                        max_length=512,
                    ),
                    FieldSchema(
                        name="code",
                        dtype=DataType.VARCHAR,
                        max_length=65535,
                    ),
                ])

            # 创建 schema 和 collection
            schema = CollectionSchema(
                fields=fields,
                description=f"Collection for {collection_name}",
            )

            await self._client.create_collection(
                collection_name=collection_name,
                schema=schema,
            )

            # 创建索引（忽略错误，不影响服务启动）
            try:
                from pymilvus import Collection
                collection = Collection(collection_name)
                collection.create_index(
                    field_name="embedding",
                    index_params={
                        "index_type": "IVF_FLAT",
                        "metric_type": "COSINE",
                        "params": {"nlist": 128},
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to create index for {collection_name}: {e}")

            logger.info(f"Created collection: {collection_name}")

    async def insert(
        self,
        collection_name: str,
        records: List[Dict[str, Any]],
    ) -> List[str]:
        """插入记录.

        Args:
            collection_name: Collection 名称
            records: 记录列表

        Returns:
            插入记录的ID列表
        """
        if self._client is None:
            await self.connect()

        if not records:
            return []

        try:
            result = await self._client.insert(
                collection_name=collection_name,
                data=records,
            )
            logger.debug(f"Inserted {len(records)} records into {collection_name}")
            # Handle different result types from pymilvus
            if result is None:
                return []
            if hasattr(result, 'primary_keys'):
                return result.primary_keys
            if hasattr(result, 'ids'):
                return result.ids
            if isinstance(result, dict):
                return result.get('ids', result.get('primary_keys', []))
            return []
        except Exception as e:
            logger.error(f"Failed to insert into {collection_name}: {e}")
            raise

    async def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """向量搜索.

        Args:
            collection_name: Collection 名称
            query_vector: 查询向量
            top_k: 返回结果数量
            filter_expr: 过滤表达式

        Returns:
            搜索结果列表
        """
        if self._client is None:
            await self.connect()

        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10},
        }

        try:
            results = await self._client.search(
                collection_name=collection_name,
                data=[query_vector],
                limit=top_k,
                output_fields=["id", "name", "node_id", "repo"],
                filter=filter_expr,
                search_params=search_params,
            )

            # 格式化结果
            formatted_results = []
            if results:
                for hits in results:
                    for hit in hits:
                        formatted_results.append({
                            "id": hit.get("id"),
                            "name": hit.get("name"),
                            "node_id": hit.get("node_id"),
                            "repo": hit.get("repo"),
                            "distance": hit.get("distance", 0),
                        })

            return formatted_results
        except Exception as e:
            logger.error(f"Search failed in {collection_name}: {e}")
            raise

    async def delete_by_repo(
        self,
        collection_name: str,
        repo: str,
    ) -> int:
        """删除指定仓库的数据.

        Args:
            collection_name: Collection 名称
            repo: 仓库名称

        Returns:
            删除的记录数量
        """
        if self._client is None:
            await self.connect()

        try:
            result = await self._client.delete(
                collection_name=collection_name,
                expr=f'repo == "{repo}"',
            )
            deleted = result.delete_count if result else 0
            logger.info(f"Deleted {deleted} records from {collection_name} for repo: {repo}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete from {collection_name}: {e}")
            raise

    async def delete_repo_data(self, repo: str) -> Dict[str, int]:
        """删除指定仓库的所有数据.

        Args:
            repo: 仓库名称

        Returns:
            各 collection 删除数量统计
        """
        results = {}
        for key, collection_name in COLLECTIONS.items():
            results[key] = await self.delete_by_repo(collection_name, repo)
        return results


# 全局客户端实例
_milvus_client: Optional[MilvusClient] = None


def get_milvus_client() -> MilvusClient:
    """获取Milvus客户端实例."""
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient()
    return _milvus_client
