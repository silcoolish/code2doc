"""向量数据库客户端抽象基类.

定义向量数据库操作的通用接口，所有向量数据库实现需继承此类。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class VectorDatabaseClient(ABC):
    """向量数据库客户端抽象基类.

    定义向量数据库操作的通用接口，所有向量数据库实现需继承此类。
    """

    @abstractmethod
    async def connect(self) -> None:
        """建立数据库连接."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭数据库连接."""
        pass

    @abstractmethod
    async def insert(
        self,
        collection_name: str,
        records: List[Dict[str, Any]],
    ) -> List[str]:
        """插入记录.

        Args:
            collection_name: Collection/索引名称
            records: 记录列表

        Returns:
            插入记录的ID列表
        """
        pass

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """向量搜索.

        Args:
            collection_name: Collection/索引名称
            query_vector: 查询向量
            top_k: 返回结果数量
            filter_expr: 过滤表达式

        Returns:
            搜索结果列表
        """
        pass

    @abstractmethod
    async def delete_by_repo(
        self,
        collection_name: str,
        repo_id: str,
    ) -> int:
        """删除指定仓库的数据.

        Args:
            collection_name: Collection/索引名称
            repo_id: 仓库ID

        Returns:
            删除的记录数量
        """
        pass

    @abstractmethod
    async def delete_repo_data(self, repo_id: str) -> Dict[str, int]:
        """删除指定仓库的所有数据.

        Args:
            repo_id: 仓库ID

        Returns:
            各 collection/索引 删除数量统计
        """
        pass
