"""图数据库客户端抽象基类.

提供图数据库操作的通用接口，所有图数据库实现需继承此类。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


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
    async def batch_merge_nodes(
        self,
        label: str,
        nodes: List[Dict[str, Any]],
        database: Optional[str] = None,
    ) -> int:
        """批量合并节点（使用UNWIND优化）.

        Args:
            label: 节点标签
            nodes: 节点属性列表，每项必须包含 'id' 和 'properties' 字段
            database: 目标数据库名称

        Returns:
            成功合并的节点数量
        """
        pass

    @abstractmethod
    async def batch_create_relationships(
        self,
        rel_type: str,
        relationships: List[Dict[str, str]],
        from_label: Optional[str] = None,
        to_label: Optional[str] = None,
        database: Optional[str] = None,
    ) -> int:
        """批量创建关系（使用UNWIND优化）.

        Args:
            rel_type: 关系类型
            relationships: 关系列表，每项包含 'from_id' 和 'to_id'
            from_label: 起始节点标签（可选，用于优化MATCH性能）
            to_label: 目标节点标签（可选，用于优化MATCH性能）
            database: 目标数据库名称

        Returns:
            成功创建的关系数量
        """
        pass

    @abstractmethod
    async def delete_repo_data(self, repo_id: str, database: Optional[str] = None) -> int:
        """删除仓库相关数据.

        Args:
            repo_id: 仓库ID
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
    async def get_code_files(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定仓库的所有代码文件节点.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            File 节点列表，包含 id, path, code, suffix, language 等字段
        """
        pass

    @abstractmethod
    async def get_all_methods(
        self,
        repo_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定仓库的所有 Method 节点.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 id, name, code, language, file_path 等字段
        """
        pass

    @abstractmethod
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
            节点列表，每项包含 id, name, type, file_path, summary, language, description 等字段
        """
        pass

    @abstractmethod
    async def get_methods_with_calls(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Method 节点及其 CALL 关系.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 code, docstring, language, name, summary, callee_ids 等字段
        """
        pass

    @abstractmethod
    async def get_classes_with_methods(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 Class 节点及其包含的 Method summaries.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Class 节点列表，包含 code, docstring, language, name, summary, method_summaries 等字段
        """
        pass

    @abstractmethod
    async def get_files_for_summary(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有 File 节点及其包含的 Class/Method summaries.

        Args:
            repo_id: 仓库ID
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
    async def update_node_summaries_batch(
        self,
        label: str,
        updates: List[Tuple[str, str]],
        database: Optional[str] = None,
    ) -> int:
        """批量更新节点的 summary 属性.

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, summary) 元组
            database: 目标数据库名称

        Returns:
            成功更新的节点数量
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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

    @abstractmethod
    async def update_node_embedding_ids_batch(
        self,
        label: str,
        updates: List[Tuple[str, str]],
        database: Optional[str] = None,
    ) -> int:
        """批量更新节点的 embeddingId 属性.

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, embedding_id) 元组
            database: 目标数据库名称

        Returns:
            成功更新的节点数量
        """
        pass

    @abstractmethod
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
            目录和文件列表，每项包含 path, type, labels 字段
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
            direction: 关系方向 ("out":  outgoing, "in": incoming, "both": 双向)
            database: 目标数据库名称

        Returns:
            关联节点列表，每项包含 id, name, labels, summary, description 等字段
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def search_nodes_by_name(
        self,
        repo_id: str,
        name: str,
        node_types: List[str],
        fuzzy: bool = True,
        top_k: int = 10,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """根据节点名称搜索代码节点.

        Args:
            repo_id: 仓库ID
            name: 节点名称关键字
            node_types: 节点类型列表，如 ["File", "Class", "Method"]
            fuzzy: 是否模糊匹配，True 使用 CONTAINS，False 使用精确匹配
            top_k: 返回结果数量上限
            database: 目标数据库名称

        Returns:
            节点列表，每项包含 id, name, types, file_path, summary, docstring 等字段
        """
        pass

    @abstractmethod
    async def batch_get_node_details(
        self,
        repo_id: str,
        node_ids: List[str],
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """批量根据节点 ID 获取节点详情.

        Args:
            repo_id: 仓库ID
            node_ids: 节点 ID 列表
            database: 目标数据库名称

        Returns:
            节点详情列表，每项包含 id, name, types, file_path, code, summary, docstring, language, suffix 等字段
        """
        pass

    @abstractmethod
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
            包含 totalFiles, totalCodeFiles, totalLines, totalSize, languages, languageDistribution 等字段的字典，或 None
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_lineage_graph_page(
        self,
        repo_id: str,
        page: int,
        page_size: int,
        database: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页读取代码—文档追溯所需的完整代码图.

        Args:
            repo_id: 仓库ID
            page: 页码
            page_size: 每页节点数量
            database: 目标数据库名称

        Returns:
            节点、当前页相关关系、总数和类型统计
        """
        pass
