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
    async def get_all_methods(self, repo_id: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定仓库的所有 Method 节点.

        Args:
            repo_id: 仓库ID
            database: 目标数据库名称

        Returns:
            Method 节点列表，包含 id, name, code, language, file_path 等字段
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
    async def get_module_workflows(
        self,
        module_id: str,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取 Module 对应的 Workflow 列表.

        Args:
            module_id: Module ID
            database: 目标数据库名称

        Returns:
            Workflow 列表，每项包含 id, name, description, summary 字段
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
