"""向量数据库模型定义."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VectorRecord:
    """向量记录基类."""

    id: str
    name: str
    node_id: str
    repo: str
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于Milvus）."""
        return {
            "id": self.id,
            "name": self.name,
            "node_id": self.node_id,
            "repo": self.repo,
            "embedding": self.embedding,
        }


@dataclass
class FileSummaryRecord(VectorRecord):
    """文件摘要向量记录."""

    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["summary"] = self.summary
        return result


@dataclass
class ClassSummaryRecord(VectorRecord):
    """类摘要向量记录."""

    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["summary"] = self.summary
        return result


@dataclass
class MethodSummaryRecord(VectorRecord):
    """方法摘要向量记录."""

    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["summary"] = self.summary
        return result


@dataclass
class SemanticSummaryRecord(VectorRecord):
    """语义摘要向量记录（Module/Workflow）."""

    type: str = ""  # Module / Workflow
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["type"] = self.type
        result["summary"] = self.summary
        return result


@dataclass
class SemanticDetailRecord(VectorRecord):
    """语义详情向量记录（Module/Workflow）."""

    type: str = ""  # Module / Workflow
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["type"] = self.type
        result["detail"] = self.detail
        return result


@dataclass
class ClassCodeRecord(VectorRecord):
    """类代码向量记录."""

    path: str = ""
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["path"] = self.path
        result["code"] = self.code
        return result


@dataclass
class MethodCodeRecord(VectorRecord):
    """方法代码向量记录."""

    path: str = ""
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["path"] = self.path
        result["code"] = self.code
        return result
