"""数据库客户端抽象基类.

提供图数据库和向量数据库的抽象接口，便于后续扩展其他实现。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class GraphDatabaseClient(ABC):
    """图数据库客户端抽象基类.

    定义图数据库操作的通用接口，所有图数据库实现需继承此类。
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
    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """执行查询语句.

        Args:
            query: 查询语句
            parameters: 查询参数
            database: 目标数据库名称

        Returns:
            查询结果列表
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def delete_repo_data(self, repo_name: str, database: Optional[str] = None) -> int:
        """删除仓库相关数据.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            删除的节点数量
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_node_relationships(
        self,
        node_id: str,
        direction: str = "both",
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取节点的关系.

        Args:
            node_id: 节点ID
            direction: 关系方向 ("out", "in", "both")
            database: 目标数据库名称

        Returns:
            关系列表
        """
        pass


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
        repo: str,
    ) -> int:
        """删除指定仓库的数据.

        Args:
            collection_name: Collection/索引名称
            repo: 仓库名称

        Returns:
            删除的记录数量
        """
        pass

    @abstractmethod
    async def delete_repo_data(self, repo: str) -> Dict[str, int]:
        """删除指定仓库的所有数据.

        Args:
            repo: 仓库名称

        Returns:
            各 collection/索引 删除数量统计
        """
        pass
