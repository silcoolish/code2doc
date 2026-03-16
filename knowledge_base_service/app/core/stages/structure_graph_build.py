"""结构图构建阶段处理器."""

import logging
from typing import Dict, List, Any

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Class, Method, File, Directory, Repository
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_neo4j_client
from app.domain.parser.code_parser import ParseResult

logger = logging.getLogger(__name__)


class StructureGraphBuildStage(PipelineStageHandler):
    """结构图构建阶段处理器."""

    stage = PipelineStage.STRUCTURE_GRAPH_BUILD

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行结构图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            neo4j = get_neo4j_client()

            # 获取数据
            repository: Repository = context.data.get("repository")
            directories: List[Directory] = context.data.get("directories", [])
            files: List[File] = context.data.get("files", [])
            parsed_results: Dict[str, ParseResult] = context.data.get("parsed_results", {})

            created_nodes = {
                "repositories": 0,
                "directories": 0,
                "files": 0,
                "classes": 0,
                "methods": 0,
            }

            # 1. 创建 Repository 节点
            await self._create_repository(neo4j, repository)
            created_nodes["repositories"] += 1
            logger.info(f"Created Repository node: {repository.name}")

            # 2. 创建 Directory 节点和关系
            for directory in directories:
                await self._create_directory(neo4j, directory, repository.id)
                created_nodes["directories"] += 1

            logger.info(f"Created {created_nodes['directories']} Directory nodes")

            # 3. 创建 File 节点和关系
            for file_node in files:
                parent_id = self._get_parent_directory_id(file_node.path, directories, repository.id)
                await self._create_file(neo4j, file_node, parent_id)
                created_nodes["files"] += 1

            logger.info(f"Created {created_nodes['files']} File nodes")

            # 4. 创建 Class 和 Method 节点
            for file_path, parse_result in parsed_results.items():
                file_id = f"file_{context.repo_name}_{file_path}"

                # 创建 Class 节点
                for class_symbol in parse_result.classes:
                    class_node = Class(
                        id=f"class_{context.repo_name}_{file_path}_{class_symbol.name}",
                        name=class_symbol.name,
                        type="Class",
                        file_path=file_path,
                        start_line=class_symbol.start_line,
                        end_line=class_symbol.end_line,
                        language=parse_result.language,
                        code=class_symbol.code,
                        docstring=class_symbol.docstring,
                    )
                    await self._create_class(neo4j, class_node, file_id)
                    created_nodes["classes"] += 1

                    # 创建 Method 节点（类中的方法）
                    for method_symbol in class_symbol.methods:
                        method_node = Method(
                            id=f"method_{context.repo_name}_{file_path}_{class_symbol.name}_{method_symbol.name}",
                            name=method_symbol.name,
                            type="Method",
                            file_path=file_path,
                            start_line=method_symbol.start_line,
                            end_line=method_symbol.end_line,
                            language=parse_result.language,
                            code=method_symbol.code,
                            docstring=method_symbol.docstring,
                            class_id=class_node.id,
                        )
                        await self._create_method(neo4j, method_node, class_node.id)
                        created_nodes["methods"] += 1

                # 创建独立 Method 节点
                for method_symbol in parse_result.methods:
                    method_node = Method(
                        id=f"method_{context.repo_name}_{file_path}_{method_symbol.name}",
                        name=method_symbol.name,
                        type="Method",
                        file_path=file_path,
                        start_line=method_symbol.start_line,
                        end_line=method_symbol.end_line,
                        language=parse_result.language,
                        code=method_symbol.code,
                        docstring=method_symbol.docstring,
                    )
                    await self._create_method(neo4j, method_node, file_id)
                    created_nodes["methods"] += 1

            logger.info(f"Created {created_nodes['classes']} Class nodes")
            logger.info(f"Created {created_nodes['methods']} Method nodes")

            # 保存节点映射到上下文
            context.data["created_nodes"] = created_nodes

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Structure graph built successfully",
                metadata=created_nodes,
            )

        except Exception as e:
            logger.exception(f"Structure graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _create_repository(self, neo4j, repository: Repository) -> None:
        """创建 Repository 节点."""
        properties = repository.to_dict()
        properties["repo"] = repository.name
        await neo4j.merge_node(
            label="Repository",
            key_property="id",
            key_value=repository.id,
            properties=properties,
        )

    async def _create_directory(self, neo4j, directory: Directory, repo_id: str) -> None:
        """创建 Directory 节点和关系."""
        properties = directory.to_dict()
        properties["repo"] = repo_id.replace("repo_", "")

        await neo4j.merge_node(
            label="Directory",
            key_property="id",
            key_value=directory.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        parent_id = self._get_parent_id(directory.path, repo_id)
        if parent_id:
            await neo4j.create_relationship(
                from_label="Directory" if "/" in directory.path else "Repository",
                from_key="id",
                from_value=parent_id,
                to_label="Directory",
                to_key="id",
                to_value=directory.id,
                rel_type="CONTAIN",
            )

    async def _create_file(self, neo4j, file_node: File, parent_id: str) -> None:
        """创建 File 节点和关系."""
        properties = file_node.to_dict()
        properties["repo"] = parent_id.replace("repo_", "").split("_dir_")[0]

        await neo4j.merge_node(
            label="File",
            key_property="id",
            key_value=file_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        label = "Directory" if "dir_" in parent_id else "Repository"
        await neo4j.create_relationship(
            from_label=label,
            from_key="id",
            from_value=parent_id,
            to_label="File",
            to_key="id",
            to_value=file_node.id,
            rel_type="CONTAIN",
        )

    async def _create_class(self, neo4j, class_node: Class, file_id: str) -> None:
        """创建 Class 节点和关系."""
        properties = class_node.to_dict()
        properties["repo"] = file_id.split("_")[1]

        await neo4j.merge_node(
            label="Class",
            key_property="id",
            key_value=class_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        await neo4j.create_relationship(
            from_label="File",
            from_key="id",
            from_value=file_id,
            to_label="Class",
            to_key="id",
            to_value=class_node.id,
            rel_type="CONTAIN",
        )

    async def _create_method(self, neo4j, method_node: Method, parent_id: str) -> None:
        """创建 Method 节点和关系."""
        properties = method_node.to_dict()
        properties["repo"] = parent_id.split("_")[1]

        await neo4j.merge_node(
            label="Method",
            key_property="id",
            key_value=method_node.id,
            properties=properties,
        )

        # 确定父节点标签
        parent_label = "Class" if "class_" in parent_id else "File"

        # 创建 CONTAIN 关系
        await neo4j.create_relationship(
            from_label=parent_label,
            from_key="id",
            from_value=parent_id,
            to_label="Method",
            to_key="id",
            to_value=method_node.id,
            rel_type="CONTAIN",
        )

    def _get_parent_directory_id(self, file_path: str, directories: List[Directory], repo_id: str) -> str:
        """获取文件所在目录的ID."""
        if "/" not in file_path and "\\" not in file_path:
            return repo_id

        parent_path = str(Path(file_path).parent).replace("\\", "/")
        if parent_path == ".":
            return repo_id

        for directory in directories:
            if directory.path == parent_path:
                return directory.id

        return repo_id

    def _get_parent_id(self, directory_path: str, repo_id: str) -> str:
        """获取目录的父节点ID."""
        if "/" not in directory_path and "\\" not in directory_path:
            return repo_id

        parent_path = str(Path(directory_path).parent).replace("\\", "/")
        if parent_path == ".":
            return repo_id

        return f"dir_{repo_id.replace('repo_', '')}_{parent_path}"
