"""模式匹配文件过滤器."""

import fnmatch
import logging
from pathlib import Path
from typing import List

from .base import FileFilter, FilterResult

logger = logging.getLogger(__name__)


class PatternFilter(FileFilter):
    """基于模式匹配的文件过滤器.

    支持 glob 风格的模式匹配，如:
    - *.pyc: 匹配所有 .pyc 文件
    - __pycache__/: 匹配目录
    - **/node_modules: 匹配任意深度的 node_modules 目录
    - build/**: 匹配 build 目录下的所有内容

    Attributes:
        patterns: 要匹配的模式列表
        name: 过滤器名称（用于日志和调试）
    """

    def __init__(self, patterns: List[str], name: str = "PatternFilter"):
        """初始化模式过滤器.

        Args:
            patterns: 模式字符串列表
            name: 过滤器标识名称
        """
        self.patterns = patterns
        self.name = name

    def should_filter(self, path: Path, relative_path: str) -> FilterResult:
        """检查路径是否匹配任何排除模式.

        Args:
            path: 文件的绝对路径
            relative_path: 相对于仓库根目录的路径

        Returns:
            FilterResult: 如果匹配任何模式则返回忽略结果
        """
        # 统一使用正斜杠进行匹配
        normalized_path = relative_path.replace("\\", "/")
        path_name = path.name

        for pattern in self.patterns:
            if self._match_pattern(normalized_path, path_name, pattern):
                return FilterResult(
                    should_ignore=True,
                    reason=f"Matched pattern '{pattern}' in {self.name}",
                )

        return FilterResult(should_ignore=False)

    def _match_pattern(
        self, normalized_path: str, path_name: str, pattern: str
    ) -> bool:
        """匹配单个模式.

        支持以下模式语法:
        - **/prefix: 匹配任意深度的以 prefix 结尾的路径
        - suffix/**: 匹配以 suffix 开头的目录及其所有内容
        - *: 匹配任意字符（非路径分隔符）
        - **: 匹配任意路径层级

        Args:
            normalized_path: 标准化的相对路径（正斜杠）
            path_name: 文件或目录名
            pattern: 匹配模式

        Returns:
            bool: 是否匹配
        """
        # 处理 **/ 前缀（匹配任意深度）
        if pattern.startswith("**/"):
            suffix = pattern[3:]
            # 检查路径本身或任何父级目录名是否匹配
            if fnmatch.fnmatch(normalized_path, suffix):
                return True
            # 检查路径的各级目录
            path_parts = normalized_path.split("/")
            for part in path_parts:
                if fnmatch.fnmatch(part, suffix):
                    return True
            return False

        # 处理 /** 后缀（匹配目录及其内容）
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            # 检查路径是否以 prefix 开头，或路径中包含 prefix/
            if normalized_path.startswith(prefix + "/"):
                return True
            if normalized_path == prefix:
                return True
            return False

        # 处理目录匹配（以 / 结尾的模式）
        if pattern.endswith("/"):
            dir_pattern = pattern[:-1]
            # 检查路径名或完整路径是否匹配
            if fnmatch.fnmatch(path_name, dir_pattern):
                return True
            if fnmatch.fnmatch(normalized_path, dir_pattern):
                return True
            return False

        # 标准通配符匹配
        if fnmatch.fnmatch(normalized_path, pattern):
            return True
        if fnmatch.fnmatch(path_name, pattern):
            return True

        return False

    @classmethod
    def default_exclude_patterns(cls) -> "PatternFilter":
        """创建默认的排除模式过滤器.

        包含常见的应该忽略的文件和目录模式。

        Returns:
            PatternFilter: 预配置的默认过滤器
        """
        default_patterns = [
            # 版本控制
            ".git/",
            ".git/**",
            ".svn/",
            ".hg/",
            # Python
            "__pycache__/",
            "__pycache__/**",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".pytest_cache/",
            ".pytest_cache/**",
            ".mypy_cache/",
            ".mypy_cache/**",
            ".tox/",
            ".tox/**",
            "*.egg-info/",
            "*.egg-info/**",
            ".eggs/",
            ".eggs/**",
            "venv/",
            "venv/**",
            ".venv/",
            ".venv/**",
            "env/",
            "env/**",
            # Node.js
            "node_modules/",
            "node_modules/**",
            "bower_components/",
            "bower_components/**",
            "dist/",
            "dist/**",
            "build/",
            "build/**",
            # IDE
            ".idea/",
            ".idea/**",
            ".vscode/",
            ".vscode/**",
            "*.swp",
            "*.swo",
            "*~",
            # 操作系统
            ".DS_Store",
            "Thumbs.db",
            # 日志和临时文件
            "*.log",
            "*.tmp",
            "*.temp",
            ".cache/",
            ".cache/**",
            # 测试和覆盖率
            "htmlcov/",
            "htmlcov/**",
            ".coverage",
            # 文档构建
            "_build/",
            "_build/**",
            "site/",
            "site/**",
        ]

        return cls(patterns=default_patterns, name="DefaultExcludePatterns")

    @classmethod
    def from_settings(cls, settings_patterns: List[str]) -> "PatternFilter":
        """从设置创建过滤器.

        Args:
            settings_patterns: 配置中的模式列表

        Returns:
            PatternFilter: 使用配置模式的过滤器
        """
        return cls(patterns=settings_patterns, name="SettingsPatterns")
