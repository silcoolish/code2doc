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

    @abstractmethod
    async def get_code_files(self, repo_name: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定仓库的所有代码文件节点.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 id, path, code, suffix, language 等字段
        """
        pass

    @abstractmethod
    async def get_all_methods(self, repo_name: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定仓库的所有 Method 节点.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 id, name, code, language, file_path 等字段
        """
        pass

    @abstractmethod
    async def get_methods_with_calls(self, repo_name: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Method 节点及其 CALL 关系.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 code, docstring, language, name, summary, callee_ids 等字段
        """
        pass

    @abstractmethod
    async def get_classes_with_methods(self, repo_name: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Class 节点及其包含的 Method summaries.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            Class 节点列表，包含 code, docstring, language, name, summary, method_summaries 等字段
        """
        pass

    @abstractmethod
    async def get_files_for_summary(self, repo_name: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 File 节点及其包含的 Class/Method summaries.

        Args:
            repo_name: 仓库名称
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 code, file_type, suffix, name, summary, class_summaries, method_summaries 等字段
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_nodes_with_summary(
        self,
        repo_name: str,
        node_type: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定类型的所有包含 summary 的节点.

        Args:
            repo_name: 仓库名称
            node_type: 节点类型 (File, Class, Method)
            database: 目标数据库名称

        Returns:
            节点列表，包含 id, name, summary 等字段
        """
        pass

    @abstractmethod
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
