"""代码解析器接口定义."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ASTNode:
    """AST 节点."""

    node_type: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    text: str
    children: List["ASTNode"] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MethodSymbol:
    """方法/函数符号."""

    name: str
    start_line: int
    end_line: int
    code: str
    docstring: str = ""
    parameters: List[Dict[str, str]] = field(default_factory=list)
    return_type: Optional[str] = None
    modifiers: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)  # 调用的方法名列表


@dataclass
class ClassSymbol:
    """类/结构体符号."""

    name: str
    start_line: int
    end_line: int
    code: str
    docstring: str = ""
    methods: List[MethodSymbol] = field(default_factory=list)
    base_classes: List[str] = field(default_factory=list)
    implements: List[str] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)


@dataclass
class ParseResult:
    """解析结果."""

    file_path: str
    language: str
    ast: Optional[ASTNode] = None
    classes: List[ClassSymbol] = field(default_factory=list)
    methods: List[MethodSymbol] = field(default_factory=list)  # 独立的函数
    imports: List[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


class CodeParser(ABC):
    """代码解析器抽象基类."""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        raise NotImplementedError

    @property
    @abstractmethod
    def language_name(self) -> str:
        """语言名称."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, file_path: str, content: str) -> ParseResult:
        """解析代码文件.

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            解析结果
        """
        raise NotImplementedError
