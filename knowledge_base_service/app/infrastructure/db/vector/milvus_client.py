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
from app.infrastructure.db.vector.base_client import VectorDatabaseClient

logger = logging.getLogger(__name__)

# 统一的 collection 名称
COLLECTION_NAME = "code_vectors"


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

            # 初始化 collection
            await self._init_collection()

    async def close(self) -> None:
        """关闭数据库连接."""
        if self._client:
            # Milvus 客户端无需显式关闭
            self._client = None
            logger.info("Milvus connection closed")

    async def _init_collection(self) -> None:
        """初始化 collection."""
        await self._create_collection_if_not_exists(COLLECTION_NAME)

    async def _create_collection_if_not_exists(self, collection_name: str) -> None:
        """如果不存在则创建 collection 并同步创建索引."""
        if await self._client.has_collection(collection_name):
            logger.info(f"Collection already exists: {collection_name}")
            return

        # 定义统一字段
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
                max_length=256,
            ),
            FieldSchema(
                name="repo",
                dtype=DataType.VARCHAR,
                max_length=128,
            ),
            FieldSchema(
                name="repo_id",
                dtype=DataType.VARCHAR,
                max_length=64,
            ),
            FieldSchema(
                name="type",
                dtype=DataType.VARCHAR,
                max_length=32,
            ),
            FieldSchema(
                name="summary",
                dtype=DataType.VARCHAR,
                max_length=4096,
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self._dimensions,
            ),
        ]

        # 创建 schema 和 collection
        schema = CollectionSchema(
            fields=fields,
            description="Unified collection for code vector records",
        )

        await self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
        )
        logger.info(f"Created collection: {collection_name}")

        # 同步创建索引 - 需要建立同步连接
        import asyncio
        from pymilvus import connections

        settings = get_settings()

        def _create_index_sync():
            """同步创建索引并等待构建完成."""
            # 建立同步连接（使用独立的别名避免冲突）
            conn_alias = f"sync_conn_{collection_name}"
            try:
                connections.connect(
                    alias=conn_alias,
                    host=settings.milvus_host,
                    port=settings.milvus_port,
                )
                logger.debug(f"Established sync connection: {conn_alias}")
            except Exception as conn_err:
                # 如果已经存在，尝试断开重连
                try:
                    connections.disconnect(conn_alias)
                except Exception:
                    pass
                connections.connect(
                    alias=conn_alias,
                    host=settings.milvus_host,
                    port=settings.milvus_port,
                )

            try:
                # 使用指定连接别名创建 Collection
                collection = Collection(collection_name, using=conn_alias)
                collection.create_index(
                    field_name="embedding",
                    index_params={
                        "index_type": "IVF_FLAT",
                        "metric_type": "COSINE",
                        "params": {"nlist": 128},
                    },
                    using=conn_alias,
                )
                # 等待索引构建完成
                utility.wait_for_index_building_complete(
                    collection_name, using=conn_alias
                )
                return True
            finally:
                # 断开同步连接
                try:
                    connections.disconnect(conn_alias)
                except Exception:
                    pass

        try:
            # 在线程池中执行同步索引创建，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _create_index_sync)
            logger.info(f"Created index for collection: {collection_name}")
        except Exception as e:
            logger.error(f"Failed to create index for {collection_name}: {e}")
            raise RuntimeError(
                f"Failed to create index for {collection_name}: {e}"
            ) from e

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
            output_fields = ["id", "name", "node_id", "repo", "repo_id", "type", "summary"]

            results = await self._client.search(
                collection_name=collection_name,
                data=[query_vector],
                limit=top_k,
                output_fields=output_fields,
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
                            "repo_id": hit.get("repo_id"),
                            "type": hit.get("type"),
                            "distance": hit.get("distance", 0),
                            "summary": hit.get("summary"),
                        })

            return formatted_results
        except Exception as e:
            logger.error(f"Search failed in {collection_name}: {e}")
            raise

    async def delete_by_repo(
        self,
        collection_name: str,
        repo_id: str,
    ) -> int:
        """删除指定仓库的数据.

        Args:
            collection_name: Collection 名称
            repo_id: 仓库ID

        Returns:
            删除的记录数量
        """
        # 空值检查
        if not repo_id:
            logger.error(f"repo_id is empty or None for collection {collection_name}")
            return 0

        if not collection_name:
            logger.error(f"collection_name is empty or None for repo {repo_id}")
            return 0

        if self._client is None:
            await self.connect()

        try:
            # 检查 collection 是否存在
            if not await self._client.has_collection(collection_name):
                logger.warning(f"Collection {collection_name} does not exist, skipping delete")
                return 0

            # 加载 collection（Milvus 删除前需要先加载）
            await self._client.load_collection(collection_name)

            # 构建删除表达式
            delete_expr = f"repo == '{repo_id}'"
            logger.debug(f"Deleting from {collection_name} with expr: {delete_expr}")

            result = await self._client.delete(
                collection_name=collection_name,
                expression=delete_expr,
            )
            deleted = result.delete_count if result else 0
            logger.info(f"Deleted {deleted} records from {collection_name} for repo: {repo_id}")

            # Flush 以确保删除操作持久化
            await self._client.flush(collection_name)

            # 释放 collection
            await self._client.release_collection(collection_name)

            return deleted
        except Exception as e:
            logger.error(f"Failed to delete from {collection_name}: {e}")
            raise

    async def delete_repo_data(self, repo_id: str) -> int:
        """删除指定仓库的所有数据.

        Args:
            repo_id: 仓库ID

        Returns:
            删除的记录数量
        """
        return await self.delete_by_repo(COLLECTION_NAME, repo_id)


# 全局客户端实例
_milvus_client: Optional[MilvusClient] = None


def get_milvus_client() -> MilvusClient:
    """获取Milvus客户端实例."""
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient()
    return _milvus_client
