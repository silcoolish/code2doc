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
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.core.stages.structure_graph_build.filters import (
    FileFilter,
    FilterResult,
    GitignoreFilter,
    PatternFilter,
)
from app.domain.analyzer import ParsedSymbol, get_analyzer_for_file, is_supported_file
from app.domain.graph import Class, Directory, File, GraphHelper, Method, Repository
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

logger = logging.getLogger(__name__)


class FilterChain:
    """文件过滤器链.

    组合多个过滤器，按顺序执行过滤检查。
    提供统一的过滤接口，便于管理和扩展。
    """

    def __init__(self):
        self._filters: List[FileFilter] = []

    def add_filter(self, filter_item: FileFilter) -> "FilterChain":
        """添加过滤器到链尾.

        Args:
            filter_item: 要添加的过滤器

        Returns:
            self: 支持链式调用
        """
        self._filters.append(filter_item)
        return self

    def should_filter(self, path: Path, relative_path: str) -> FilterResult:
        """执行过滤检查.

        依次调用所有过滤器，直到有一个过滤器返回忽略。

        Args:
            path: 文件的绝对路径
            relative_path: 相对于仓库根目录的路径

        Returns:
            FilterResult: 过滤结果
        """
        for filter_item in self._filters:
            result = filter_item.should_filter(path, relative_path)
            if result.should_ignore:
                return result
        return FilterResult(should_ignore=False)

    @classmethod
    def create_default_chain(cls, repo_root: Path) -> "FilterChain":
        """创建默认的过滤器链.

        默认链包含:
        1. 默认排除模式过滤器（忽略常见临时文件和目录）
        2. Gitignore 过滤器（根据 .gitignore 文件过滤）

        Args:
            repo_root: 仓库根目录路径

        Returns:
            FilterChain: 配置好的过滤器链
        """
        chain = cls()

        # 1. 添加默认排除模式过滤器
        chain.add_filter(PatternFilter.default_exclude_patterns())

        # 2. 添加 gitignore 过滤器
        chain.add_filter(GitignoreFilter.from_repo_root(repo_root))

        logger.info(f"Created default filter chain with {len(chain._filters)} filters")
        return chain


_EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".m": "objective-c",
    ".mm": "objective-c",
    ".groovy": "groovy",
    ".clj": "clojure",
    ".erl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
}


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
    weight = 3.0  # 文件遍历和解析，最耗时

    def __init__(self):
        self.settings = get_settings()
        graph_db = get_graph_db_client()
        self.graph_helper = GraphHelper(graph_db)

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行结构图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            # 从 context 获取 repo_id（初始化请求传入的）
            pipeline_repo_id = getattr(context, "repo_id", context.repo_name)

            # 1. 遍历仓库并直接创建结构节点
            context.stage_msg = "正在遍历仓库文件..."
            repository, directories, files, stats = await self._traverse_and_create_structure(
                context.repo_path, context.repo_name, pipeline_repo_id
            )

            # 节点ID记录（只存ID，不存完整数据）
            node_ids = {
                "repository_id": repository.id,
                "directory_ids": [d.id for d in directories],
                "file_ids": [],
                "class_ids": [],
                "method_ids": [],
            }

            context.stage_msg = f"已创建 {len(directories)} 个目录节点"
            logger.info(f"Created Repository node: {repository.name}")
            logger.info(f"Created {len(directories)} Directory nodes")

            # 2. 解析代码文件并创建 File/Class/Method 节点
            context.stage_msg = f"正在解析 {len(files)} 个代码文件..."
            file_node_ids, class_node_ids, method_node_ids = (
                await self._process_code_files(
                    files,
                    directories,
                    repository.id,
                    context.repo_name,
                    context.repo_path,
                    context,
                    pipeline_repo_id,
                )
            )
            node_ids["file_ids"] = file_node_ids
            node_ids["class_ids"] = class_node_ids
            node_ids["method_ids"] = method_node_ids

            # 3. 保存节点ID到上下文（而非完整数据）
            context.data["node_ids"] = node_ids

            # 4. 更新 Repository 节点的统计信息
            repository.total_files = stats["total_files"]
            repository.total_code_files = stats["total_code_files"]
            repository.total_lines = stats["total_lines"]
            repository.total_size = stats["total_size"]
            repository.languages = sorted(list(stats["languages"]))
            repository.language_distribution = stats["language_distribution"]
            repository.updated_at = datetime.utcnow()
            await self.graph_helper.create_repository(repository)
            logger.info(
                f"Updated Repository stats: {repository.total_files} files, "
                f"{repository.total_code_files} code files, {repository.total_lines} lines, "
                f"{repository.total_size} bytes, languages={repository.languages}"
            )

            # 统计信息
            metadata = {
                "repositories": 1,
                "directories": len(node_ids["directory_ids"]),
                "files": len(node_ids["file_ids"]),
                "classes": len(node_ids["class_ids"]),
                "methods": len(node_ids["method_ids"]),
            }

            context.stage_msg = f"结构图构建完成：{len(file_node_ids)} 个文件, {len(class_node_ids)} 个类, {len(method_node_ids)} 个方法"

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
        self, repo_path: str, repo_name: str, pipeline_repo_id: str
    ) -> tuple[Repository, List[Directory], List[File], Dict[str, Any]]:
        """遍历仓库并直接创建结构节点.

        Args:
            repo_path: 仓库路径
            repo_name: 仓库名称
            pipeline_repo_id: 初始化请求传入的repo_id

        Returns:
            (repository, directories, code_files, stats)
        """
        repo_root = Path(repo_path).resolve()
        if not repo_root.exists():
            raise FileNotFoundError(f"Repository path not found: {repo_path}")

        # 创建 Repository 节点（基础信息，统计信息在遍历完成后更新）
        repository = Repository(
            id=f"repo_{repo_name}",
            name=repo_name,
            type="Repository",
            repo_id=pipeline_repo_id,
            path=str(repo_root),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.graph_helper.create_repository(repository)

        # 创建默认过滤器链
        filter_chain = FilterChain.create_default_chain(repo_root)

        directories: List[Directory] = []
        dir_parent_ids: List[str] = []
        code_files: List[File] = []
        stats: Dict[str, Any] = {
            "total_files": 0,
            "total_code_files": 0,
            "total_lines": 0,
            "total_size": 0,
            "languages": set(),
            "language_distribution": {},
        }

        # 遍历目录（同步操作，大仓库可能阻塞事件循环）
        for path in repo_root.rglob("*"):
            try:
                relative_path = path.relative_to(repo_root)
                str_path = str(relative_path).replace("\\", "/")

                # 使用过滤器链检查是否应该忽略
                filter_result = filter_chain.should_filter(path, str_path)
                if filter_result.should_ignore:
                    logger.debug(f"Filtered out {str_path}: {filter_result.reason}")
                    continue

                if path.is_dir():
                    # 收集 Directory 节点（稍后批量创建）
                    directory = Directory(
                        id=f"dir_{repo_name}_{str_path}",
                        name=path.name,
                        type="Directory",
                        repo_id=pipeline_repo_id,
                        path=str_path,
                    )
                    parent_id = self._get_parent_id(directory.path, repository.id)
                    effective_parent_id = parent_id if parent_id else repository.id
                    directories.append(directory)
                    dir_parent_ids.append(effective_parent_id)

                elif path.is_file():
                    # 确定文件类型
                    file_type = self._determine_file_type(path)
                    suffix = path.suffix

                    # 累加全局统计
                    stats["total_files"] += 1
                    try:
                        stats["total_size"] += path.stat().st_size
                    except Exception as e:
                        logger.warning(f"Failed to get file size for {path}: {e}")

                    # 代码文件额外统计行数和语言分布
                    if file_type == "code":
                        stats["total_code_files"] += 1
                        try:
                            content = path.read_text(encoding="utf-8", errors="ignore")
                            stats["total_lines"] += len(content.splitlines())
                            lang = _EXTENSION_LANGUAGE_MAP.get(
                                suffix.lower(), suffix.lower().lstrip(".")
                            )
                            stats["languages"].add(lang)
                            stats["language_distribution"][lang] = (
                                stats["language_distribution"].get(lang, 0) + 1
                            )
                        except Exception as e:
                            logger.warning(f"Failed to read code file {path}: {e}")

                    # 收集 File 节点（稍后批量创建）
                    file_node = File(
                        id=f"file_{repo_name}_{str_path}",
                        name=path.name,
                        type="File",
                        repo_id=pipeline_repo_id,
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

        # 批量创建 Directory 节点和关系（单次UNWIND查询）
        if directories:
            await self.graph_helper.batch_create_directories(directories, dir_parent_ids)
            logger.info(f"Batch created {len(directories)} Directory nodes")

        return repository, directories, code_files, stats

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
            ".py",
            ".java",
            ".js",
            ".ts",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".scala",
            ".r",
            ".m",
            ".mm",
            ".groovy",
            ".clj",
            ".erl",
            ".ex",
            ".exs",
        }

        # 文档文件
        doc_extensions = {
            ".md",
            ".rst",
            ".txt",
            ".adoc",
            ".org",
        }

        # 配置文件
        config_extensions = {
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".properties",
            ".xml",
            ".env",
            ".env.example",
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
        context: PipelineContext,
        pipeline_repo_id: str = "",
    ) -> tuple[List[str], List[str], List[str]]:
        """处理代码文件：批量解析并批量创建节点.

        优化策略：
        1. 先并发解析所有文件（纯CPU/IO，不涉及数据库）
        2. 收集所有 File/Class/Method 节点
        3. 使用UNWIND批量写入Neo4j（减少网络往返）

        Args:
            code_files: 代码文件列表（已过滤的代码类型文件）
            directories: 目录列表
            repo_id: 仓库节点ID
            repo_name: 仓库名称
            repo_path: 仓库路径
            context: 流水线上下文
            pipeline_repo_id: 初始化请求传入的repo_id

        Returns:
            (file_ids, class_ids, method_ids)
        """
        # 过滤出支持语言的代码文件
        code_files = [f for f in code_files if is_supported_file(f.path)]

        total_files = len(code_files)
        file_ids: List[str] = []
        class_ids: List[str] = []
        method_ids: List[str] = []

        logger.info(f"Processing {total_files} code files...")

        # 批量处理
        batch_size = 50
        for i in range(0, total_files, batch_size):
            batch = code_files[i : i + batch_size]

            # 并发解析（不涉及数据库写入）
            tasks = [
                self._parse_file(
                    f, directories, repo_id, repo_name, repo_path, pipeline_repo_id
                )
                for f in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 收集待创建的节点
            files_to_create: List[File] = []
            file_parents: List[str] = []
            classes_to_create: List[Class] = []
            class_parents: List[str] = []
            methods_to_create: List[Method] = []
            method_parents: List[str] = []

            for file_node, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to parse {file_node.path}: {result}")
                    continue

                file_parent_id, classes, methods = result
                file_ids.append(file_node.id)
                files_to_create.append(file_node)
                file_parents.append(file_parent_id)

                for cls, cls_parent in classes:
                    class_ids.append(cls.id)
                    classes_to_create.append(cls)
                    class_parents.append(cls_parent)

                for method, method_parent in methods:
                    method_ids.append(method.id)
                    methods_to_create.append(method)
                    method_parents.append(method_parent)

            # 批量创建节点和关系（单次UNWIND查询）
            if files_to_create:
                await self.graph_helper.batch_create_files(files_to_create, file_parents)
            if classes_to_create:
                await self.graph_helper.batch_create_classes(classes_to_create, class_parents)
            if methods_to_create:
                await self.graph_helper.batch_create_methods(methods_to_create, method_parents)

            progress = min(100, int((i + len(batch)) / total_files * 100))
            context.stage_msg = (
                f"正在解析代码文件: {i + len(batch)}/{total_files} ({progress}%)"
            )
            logger.info(
                f"Processing progress: {progress}% ({i + len(batch)}/{total_files}), "
                f"batch: {len(files_to_create)} files, {len(classes_to_create)} classes, {len(methods_to_create)} methods"
            )

        context.stage_msg = f"已创建 {len(file_ids)} 个File节点, {len(class_ids)} 个Class节点, {len(method_ids)} 个Method节点"
        logger.info(f"Created {len(class_ids)} Class nodes")
        logger.info(f"Created {len(method_ids)} Method nodes")

        return file_ids, class_ids, method_ids

    async def _parse_file(
        self,
        file_node: File,
        directories: List[Directory],
        repo_id: str,
        repo_name: str,
        repo_path: str,
        pipeline_repo_id: str = "",
    ) -> tuple[str, list[tuple[Class, str]], list[tuple[Method, str]]]:
        """解析单个文件，返回待创建的节点数据（不写入数据库）.

        Args:
            file_node: 文件节点
            directories: 目录列表
            repo_id: 仓库节点ID
            repo_name: 仓库名称
            repo_path: 仓库路径
            pipeline_repo_id: 初始化请求传入的repo_id

        Returns:
            (file_parent_id, classes_with_parent_file_id, methods_with_parent_id)
        """
        # 获取父目录ID
        parent_id = self._get_parent_directory_id(file_node.path, directories, repo_id)

        # 读取文件内容（设置到 file_node.code 上，供批量创建使用）
        file_path = Path(repo_path) / file_node.path
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            file_node.code = content
        except Exception as e:
            logger.warning(f"Failed to read file {file_node.path}: {e}")
            return parent_id, [], []

        analyzer = get_analyzer_for_file(file_node.path)
        if not analyzer:
            return parent_id, [], []

        parse_result = analyzer.parse_for_structure(file_node.path, content)
        if not parse_result.success:
            logger.warning(f"Failed to parse {file_node.path}: {parse_result.error}")
            return parent_id, [], []

        file_id = file_node.id

        # 构建 Class 节点对象
        classes: list[tuple[Class, str]] = []
        class_name_to_id: dict[str, str] = {}
        for class_symbol in parse_result.classes:
            class_node = self._build_class_node(
                class_symbol, file_node.path, parse_result.language, repo_name, pipeline_repo_id
            )
            classes.append((class_node, file_id))
            class_name_to_id[class_symbol.name] = class_node.id

        # 构建 Method 节点对象
        methods: list[tuple[Method, str]] = []
        for method_symbol in parse_result.methods:
            if (
                method_symbol.parent_name
                and method_symbol.parent_name in class_name_to_id
            ):
                # 类方法
                class_node_id = class_name_to_id[method_symbol.parent_name]
                method_node = self._build_method_node(
                    method_symbol,
                    class_node_id,
                    file_node.path,
                    parse_result.language,
                    repo_name,
                    pipeline_repo_id,
                    class_name=method_symbol.parent_name,
                )
                methods.append((method_node, class_node_id))
            else:
                # 独立函数
                method_node = self._build_method_node(
                    method_symbol,
                    file_id,
                    file_node.path,
                    parse_result.language,
                    repo_name,
                    pipeline_repo_id,
                )
                methods.append((method_node, file_id))

        return parent_id, classes, methods

    def _build_class_node(
        self,
        class_symbol: ParsedSymbol,
        file_path: str,
        language: str,
        repo_name: str,
        pipeline_repo_id: str = "",
    ) -> Class:
        """从 ParsedSymbol 构建 Class 节点对象（不涉及数据库操作）.

        Args:
            class_symbol: 解析出的类符号
            file_path: 文件路径
            language: 编程语言
            repo_name: 仓库名称
            pipeline_repo_id: 初始化请求传入的repo_id

        Returns:
            Class 节点对象
        """
        class_node_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

        real_type = "Class"
        if class_symbol.symbol_type:
            real_type = class_symbol.symbol_type.capitalize()

        return Class(
            id=class_node_id,
            name=class_symbol.name,
            type="Class",
            repo_id=pipeline_repo_id,
            file_path=file_path,
            start_line=class_symbol.start_line,
            end_line=class_symbol.end_line,
            language=language,
            code=class_symbol.code,
            docstring=class_symbol.docstring,
            real_type=real_type,
        )

    def _build_method_node(
        self,
        method_symbol: ParsedSymbol,
        parent_id: str,
        file_path: str,
        language: str,
        repo_name: str,
        pipeline_repo_id: str = "",
        class_name: str = "",
    ) -> Method:
        """从 ParsedSymbol 构建 Method 节点对象（不涉及数据库操作）.

        Args:
            method_symbol: 解析出的方法符号
            parent_id: 父节点ID（Class 或 File）
            file_path: 文件路径
            language: 编程语言
            repo_name: 仓库名称
            pipeline_repo_id: 初始化请求传入的repo_id
            class_name: 所属类名（如果有）

        Returns:
            Method 节点对象
        """
        if class_name:
            method_node_id = (
                f"method_{repo_name}_{file_path}_{class_name}_{method_symbol.name}"
            )
        else:
            method_node_id = f"method_{repo_name}_{file_path}_{method_symbol.name}"

        return Method(
            id=method_node_id,
            name=method_symbol.name,
            type="Method",
            repo_id=pipeline_repo_id,
            file_path=file_path,
            start_line=method_symbol.start_line,
            end_line=method_symbol.end_line,
            language=language,
            code=method_symbol.code,
            docstring=method_symbol.docstring,
            class_id=parent_id if "class_" in parent_id else None,
        )

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
