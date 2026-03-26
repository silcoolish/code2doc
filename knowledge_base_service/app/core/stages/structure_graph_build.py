"""结构图构建阶段处理器.

该阶段合并了代码解析和结构图构建:
1. 遍历仓库文件
2. 解析代码文件提取类和方法
3. 将解析结果立即存入Neo4j图数据库
4. 在上下文中只保存节点ID信息

后续阶段需要具体信息时，应通过节点ID从图数据库中查询。
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Class, Directory, File, Method, Repository
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.parser.code_parser import ClassSymbol, MethodSymbol
from app.domain.parser.tree_sitter_parser import get_parser_for_file
from app.infrastructure.db.base_client import GraphDatabaseClient
from app.infrastructure.db.neo4j_client import get_neo4j_client

logger = logging.getLogger(__name__)


class StructureGraphBuildStage(PipelineStageHandler):
    """结构图构建阶段处理器.

    将代码解析和图构建合并为一个阶段，解析后立即存储到Neo4j，
    上下文中只保留节点ID引用。

    Input (context.data):
        - traversal_result: TraversalResult - 包含 repository, directories, files

    Output (context.data):
        - node_ids: Dict[str, List[str]] - 各类节点的ID列表
          包含: repository_id, directory_ids, file_ids, class_ids, method_ids

    Side Effects:
        - 在 Neo4j 中创建 Repository, Directory, File, Class, Method 节点
        - 创建 CONTAIN 关系连接各节点
    """

    stage = PipelineStage.STRUCTURE_GRAPH_BUILD

    def __init__(self):
        self.settings = get_settings()
        self._neo4j: Optional[GraphDatabaseClient] = None

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行结构图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self._neo4j = get_neo4j_client()

            # 获取遍历结果
            traversal_result = context.data.get("traversal_result")
            if not traversal_result:
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.FAILED,
                    message="No traversal_result found in context",
                )

            repository: Repository = traversal_result.repository
            directories: List[Directory] = traversal_result.directories
            files: List[File] = traversal_result.files

            # 节点ID记录（只存ID，不存完整数据）
            node_ids = {
                "repository_id": "",
                "directory_ids": [],
                "file_ids": [],
                "class_ids": [],
                "method_ids": [],
            }

            # 1. 创建 Repository 节点
            await self._create_repository(repository)
            node_ids["repository_id"] = repository.id
            logger.info(f"Created Repository node: {repository.name}")

            # 2. 创建 Directory 节点和关系
            for directory in directories:
                await self._create_directory(directory, repository.id)
                node_ids["directory_ids"].append(directory.id)

            logger.info(f"Created {len(node_ids['directory_ids'])} Directory nodes")

            # 3. 解析代码文件并创建 File/Class/Method 节点
            file_node_ids, class_node_ids, method_node_ids = await self._process_code_files(
                files, directories, repository.id, context.repo_name, context.repo_path
            )
            node_ids["file_ids"] = file_node_ids
            node_ids["class_ids"] = class_node_ids
            node_ids["method_ids"] = method_node_ids

            # 4. 保存节点ID到上下文（而非完整数据）
            context.data["node_ids"] = node_ids

            # 统计信息
            metadata = {
                "repositories": 1,
                "directories": len(node_ids["directory_ids"]),
                "files": len(node_ids["file_ids"]),
                "classes": len(node_ids["class_ids"]),
                "methods": len(node_ids["method_ids"]),
            }

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Structure graph built: {len(node_ids['file_ids'])} files, "
                        f"{len(node_ids['class_ids'])} classes, "
                        f"{len(node_ids['method_ids'])} methods",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"Structure graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _process_code_files(
        self,
        files: List[File],
        directories: List[Directory],
        repo_id: str,
        repo_name: str,
        repo_path: str,
    ) -> tuple[List[str], List[str], List[str]]:
        """处理代码文件：解析并创建节点.

        Args:
            files: 文件列表
            directories: 目录列表
            repo_id: 仓库ID
            repo_name: 仓库名称
            repo_path: 仓库路径

        Returns:
            (file_ids, class_ids, method_ids)
        """
        # 过滤出代码文件
        code_files = [
            f for f in files
            if f.file_type == "code" and self._is_supported_language(f.suffix)
        ]

        total_files = len(code_files)
        file_ids: List[str] = []
        class_ids: List[str] = []
        method_ids: List[str] = []

        logger.info(f"Processing {total_files} code files...")

        # 批量处理
        batch_size = 50
        for i in range(0, total_files, batch_size):
            batch = code_files[i:i + batch_size]

            # 并发处理
            tasks = [
                self._parse_and_store_file(f, directories, repo_id, repo_name, repo_path)
                for f in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for file_node, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to process {file_node.path}: {result}")
                else:
                    f_ids, c_ids, m_ids = result
                    file_ids.extend(f_ids)
                    class_ids.extend(c_ids)
                    method_ids.extend(m_ids)

            progress = min(100, int((i + len(batch)) / total_files * 100))
            logger.info(f"Processing progress: {progress}% ({i + len(batch)}/{total_files})")

        logger.info(f"Created {len(class_ids)} Class nodes")
        logger.info(f"Created {len(method_ids)} Method nodes")

        return file_ids, class_ids, method_ids

    async def _parse_and_store_file(
        self,
        file_node: File,
        directories: List[Directory],
        repo_id: str,
        repo_name: str,
        repo_path: str,
    ) -> tuple[List[str], List[str], List[str]]:
        """解析单个文件并存储到图数据库.

        Args:
            file_node: 文件节点
            directories: 目录列表
            repo_id: 仓库ID
            repo_name: 仓库名称
            repo_path: 仓库路径

        Returns:
            (file_ids, class_ids, method_ids)
        """
        file_ids: List[str] = []
        class_ids: List[str] = []
        method_ids: List[str] = []

        # 获取父目录ID
        parent_id = self._get_parent_directory_id(file_node.path, directories, repo_id)

        # 创建 File 节点
        await self._create_file(file_node, parent_id)
        file_ids.append(file_node.id)

        # 解析文件
        file_path = Path(repo_path) / file_node.path

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Failed to read file {file_node.path}: {e}")
            return file_ids, class_ids, method_ids

        parser = get_parser_for_file(file_node.path)
        if not parser:
            return file_ids, class_ids, method_ids

        parse_result = parser.parse(file_node.path, content)
        if not parse_result.success:
            logger.warning(f"Failed to parse {file_node.path}: {parse_result.error}")
            return file_ids, class_ids, method_ids

        file_id = file_node.id

        # 创建 Class 节点
        for class_symbol in parse_result.classes:
            class_node_id = await self._create_class_from_symbol(
                class_symbol, file_id, file_node.path, parse_result.language, repo_name
            )
            class_ids.append(class_node_id)

            # 创建类中的 Method 节点
            for method_symbol in class_symbol.methods:
                method_node_id = await self._create_method_from_symbol(
                    method_symbol,
                    class_node_id,
                    file_node.path,
                    parse_result.language,
                    repo_name,
                    class_name=class_symbol.name,
                )
                method_ids.append(method_node_id)

        # 创建独立 Method 节点
        for method_symbol in parse_result.methods:
            method_node_id = await self._create_method_from_symbol(
                method_symbol,
                file_id,
                file_node.path,
                parse_result.language,
                repo_name,
            )
            method_ids.append(method_node_id)

        return file_ids, class_ids, method_ids

    async def _create_repository(self, repository: Repository) -> None:
        """创建 Repository 节点."""
        properties = repository.to_dict()
        properties["repo"] = repository.name
        properties = self._filter_properties(properties)

        await self._neo4j.merge_node(
            label="Repository",
            key_property="id",
            key_value=repository.id,
            properties=properties,
        )

    async def _create_directory(self, directory: Directory, repo_id: str) -> None:
        """创建 Directory 节点和关系."""
        properties = directory.to_dict()
        properties["repo"] = repo_id.replace("repo_", "")
        properties = self._filter_properties(properties)

        await self._neo4j.merge_node(
            label="Directory",
            key_property="id",
            key_value=directory.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        parent_id = self._get_parent_id(directory.path, repo_id)
        if parent_id:
            await self._neo4j.create_relationship(
                from_label="Directory" if "/" in directory.path else "Repository",
                from_key="id",
                from_value=parent_id,
                to_label="Directory",
                to_key="id",
                to_value=directory.id,
                rel_type="CONTAIN",
            )

    async def _create_file(self, file_node: File, parent_id: str) -> None:
        """创建 File 节点和关系."""
        properties = file_node.to_dict()
        properties["repo"] = parent_id.replace("repo_", "").split("_dir_")[0]
        properties = self._filter_properties(properties)

        await self._neo4j.merge_node(
            label="File",
            key_property="id",
            key_value=file_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        label = "Directory" if "dir_" in parent_id else "Repository"
        await self._neo4j.create_relationship(
            from_label=label,
            from_key="id",
            from_value=parent_id,
            to_label="File",
            to_key="id",
            to_value=file_node.id,
            rel_type="CONTAIN",
        )

    async def _create_class_from_symbol(
        self,
        class_symbol: ClassSymbol,
        file_id: str,
        file_path: str,
        language: str,
        repo_name: str,
    ) -> str:
        """从 ClassSymbol 创建 Class 节点.

        Returns:
            创建的 Class 节点ID
        """
        class_node_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

        class_node = Class(
            id=class_node_id,
            name=class_symbol.name,
            type="Class",
            file_path=file_path,
            start_line=class_symbol.start_line,
            end_line=class_symbol.end_line,
            language=language,
            code=class_symbol.code,
            docstring=class_symbol.docstring,
        )

        properties = class_node.to_dict()
        properties["repo"] = repo_name
        properties = self._filter_properties(properties)

        await self._neo4j.merge_node(
            label="Class",
            key_property="id",
            key_value=class_node_id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        await self._neo4j.create_relationship(
            from_label="File",
            from_key="id",
            from_value=file_id,
            to_label="Class",
            to_key="id",
            to_value=class_node_id,
            rel_type="CONTAIN",
        )

        return class_node_id

    async def _create_method_from_symbol(
        self,
        method_symbol: MethodSymbol,
        parent_id: str,
        file_path: str,
        language: str,
        repo_name: str,
        class_name: str = "",
    ) -> str:
        """从 MethodSymbol 创建 Method 节点.

        Returns:
            创建的 Method 节点ID
        """
        if class_name:
            method_node_id = f"method_{repo_name}_{file_path}_{class_name}_{method_symbol.name}"
        else:
            method_node_id = f"method_{repo_name}_{file_path}_{method_symbol.name}"

        method_node = Method(
            id=method_node_id,
            name=method_symbol.name,
            type="Method",
            file_path=file_path,
            start_line=method_symbol.start_line,
            end_line=method_symbol.end_line,
            language=language,
            code=method_symbol.code,
            docstring=method_symbol.docstring,
            class_id=parent_id if "class_" in parent_id else None,
        )

        properties = method_node.to_dict()
        properties["repo"] = repo_name
        properties = self._filter_properties(properties)

        await self._neo4j.merge_node(
            label="Method",
            key_property="id",
            key_value=method_node_id,
            properties=properties,
        )

        # 确定父节点标签
        parent_label = "Class" if "class_" in parent_id else "File"

        # 创建 CONTAIN 关系
        await self._neo4j.create_relationship(
            from_label=parent_label,
            from_key="id",
            from_value=parent_id,
            to_label="Method",
            to_key="id",
            to_value=method_node_id,
            rel_type="CONTAIN",
        )

        return method_node_id

    def _is_supported_language(self, suffix: str) -> bool:
        """检查是否支持该语言."""
        from app.domain.parser.tree_sitter_parser import TreeSitterParser
        return suffix.lower() in TreeSitterParser.LANGUAGE_MAP

    def _get_parent_directory_id(
        self, file_path: str, directories: List[Directory], repo_id: str
    ) -> str:
        """获取文件所在目录的ID."""
        if "/" not in file_path and "\\" not in file_path:
            return repo_id

        parent_path = os.path.dirname(file_path).replace("\\", "/")
        if parent_path == ".":
            return repo_id

        for directory in directories:
            if directory.path == parent_path:
                return directory.id

        return repo_id

    def _get_parent_id(self, directory_path: str, repo_id: str) -> Optional[str]:
        """获取目录的父节点ID."""
        if "/" not in directory_path and "\\" not in directory_path:
            return repo_id

        parent_path = os.path.dirname(directory_path).replace("\\", "/")
        if parent_path == ".":
            return repo_id

        return f"dir_{repo_id.replace('repo_', '')}_{parent_path}"

    def _filter_properties(self, properties: Dict) -> Dict:
        """过滤属性，只保留基本类型.

        Neo4j 只支持基本类型（字符串、数字、布尔值、日期）和这些类型的数组。
        过滤掉字典、None 值和嵌套对象。
        """
        filtered = {}
        for key, value in properties.items():
            if value is None:
                continue
            # 跳过所有字典类型（Neo4j不支持）
            if isinstance(value, dict):
                continue
            # 跳过所有列表类型（除非是纯基本类型列表）
            if isinstance(value, list):
                # 只保留非空且元素都是基本类型的列表
                if value and all(not isinstance(item, (dict, list)) for item in value):
                    filtered[key] = value
                continue
            # 基本类型
            filtered[key] = value
        return filtered
