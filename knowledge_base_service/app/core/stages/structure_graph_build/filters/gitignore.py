"""Gitignore 文件过滤器."""

import logging
from pathlib import Path
from typing import Callable, Optional

from gitignore_parser import parse_gitignore

from .base import FileFilter, FilterResult

logger = logging.getLogger(__name__)


class GitignoreFilter(FileFilter):
    """基于 .gitignore 文件的过滤器.

    解析仓库根目录下的 .gitignore 文件，根据其中的模式过滤文件。
    如果 .gitignore 文件不存在或解析失败，则允许所有文件通过。

    Attributes:
        matches_gitignore: gitignore 解析后的匹配函数
    """

    def __init__(self, gitignore_path: Path):
        """初始化 Gitignore 过滤器.

        Args:
            gitignore_path: .gitignore 文件的完整路径
        """
        self.gitignore_path = gitignore_path
        self.matches_gitignore: Optional[Callable[[Path], bool]] = None

        if gitignore_path.exists():
            try:
                self.matches_gitignore = parse_gitignore(gitignore_path)
                logger.info(f"Loaded .gitignore from {gitignore_path}")
            except Exception as e:
                logger.warning(f"Failed to parse .gitignore: {e}")
        else:
            logger.debug(f"No .gitignore found at {gitignore_path}")

    def should_filter(self, path: Path, relative_path: str) -> FilterResult:
        """检查路径是否匹配 .gitignore 规则.

        Args:
            path: 文件的绝对路径
            relative_path: 相对于仓库根目录的路径（未使用，但保持接口一致）

        Returns:
            FilterResult: 如果匹配 gitignore 则返回忽略结果
        """
        if self.matches_gitignore is None:
            return FilterResult(should_ignore=False)

        try:
            if self.matches_gitignore(path):
                return FilterResult(
                    should_ignore=True,
                    reason=f"Matched .gitignore pattern in {self.gitignore_path.name}",
                )
        except Exception as e:
            logger.warning(f"Error matching gitignore for {path}: {e}")

        return FilterResult(should_ignore=False)

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "GitignoreFilter":
        """从仓库根目录自动创建过滤器.

        自动查找仓库根目录下的 .gitignore 文件。

        Args:
            repo_root: 仓库根目录路径

        Returns:
            GitignoreFilter: 配置好的过滤器实例
        """
        gitignore_path = repo_root / ".gitignore"
        return cls(gitignore_path)
