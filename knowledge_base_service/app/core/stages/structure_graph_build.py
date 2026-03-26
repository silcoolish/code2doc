"""结构图构建阶段处理器.

该阶段合并了仓库遍历、代码解析和结构图构建:
1. 遍历仓库文件系统
2. 直接创建 Repository、Directory、File 等结构节点并保存到 Neo4j
3. 解析代码文件提取类和方法
4. 创建 Class、Method 节点并保存到 Neo4j
5. 在上下文中只保存节点ID信息

后续阶段需要具体信息时，应通过节点ID从图数据库中查询。
"""

import asyncio
import fnmatch
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable

from gitignore_parser import parse_gitignore

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Class, Directory, File, Method, Repository
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.analyzer import get_analyzer_for_file, ParsedSymbol, is_supported_file
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)


class StructureGraphBuildStage(PipelineStageHandler):
    """结构图构建阶段处理器.

    将仓库遍历、代码解析和图构建合并为一个阶段：
    1. 遍历仓库文件系统
    2. 直接创建结构节点并存储到Neo4j
    3. 解析代码文件创建 Class/Method 节点
    上下文中只保留节点ID引用。

    Input (context.data):
        - 无需前置数据，从 context.repo_path 和 context.repo_name 读取

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
        self.graph_db: Optional[GraphDatabaseClient] = None

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行结构图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self.graph_db = get_graph_db_client()

            # 1. 遍历仓库并直接创建结构节点
            repository, directories, files = await self._traverse_and_create_structure(
                context.repo_path, context.repo_name
            )

            # 节点ID记录（只存ID，不存完整数据）
            node_ids = {
                "repository_id": repository.id,
                "directory_ids": [d.id for d in directories],
                "file_ids": [],
                "class_ids": [],
                "method_ids": [],
            }

            logger.info(f"Created Repository node: {repository.name}")
            logger.info(f"Created {len(directories)} Directory nodes")

            # 2. 解析代码文件并创建 File/Class/Method 节点
            file_node_ids, class_node_ids, method_node_ids = await self._process_code_files(
                files, directories, repository.id, context.repo_name, context.repo_path
            )
            node_ids["file_ids"] = file_node_ids
            node_ids["class_ids"] = class_node_ids
            node_ids["method_ids"] = method_node_ids

            # 3. 保存节点ID到上下文（而非完整数据）
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
                message=f"Structure graph built: {len(directories)} directories, "
                        f"{len(file_node_ids)} files, "
                        f"{len(class_node_ids)} classes, "
                        f"{len(method_node_ids)} methods",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"Structure graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _traverse_and_create_structure(
        self, repo_path: str, repo_name: str
    ) -> tuple[Repository, List[Directory], List[File]]:
        """遍历仓库并直接创建结构节点.

        Args:
            repo_path: 仓库路径
            repo_name: 仓库名称

        Returns:
            (repository, directories, code_files)
        """
        repo_root = Path(repo_path).resolve()
        if not repo_root.exists():
            raise FileNotFoundError(f"Repository path not found: {repo_path}")

        # 创建 Repository 节点
        repository = Repository(
            id=f"repo_{repo_name}",
            name=repo_name,
            type="Repository",
            path=str(repo_root),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self._create_repository(repository)

        # 加载 .gitignore
        gitignore_path = repo_root / ".gitignore"
        matches_gitignore: Optional[Callable] = None
        if gitignore_path.exists():
            try:
                matches_gitignore = parse_gitignore(gitignore_path)
            except Exception as e:
                logger.warning(f"Failed to parse .gitignore: {e}")

        directories: List[Directory] = []
        code_files: List[File] = []

        # 遍历目录
        for path in repo_root.rglob("*"):
            try:
                relative_path = path.relative_to(repo_root)
                str_path = str(relative_path).replace("\\", "/")

                # 检查是否应该忽略
                if self._should_ignore(str_path, path, matches_gitignore):
                    continue

                if path.is_dir():
                    # 创建 Directory 节点
                    directory = Directory(
                        id=f"dir_{repo_name}_{str_path}",
                        name=path.name,
                        type="Directory",
                        path=str_path,
                    )
                    await self._create_directory(directory, repository.id)
                    directories.append(directory)

                elif path.is_file():
                    # 确定文件类型
                    file_type = self._determine_file_type(path)
                    suffix = path.suffix

                    # 创建 File 节点
                    file_node = File(
                        id=f"file_{repo_name}_{str_path}",
                        name=path.name,
                        type="File",
                        path=str_path,
                        file_type=file_type,
                        suffix=suffix,
                    )
                    # 只收集代码文件用于后续解析
                    if file_type == "code":
                        code_files.append(file_node)

            except Exception as e:
                logger.warning(f"Error processing path {path}: {e}")
                continue

        return repository, directories, code_files

    def _should_ignore(
        self,
        str_path: str,
        path: Path,
        matches_gitignore: Optional[Callable],
    ) -> bool:
        """检查路径是否应该被忽略.

        Args:
            str_path: 相对路径字符串
            path: Path 对象
            matches_gitignore: gitignore 匹配函数

        Returns:
            是否应该忽略
        """
        # 检查默认排除模式
        for pattern in self.settings.default_exclude_patterns:
            if self._match_pattern(str_path, pattern):
                return True

        # 检查 .gitignore
        if matches_gitignore and matches_gitignore(path):
            return True

        # 检查用户配置的排除模式
        config_patterns = self.settings.default_exclude_patterns
        for pattern in config_patterns:
            if self._match_pattern(str_path, pattern):
                return True

        return False

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """匹配路径模式.

        Args:
            path: 文件路径
            pattern: 匹配模式

        Returns:
            是否匹配
        """
        # 处理 **/ 前缀
        if pattern.startswith("**/"):
            suffix = pattern[3:]
            return fnmatch.fnmatch(path, suffix) or any(
                fnmatch.fnmatch(str(p), suffix)
                for p in Path(path).parents
            )

        # 处理 /** 后缀
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return path.startswith(prefix)

        # 处理通配符
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(
            Path(path).name, pattern
        )

    def _determine_file_type(self, path: Path) -> str:
        """确定文件类型.

        Args:
            path: 文件路径

        Returns:
            文件类型: code / doc / config
        """
        suffix = path.suffix.lower()

        # 代码文件
        code_extensions = {
            ".py", ".java", ".js", ".ts", ".go", ".rs", ".cpp", ".c", ".h",
            ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
            ".r", ".m", ".mm", ".groovy", ".clj", ".erl", ".ex", ".exs",
        }

        # 文档文件
        doc_extensions = {
            ".md", ".rst", ".txt", ".adoc", ".org",
        }

        # 配置文件
        config_extensions = {
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
            ".conf", ".properties", ".xml", ".env", ".env.example",
        }

        if suffix in code_extensions:
            return "code"
        elif suffix in doc_extensions:
            return "doc"
        elif suffix in config_extensions:
            return "config"
        else:
            return "other"

    async def _process_code_files(
        self,
        code_files: List[File],
        directories: List[Directory],
        repo_id: str,
        repo_name: str,
        repo_path: str,
    ) -> tuple[List[str], List[str], List[str]]:
        """处理代码文件：解析并创建节点.

        Args:
            code_files: 代码文件列表（已过滤的代码类型文件）
            directories: 目录列表
            repo_id: 仓库ID
            repo_name: 仓库名称
            repo_path: 仓库路径

        Returns:
            (file_ids, class_ids, method_ids)
        """
        # 过滤出支持语言的代码文件
        code_files = [
            f for f in code_files
            if is_supported_file(f.path)
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

        analyzer = get_analyzer_for_file(file_node.path)
        if not analyzer:
            return file_ids, class_ids, method_ids

        parse_result = analyzer.parse_for_structure(file_node.path, content)
        if not parse_result.success:
            logger.warning(f"Failed to parse {file_node.path}: {parse_result.error}")
            return file_ids, class_ids, method_ids

        file_id = file_node.id

        # 创建 Class/Struct/Interface/Enum/Trait 节点，并建立类名到ID的映射
        class_name_to_id: dict = {}
        for class_symbol in parse_result.classes:
            class_node_id = await self._create_class_from_symbol(
                class_symbol, file_id, file_node.path, parse_result.language, repo_name
            )
            class_ids.append(class_node_id)
            class_name_to_id[class_symbol.name] = class_node_id

        # 创建 Method 节点
        for method_symbol in parse_result.methods:
            # 根据 parent_name 判断是类方法还是独立函数
            if method_symbol.parent_name and method_symbol.parent_name in class_name_to_id:
                # 类方法
                class_node_id = class_name_to_id[method_symbol.parent_name]
                method_node_id = await self._create_method_from_symbol(
                    method_symbol,
                    class_node_id,
                    file_node.path,
                    parse_result.language,
                    repo_name,
                    class_name=method_symbol.parent_name,
                )
            else:
                # 独立函数
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

        await self.graph_db.merge_node(
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

        await self.graph_db.merge_node(
            label="Directory",
            key_property="id",
            key_value=directory.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        parent_id = self._get_parent_id(directory.path, repo_id)
        if parent_id:
            await self.graph_db.create_relationship(
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

        await self.graph_db.merge_node(
            label="File",
            key_property="id",
            key_value=file_node.id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        label = "Directory" if "dir_" in parent_id else "Repository"
        await self.graph_db.create_relationship(
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
        class_symbol: ParsedSymbol,
        file_id: str,
        file_path: str,
        language: str,
        repo_name: str,
    ) -> str:
        """从 ParsedSymbol 创建 Class 节点.

        Returns:
            创建的 Class 节点ID
        """
        class_node_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

        # 根据 symbol_type 确定节点类型
        node_type = "Class"
        if class_symbol.symbol_type == "struct":
            node_type = "Struct"
        elif class_symbol.symbol_type == "interface":
            node_type = "Interface"
        elif class_symbol.symbol_type == "enum":
            node_type = "Enum"
        elif class_symbol.symbol_type == "trait":
            node_type = "Trait"

        class_node = Class(
            id=class_node_id,
            name=class_symbol.name,
            type=node_type,
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

        await self.graph_db.merge_node(
            label="Class",
            key_property="id",
            key_value=class_node_id,
            properties=properties,
        )

        # 创建 CONTAIN 关系
        await self.graph_db.create_relationship(
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
        method_symbol: ParsedSymbol,
        parent_id: str,
        file_path: str,
        language: str,
        repo_name: str,
        class_name: str = "",
    ) -> str:
        """从 ParsedSymbol 创建 Method 节点.

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

        await self.graph_db.merge_node(
            label="Method",
            key_property="id",
            key_value=method_node_id,
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
            to_value=method_node_id,
            rel_type="CONTAIN",
        )

        return method_node_id

    def _is_supported_language(self, suffix: str) -> bool:
        """检查是否支持该语言."""
        from app.domain.analyzer import get_analyzer_for_extension
        return get_analyzer_for_extension(suffix) is not None

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
