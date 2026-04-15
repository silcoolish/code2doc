"""文件过滤器模块.

提供可扩展的文件过滤功能，用于结构图构建阶段的文件遍历。
"""

from .base import CompositeFilter, FileFilter, FilterResult
from .gitignore import GitignoreFilter
from .pattern import PatternFilter

__all__ = [
    "FileFilter",
    "FilterResult",
    "CompositeFilter",
    "GitignoreFilter",
    "PatternFilter",
]
