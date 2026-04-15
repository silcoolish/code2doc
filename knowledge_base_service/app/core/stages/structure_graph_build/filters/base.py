"""文件过滤器抽象基类."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FilterResult:
    """过滤结果.

    Attributes:
        should_ignore: 是否应该忽略该文件/目录
        reason: 忽略原因（如果被忽略）
    """

    should_ignore: bool
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        """返回是否应该忽略."""
        return self.should_ignore


class FileFilter(ABC):
    """文件过滤器抽象基类.

    所有文件过滤器必须继承此类并实现 should_filter 方法。
    过滤器用于决定文件或目录是否应该被包含在遍历结果中。

    Example:
        class MyFilter(FileFilter):
            def should_filter(self, path: Path, relative_path: str) -> FilterResult:
                if path.suffix == '.tmp':
                    return FilterResult(should_ignore=True, reason="临时文件")
                return FilterResult(should_ignore=False)
    """

    @abstractmethod
    def should_filter(self, path: Path, relative_path: str) -> FilterResult:
        """判断给定路径是否应该被过滤.

        Args:
            path: 文件的绝对路径（Path 对象）
            relative_path: 相对于仓库根目录的路径字符串

        Returns:
            FilterResult: 过滤结果，包含是否应该忽略及原因
        """
        ...

    def __and__(self, other: "FileFilter") -> "CompositeFilter":
        """使用 & 运算符组合过滤器（链式过滤）.

        组合后的过滤器会依次检查每个过滤器，
        只要有一个过滤器认为应该忽略，就返回忽略。

        Args:
            other: 另一个文件过滤器

        Returns:
            CompositeFilter: 组合后的过滤器
        """
        return CompositeFilter([self, other])


class CompositeFilter(FileFilter):
    """组合过滤器.

    将多个过滤器组合在一起，按顺序执行。
    只要有一个过滤器认为应该忽略，就返回忽略结果。
    """

    def __init__(self, filters: list[FileFilter]):
        """初始化组合过滤器.

        Args:
            filters: 过滤器列表，按顺序执行
        """
        self._filters = filters

    def should_filter(self, path: Path, relative_path: str) -> FilterResult:
        """依次执行所有过滤器.

        Args:
            path: 文件的绝对路径
            relative_path: 相对于仓库根目录的路径

        Returns:
            FilterResult: 第一个返回忽略的过滤器结果，或允许通过
        """
        for filter_item in self._filters:
            result = filter_item.should_filter(path, relative_path)
            if result.should_ignore:
                return result
        return FilterResult(should_ignore=False)

    def add_filter(self, filter_item: FileFilter) -> "CompositeFilter":
        """添加新的过滤器到链尾.

        Args:
            filter_item: 要添加的过滤器

        Returns:
            self: 支持链式调用
        """
        self._filters.append(filter_item)
        return self
