"""仓库遍历阶段处理器."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from gitignore_parser import parse_gitignore

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Directory, File, Repository
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult

logger = logging.getLogger(__name__)


@dataclass
class TraversalResult:
    """遍历结果."""

    repository: Repository
    directories: List[Directory] = field(default_factory=list)
    files: List[File] = field(default_factory=list)
    total_files: int = 0
    total_directories: int = 0


class RepoTraversalStage(PipelineStageHandler):
    """仓库遍历阶段处理器."""

    stage = PipelineStage.REPO_TRAVERSAL

    def __init__(self):
        self.settings = get_settings()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行仓库遍历.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            result = self._traverse_repository(context.repo_path, context.repo_name)

            # 保存结果到上下文
            context.data["traversal_result"] = result
            context.data["repository"] = result.repository
            context.data["directories"] = result.directories
            context.data["files"] = result.files

            metadata = {
                "total_files": result.total_files,
                "total_directories": result.total_directories,
                "repo_path": context.repo_path,
            }

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Scanned {result.total_files} files in {result.total_directories} directories",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"Repository traversal failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    def _traverse_repository(
        self,
        repo_path: str,
        repo_name: str,
    ) -> TraversalResult:
        """遍历仓库文件系统.

        Args:
            repo_path: 仓库路径
            repo_name: 仓库名称

        Returns:
            遍历结果
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

        # 加载 .gitignore
        gitignore_path = repo_root / ".gitignore"
        matches_gitignore = None
        if gitignore_path.exists():
            try:
                matches_gitignore = parse_gitignore(gitignore_path)
            except Exception as e:
                logger.warning(f"Failed to parse .gitignore: {e}")

        directories: List[Directory] = []
        files: List[File] = []

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
                    files.append(file_node)

            except Exception as e:
                logger.warning(f"Error processing path {path}: {e}")
                continue

        return TraversalResult(
            repository=repository,
            directories=directories,
            files=files,
            total_files=len(files),
            total_directories=len(directories),
        )

    def _should_ignore(
        self,
        str_path: str,
        path: Path,
        matches_gitignore: Optional[callable],
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
        import fnmatch

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
