"""代码分析器抽象基类.

提供统一的代码分析接口，包括：
1. 结构图构建阶段的代码解析
2. 依赖图构建阶段的 import 提取
3. 依赖图构建阶段的方法调用提取
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ParsedSymbol:
    """解析的符号信息."""

    name: str
    symbol_type: str  # 'class', 'method', 'function'
    start_line: int
    end_line: int
    code: str
    docstring: str = ""
    parent_name: Optional[str] = None  # 对于类中的方法，记录所属类名
    modifiers: List[str] = field(default_factory=list)
    parameters: List[Dict[str, str]] = field(default_factory=list)
    return_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "name": self.name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "docstring": self.docstring,
            "parent_name": self.parent_name,
            "modifiers": self.modifiers,
            "parameters": self.parameters,
            "return_type": self.return_type,
        }


@dataclass
class StructureParseResult:
    """结构图构建阶段的解析结果."""

    file_path: str
    language: str
    classes: List[ParsedSymbol] = field(default_factory=list)
    methods: List[ParsedSymbol] = field(default_factory=list)  # 独立函数/方法
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "file_path": self.file_path,
            "language": self.language,
            "classes": [c.to_dict() for c in self.classes],
            "methods": [m.to_dict() for m in self.methods],
            "success": self.success,
            "error": self.error,
        }


@dataclass
class ImportInfo:
    """Import 信息."""

    module: str  # 导入的模块名
    alias: Optional[str] = None  # 别名（如 import x as y）
    imported_names: List[str] = field(default_factory=list)  # 从模块导入的具体名称
    is_relative: bool = False  # 是否是相对导入
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "module": self.module,
            "alias": self.alias,
            "imported_names": self.imported_names,
            "is_relative": self.is_relative,
            "line_number": self.line_number,
        }


@dataclass
class MethodCallInfo:
    """方法调用信息."""

    method_name: str  # 方法名
    receiver: Optional[str] = None  # 接收者（如 obj.method() 中的 obj）
    arguments: List[str] = field(default_factory=list)  # 参数表达式列表
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "method_name": self.method_name,
            "receiver": self.receiver,
            "arguments": self.arguments,
            "line_number": self.line_number,
        }


class CodeAnalyzer(ABC):
    """代码分析器抽象基类.

    子类需要实现以下方法：
    1. parse_for_structure - 结构图构建阶段的代码解析
    2. extract_imports - 依赖图构建阶段的 import 提取
    3. extract_method_calls - 依赖图构建阶段的方法调用提取
    """

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名列表."""
        raise NotImplementedError

    @property
    @abstractmethod
    def language_name(self) -> str:
        """语言名称."""
        raise NotImplementedError

    # ==================== 结构图构建阶段方法 ====================

    @abstractmethod
    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析代码文件，提取类和函数/方法定义.

        这是结构图构建阶段使用的主要方法，用于创建 Class 和 Method 节点。

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            解析结果，包含类和方法符号列表
        """
        raise NotImplementedError

    # ==================== 依赖图构建阶段方法 ====================

    @abstractmethod
    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从代码中提取 import/include 语句.

        这是依赖图构建阶段使用的方法，用于创建 File 之间的 USE 关系。

        Args:
            content: 代码内容
            file_path: 文件路径（用于解析相对导入）

        Returns:
            Import 信息列表
        """
        raise NotImplementedError

    @abstractmethod
    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从方法代码中提取方法调用.

        这是依赖图构建阶段使用的方法，用于创建 Method 之间的 CALL 关系。

        Args:
            content: 方法代码内容
            method_name: 当前方法的名称（用于排除自身调用）
            file_path: 文件路径

        Returns:
            方法调用信息列表
        """
        raise NotImplementedError

    # ==================== 辅助方法 ====================

    def can_analyze(self, file_path: str) -> bool:
        """检查是否可以分析该文件.

        Args:
            file_path: 文件路径

        Returns:
            是否可以分析
        """
        from pathlib import Path

        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
