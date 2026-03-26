"""图数据库模型定义."""

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class BaseNode(ABC):
    """图节点基类."""

    id: str
    name: str
    type: str
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于Neo4j）."""
        result = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "description": self.description,
        }
        # 只添加非空的 extra 字段
        if self.extra:
            result["extra"] = self.extra
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseNode":
        """从字典创建实例."""
        raise NotImplementedError


@dataclass
class Repository(BaseNode):
    """仓库节点."""

    path: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.type:
            self.type = "Repository"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "path": self.path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        })
        return result


@dataclass
class Directory(BaseNode):
    """目录节点."""

    path: str = ""

    def __post_init__(self):
        if not self.type:
            self.type = "Directory"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["path"] = self.path
        return result


@dataclass
class File(BaseNode):
    """文件节点."""

    path: str = ""
    summary: str = ""
    embedding_id: str = ""
    file_type: str = ""  # code / doc / config
    suffix: str = ""

    def __post_init__(self):
        if not self.type:
            self.type = "File"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "path": self.path,
            "summary": self.summary,
            "embeddingId": self.embedding_id,
            "fileType": self.file_type,
            "suffix": self.suffix,
        })
        return result


@dataclass
class Class(BaseNode):
    """类/结构体节点."""

    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    language: str = ""
    code: str = ""
    summary: str = ""
    embedding_id: str = ""
    docstring: str = ""
    real_type: str = ""

    def __post_init__(self):
        if not self.type:
            self.type = "Class"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "filePath": self.file_path,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "language": self.language,
            "code": self.code,
            "summary": self.summary,
            "embeddingId": self.embedding_id,
            "docstring": self.docstring,
            "realType": self.real_type,
        })
        return result


@dataclass
class Method(BaseNode):
    """方法/函数节点."""

    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    language: str = ""
    code: str = ""
    summary: str = ""
    embedding_id: str = ""
    docstring: str = ""
    class_id: Optional[str] = None  # 所属类的ID

    def __post_init__(self):
        if not self.type:
            self.type = "Method"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "filePath": self.file_path,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "language": self.language,
            "code": self.code,
            "summary": self.summary,
            "embeddingId": self.embedding_id,
            "docstring": self.docstring,
        })
        return result


@dataclass
class Module(BaseNode):
    """功能模块节点."""

    summary: str = ""
    detail: str = ""
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0
    embedding_id: str = ""

    def __post_init__(self):
        if not self.type:
            self.type = "Module"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "summary": self.summary,
            "detail": self.detail,
            "keywords": self.keywords,
            "confidence": self.confidence,
            "embeddingId": self.embedding_id,
        })
        return result


@dataclass
class Workflow(BaseNode):
    """业务流程节点."""

    summary: str = ""
    detail: str = ""
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0
    embedding_id: str = ""
    module_id: Optional[str] = None

    def __post_init__(self):
        if not self.type:
            self.type = "Workflow"

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result.update({
            "summary": self.summary,
            "detail": self.detail,
            "keywords": self.keywords,
            "confidence": self.confidence,
            "embeddingId": self.embedding_id,
        })
        return result
