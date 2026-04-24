"""图节点构建和持久化辅助类.

该类封装了对图数据库的所有节点操作，包括：
- 节点创建和更新
- 关系创建
- 节点查询
- 批量操作

流水线阶段统一使用 GraphHelper 来操作图节点，而不是直接调用数据库客户端。
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from app.infrastructure.db.graph.base_client import GraphDatabaseClient

from .graph import Class, Directory, File, Method, Module, Repository, Workflow

logger = logging.getLogger(__name__)


class GraphHelper:
    """图节点操作辅助类.

    提供统一的接口来构建和持久化各种类型的图节点。
    封装了节点创建、关系建立、属性过滤等底层细节。

    Example:
        helper = GraphHelper(graph_db)

        # 创建仓库节点
        repo = Repository(id="repo_1", name="my-repo", ...)
        await helper.create_repository(repo)

        # 创建文件节点并建立关系
        file_node = File(id="file_1", name="main.py", ...)
        await helper.create_file(file_node, parent_id="dir_1", repo_path="/path/to/repo")

        # 查询节点
        files = await helper.get_files_by_repo(repo_id="repo_1")
    """

    def __init__(self, graph_db: GraphDatabaseClient):
        """初始化 GraphHelper.

        Args:
            graph_db: 图数据库客户端实例
        """
        self.graph_db = graph_db

    # ==================== 节点创建方法 ====================

    async def create_repository(self, repository: Repository) -> str:
        """创建 Repository 节点.

        Args:
            repository: 仓库节点对象

        Returns:
            节点ID
        """
        properties = self._filter_properties(repository.to_dict())

        await self.graph_db.merge_node(
            label="Repository",
            key_property="id",
            key_value=repository.id,
            properties=properties,
        )
        logger.debug(f"Created/updated Repository node: {repository.id}")
        return repository.id

    async def create_directory(
        self,
        directory: Directory,
        parent_id: str,
    ) -> str:
        """创建 Directory 节点和关系.

        Args:
            directory: 目录节点对象
            parent_id: 父节点ID（Repository 或 Directory）

        Returns:
            节点ID
        """

        properties = self._filter_properties(directory.to_dict())

        await self.graph_db.merge_node(
            label="Directory",
            key_property="id",
            key_value=directory.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        parent_label = self._get_parent_label(parent_id)
        await self.graph_db.create_relationship(
            from_label=parent_label,
            from_key="id",
            from_value=parent_id,
            to_label="Directory",
            to_key="id",
            to_value=directory.id,
            rel_type="CONTAIN",
        )
        logger.debug(f"Created Directory node: {directory.id}, parent: {parent_id}")
        return directory.id

    def _get_parent_id(self, directory_path: str, repo_id: str) -> Optional[str]:
        """获取目录的父节点ID."""
        if "/" not in directory_path and "\\" not in directory_path:
            return repo_id

        parent_path = os.path.dirname(directory_path).replace("\\", "/")
        if parent_path == ".":
            return repo_id

        return f"dir_{repo_id.replace('repo_', '')}_{parent_path}"



    async def create_file(
        self,
        file_node: File,
        parent_id: str,
        repo_path: str,
    ) -> str:
        """创建 File 节点和关系.

        Args:
            file_node: 文件节点对象
            parent_id: 父节点ID（Directory 或 Repository）
            repo_path: 仓库根路径，用于读取文件内容

        Returns:
            节点ID
        """
        # 读取文件内容
        file_path = Path(repo_path) / file_node.path
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            file_node.code = content
        except Exception as e:
            logger.warning(f"Failed to read file content {file_node.path}: {e}")
            file_node.code = ""

        properties = self._filter_properties(file_node.to_dict())

        await self.graph_db.merge_node(
            label="File",
            key_property="id",
            key_value=file_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        parent_label = self._get_parent_label(parent_id)
        await self.graph_db.create_relationship(
            from_label=parent_label,
            from_key="id",
            from_value=parent_id,
            to_label="File",
            to_key="id",
            to_value=file_node.id,
            rel_type="CONTAIN",
        )
        logger.debug(f"Created File node: {file_node.id}, parent: {parent_id}")
        return file_node.id

    async def create_class(
        self,
        class_node: Class,
        file_id: str,
    ) -> str:
        """创建 Class 节点和关系.

        Args:
            class_node: 类节点对象
            file_id: 所属文件节点ID

        Returns:
            节点ID
        """
        properties = self._filter_properties(class_node.to_dict())

        await self.graph_db.merge_node(
            label="Class",
            key_property="id",
            key_value=class_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        await self.graph_db.create_relationship(
            from_label="File",
            from_key="id",
            from_value=file_id,
            to_label="Class",
            to_key="id",
            to_value=class_node.id,
            rel_type="CONTAIN",
        )
        logger.debug(f"Created Class node: {class_node.id}, file: {file_id}")
        return class_node.id

    async def create_method(
        self,
        method_node: Method,
        parent_id: str,
    ) -> str:
        """创建 Method 节点和关系.

        Args:
            method_node: 方法节点对象
            parent_id: 父节点ID（Class 或 File）

        Returns:
            节点ID
        """
        properties = self._filter_properties(method_node.to_dict())

        await self.graph_db.merge_node(
            label="Method",
            key_property="id",
            key_value=method_node.id,
            properties=properties,
        )

        # 确定父节点标签
        parent_label = "Class" if "class_" in parent_id else "File"

        # 创建 CONTAIN 关系
        await self.graph_db.create_relationship(
            from_label=parent_label,
            from_key="id",
            from_value=parent_id,
            to_label="Method",
            to_key="id",
            to_value=method_node.id,
            rel_type="CONTAIN",
        )
        logger.debug(f"Created Method node: {method_node.id}, parent: {parent_id}")
        return method_node.id

    async def create_module(self, module: Module) -> str:
        """创建 Module 节点.

        Args:
            module: 模块节点对象

        Returns:
            节点ID
        """
        properties = self._filter_properties(module.to_dict())

        await self.graph_db.merge_node(
            label="Module",
            key_property="id",
            key_value=module.id,
            properties=properties,
        )
        logger.debug(f"Created Module node: {module.id}")
        return module.id

    async def create_workflow(self, workflow: Workflow) -> str:
        """创建 Workflow 节点.

        Args:
            workflow: 工作流节点对象

        Returns:
            节点ID
        """
        properties = self._filter_properties(workflow.to_dict())

        await self.graph_db.merge_node(
            label="Workflow",
            key_property="id",
            key_value=workflow.id,
            properties=properties,
        )
        logger.debug(f"Created Workflow node: {workflow.id}")
        return workflow.id

    # ==================== 关系创建方法 ====================

    async def create_belong_to_relationship(
        self,
        from_id: str,
        to_id: str,
        from_label: str,
        to_label: str = "Module",
    ) -> bool:
        """创建 BELONG_TO 关系.

        Args:
            from_id: 源节点ID
            to_id: 目标节点ID
            from_label: 源节点标签
            to_label: 目标节点标签，默认为 Module

        Returns:
            是否成功创建
        """
        return await self.graph_db.create_relationship(
            from_label=from_label,
            from_key="id",
            from_value=from_id,
            to_label=to_label,
            to_key="id",
            to_value=to_id,
            rel_type="BELONG_TO",
        )

    async def create_call_relationship(
        self,
        from_method_id: str,
        to_method_id: str,
    ) -> bool:
        """创建方法调用 CALL 关系.

        Args:
            from_method_id: 调用方法ID
            to_method_id: 被调用方法ID

        Returns:
            是否成功创建
        """
        return await self.graph_db.create_relationship(
            from_label="Method",
            from_key="id",
            from_value=from_method_id,
            to_label="Method",
            to_key="id",
            to_value=to_method_id,
            rel_type="CALL",
        )

    async def create_use_relationship(
        self,
        from_file_id: str,
        to_file_id: str,
    ) -> bool:
        """创建文件 USE 关系.

        Args:
            from_file_id: 源文件ID
            to_file_id: 目标文件ID

        Returns:
            是否成功创建
        """
        return await self.graph_db.create_relationship(
            from_label="File",
            from_key="id",
            from_value=from_file_id,
            to_label="File",
            to_key="id",
            to_value=to_file_id,
            rel_type="USE",
        )

    # ==================== 节点查询方法 ====================

    async def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取节点.

        Args:
            node_id: 节点ID

        Returns:
            节点数据或None
        """
        return await self.graph_db.get_node_by_id(node_id)

    async def get_repository(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """获取仓库节点.

        Args:
            repo_id: 仓库ID

        Returns:
            仓库节点数据或None
        """
        return await self.graph_db.get_node_by_id(repo_id)

    async def get_files_by_repo(self, repo_id: str) -> List[Dict[str, Any]]:
        """获取仓库下的所有文件节点.

        Args:
            repo_id: 仓库ID

        Returns:
            文件节点列表
        """
        return await self.graph_db.get_code_files(repo_id)

    async def get_classes_by_repo(self, repo_id: str) -> List[Dict[str, Any]]:
        """获取仓库下的所有类节点.

        Args:
            repo_id: 仓库ID

        Returns:
            类节点列表
        """
        query = """
        MATCH (c:Class)
        WHERE c.repoId = $repo_id
        RETURN c.id as id, c.name as name, c.code as code,
               c.language as language, c.filePath as file_path
        """
        return await self.graph_db._execute_query(
            query, {"repo_id": repo_id}
        )

    async def get_methods_by_repo(self, repo_id: str) -> List[Dict[str, Any]]:
        """获取仓库下的所有方法节点.

        Args:
            repo_id: 仓库ID

        Returns:
            方法节点列表
        """
        return await self.graph_db.get_all_methods(repo_id)

    async def get_modules_by_repo(self, repo_id: str) -> List[Dict[str, Any]]:
        """获取仓库下的所有模块节点.

        Args:
            repo_id: 仓库ID

        Returns:
            模块节点列表
        """
        return await self.graph_db.get_modules(repo_id)

    async def get_file_by_path(self, repo_id: str, file_path: str) -> Optional[Dict[str, Any]]:
        """根据路径获取文件节点.

        Args:
            repo_id: 仓库ID
            file_path: 文件路径

        Returns:
            文件节点数据或None
        """
        query = """
        MATCH (f:File)
        WHERE f.repoId = $repo_id AND f.path = $path
        RETURN f.id as id, f.name as name, f.code as code,
               f.summary as summary, f.fileType as file_type
        """
        result = await self.graph_db._execute_query(
            query, {"repo_id": repo_id, "path": file_path}
        )
        return result[0] if result else None

    async def get_class_by_id(self, class_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取类节点.

        Args:
            class_id: 类节点ID

        Returns:
            类节点数据或None
        """
        return await self.graph_db.get_node_by_id(class_id)

    async def get_method_by_id(self, method_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取方法节点.

        Args:
            method_id: 方法节点ID

        Returns:
            方法节点数据或None
        """
        return await self.graph_db.get_node_by_id(method_id)

    # ==================== 批量操作方法 ====================

    async def batch_create_directories(
        self,
        directories: List[Directory],
        parent_ids: List[str],
    ) -> int:
        """批量创建 Directory 节点和 CONTAIN 关系.

        Args:
            directories: 目录节点列表
            parent_ids: 对应的父节点ID列表

        Returns:
            成功创建的节点数量
        """
        if not directories:
            return 0

        nodes = [
            {"id": d.id, "properties": self._filter_properties(d.to_dict())}
            for d in directories
        ]
        await self.graph_db.batch_merge_nodes("Directory", nodes)

        rels = [
            {"from_id": pid, "to_id": d.id}
            for d, pid in zip(directories, parent_ids)
        ]
        await self.graph_db.batch_create_relationships("CONTAIN", rels)

        logger.debug(f"Batch created {len(directories)} Directory nodes")
        return len(directories)

    async def batch_create_files(
        self,
        file_nodes: List[File],
        parent_ids: List[str],
    ) -> int:
        """批量创建 File 节点和 CONTAIN 关系.

        Args:
            file_nodes: 文件节点列表（code 属性需已设置）
            parent_ids: 对应的父节点ID列表

        Returns:
            成功创建的节点数量
        """
        if not file_nodes:
            return 0

        nodes = [
            {"id": f.id, "properties": self._filter_properties(f.to_dict())}
            for f in file_nodes
        ]
        await self.graph_db.batch_merge_nodes("File", nodes)

        rels = [
            {"from_id": pid, "to_id": f.id}
            for f, pid in zip(file_nodes, parent_ids)
        ]
        await self.graph_db.batch_create_relationships("CONTAIN", rels)

        logger.debug(f"Batch created {len(file_nodes)} File nodes")
        return len(file_nodes)

    async def batch_create_classes(
        self,
        class_nodes: List[Class],
        file_ids: List[str],
    ) -> int:
        """批量创建 Class 节点和 CONTAIN 关系.

        Args:
            class_nodes: 类节点列表
            file_ids: 对应的所属文件ID列表

        Returns:
            成功创建的节点数量
        """
        if not class_nodes:
            return 0

        nodes = [
            {"id": c.id, "properties": self._filter_properties(c.to_dict())}
            for c in class_nodes
        ]
        await self.graph_db.batch_merge_nodes("Class", nodes)

        rels = [
            {"from_id": fid, "to_id": c.id}
            for c, fid in zip(class_nodes, file_ids)
        ]
        await self.graph_db.batch_create_relationships("CONTAIN", rels)

        logger.debug(f"Batch created {len(class_nodes)} Class nodes")
        return len(class_nodes)

    async def batch_create_methods(
        self,
        method_nodes: List[Method],
        parent_ids: List[str],
    ) -> int:
        """批量创建 Method 节点和 CONTAIN 关系.

        Args:
            method_nodes: 方法节点列表
            parent_ids: 对应的父节点ID列表（Class 或 File）

        Returns:
            成功创建的节点数量
        """
        if not method_nodes:
            return 0

        nodes = [
            {"id": m.id, "properties": self._filter_properties(m.to_dict())}
            for m in method_nodes
        ]
        await self.graph_db.batch_merge_nodes("Method", nodes)

        rels = [
            {"from_id": pid, "to_id": m.id}
            for m, pid in zip(method_nodes, parent_ids)
        ]
        await self.graph_db.batch_create_relationships("CONTAIN", rels)

        logger.debug(f"Batch created {len(method_nodes)} Method nodes")
        return len(method_nodes)

    async def batch_create_use_relationships(
        self,
        relations: List[Tuple[str, str]],
    ) -> int:
        """批量创建文件间的 USE 关系.

        Args:
            relations: 关系列表，每项为 (from_file_id, to_file_id)

        Returns:
            成功创建的关系数量
        """
        if not relations:
            return 0
        rels = [{"from_id": f, "to_id": t} for f, t in relations]
        count = await self.graph_db.batch_create_relationships(
            "USE", rels, from_label="File", to_label="File"
        )
        logger.debug(f"Batch created {count} USE relationships")
        return count

    async def batch_create_call_relationships(
        self,
        relations: List[Tuple[str, str]],
    ) -> int:
        """批量创建方法间的 CALL 关系.

        Args:
            relations: 关系列表，每项为 (from_method_id, to_method_id)

        Returns:
            成功创建的关系数量
        """
        if not relations:
            return 0
        rels = [{"from_id": f, "to_id": t} for f, t in relations]
        count = await self.graph_db.batch_create_relationships(
            "CALL", rels, from_label="Method", to_label="Method"
        )
        logger.debug(f"Batch created {count} CALL relationships")
        return count

    # ==================== 节点更新方法 ====================

    async def update_node_summary(
        self,
        label: str,
        node_id: str,
        summary: str,
    ) -> bool:
        """更新节点的 summary 属性.

        Args:
            label: 节点标签
            node_id: 节点ID
            summary: 摘要内容

        Returns:
            是否成功更新
        """
        return await self.graph_db.update_node_summary(label, node_id, summary)

    async def update_node_summaries_batch(
        self,
        label: str,
        updates: List[Tuple[str, str]],
    ) -> int:
        """批量更新节点的 summary 属性.

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, summary) 元组

        Returns:
            成功更新的节点数量
        """
        return await self.graph_db.update_node_summaries_batch(label, updates)

    async def update_node_embedding_id(
        self,
        label: str,
        node_id: str,
        embedding_id: str,
    ) -> bool:
        """更新节点的 embeddingId 属性.

        Args:
            label: 节点标签
            node_id: 节点ID
            embedding_id: 向量ID

        Returns:
            是否成功更新
        """
        return await self.graph_db.update_node_embedding_id(
            label, node_id, embedding_id
        )

    async def update_method_image(
        self,
        method_id: str,
        image_id: str,
    ) -> bool:
        """更新Method节点的image属性.

        Args:
            method_id: 方法节点ID
            image_id: 图片ID

        Returns:
            是否成功更新
        """
        return await self.graph_db.update_method_image(method_id, image_id)

    # ==================== 私有辅助方法 ====================

    def _filter_properties(self, properties: Dict[str, Any]) -> Dict[str, Any]:
        """过滤属性，只保留基本类型.

        Neo4j 支持基本类型（字符串、数字、布尔值、日期）、这些类型的数组，
        以及值为基本类型的字典（Map）。过滤掉嵌套对象和 None 值。

        Args:
            properties: 原始属性字典

        Returns:
            过滤后的属性字典
        """
        filtered = {}
        for key, value in properties.items():
            if value is None:
                continue
            # 允许值为基本类型的字典（Neo4j Map）
            if isinstance(value, dict):
                if value and all(
                    isinstance(v, (str, int, float, bool)) for v in value.values()
                ):
                    filtered[key] = value
                continue
            # 跳过所有列表类型（除非是纯基本类型列表）
            if isinstance(value, list):
                # 只保留非空且元素都是基本类型的列表
                if value and all(
                    not isinstance(item, (dict, list)) for item in value
                ):
                    filtered[key] = value
                continue
            # 基本类型
            filtered[key] = value
        return filtered

    def _get_parent_label(self, parent_id: str) -> str:
        """根据父节点ID确定节点标签.

        Args:
            parent_id: 父节点ID

        Returns:
            节点标签
        """
        if parent_id.startswith("repo_"):
            return "Repository"
        elif parent_id.startswith("dir_"):
            return "Directory"
        elif parent_id.startswith("class_"):
            return "Class"
        elif parent_id.startswith("file_"):
            return "File"
        else:
            # 默认根据ID特征判断
            if "dir_" in parent_id:
                return "Directory"
            return "Repository"
