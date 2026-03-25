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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "node_type": self.node_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_col": self.start_col,
            "end_col": self.end_col,
            "text": self.text,
            "children": [c.to_dict() for c in self.children],
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASTNode":
        """从字典创建实例."""
        return cls(
            node_type=data["node_type"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            start_col=data["start_col"],
            end_col=data["end_col"],
            text=data["text"],
            children=[cls.from_dict(c) for c in data.get("children", [])],
            properties=data.get("properties", {}),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "docstring": self.docstring,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "modifiers": self.modifiers,
            "calls": self.calls,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MethodSymbol":
        """从字典创建实例."""
        return cls(
            name=data["name"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            code=data["code"],
            docstring=data.get("docstring", ""),
            parameters=data.get("parameters", []),
            return_type=data.get("return_type"),
            modifiers=data.get("modifiers", []),
            calls=data.get("calls", []),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "docstring": self.docstring,
            "methods": [m.to_dict() for m in self.methods],
            "base_classes": self.base_classes,
            "implements": self.implements,
            "modifiers": self.modifiers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClassSymbol":
        """从字典创建实例."""
        return cls(
            name=data["name"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            code=data["code"],
            docstring=data.get("docstring", ""),
            methods=[MethodSymbol.from_dict(m) for m in data.get("methods", [])],
            base_classes=data.get("base_classes", []),
            implements=data.get("implements", []),
            modifiers=data.get("modifiers", []),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "file_path": self.file_path,
            "language": self.language,
            "ast": self.ast.to_dict() if self.ast else None,
            "classes": [c.to_dict() for c in self.classes],
            "methods": [m.to_dict() for m in self.methods],
            "imports": self.imports,
            "success": self.success,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParseResult":
        """从字典创建实例."""
        ast_data = data.get("ast")
        return cls(
            file_path=data["file_path"],
            language=data["language"],
            ast=ASTNode.from_dict(ast_data) if ast_data else None,
            classes=[ClassSymbol.from_dict(c) for c in data.get("classes", [])],
            methods=[MethodSymbol.from_dict(m) for m in data.get("methods", [])],
            imports=data.get("imports", []),
            success=data.get("success", True),
            error=data.get("error"),
        )


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
