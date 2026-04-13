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
    repo_id: str = ""  # 初始化时传入的 repo_id 参数
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于Milvus）."""
        return {
            "id": self.id,
            "name": self.name,
            "node_id": self.node_id,
            "repo": self.repo,
            "repo_id": self.repo_id,
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
    """语义摘要向量记录（Module/Workflow）.

    合并了 summary 和 detail，只使用 summary 做 embedding，
    detail 作为额外字段存储和返回。
    """

    type: str = ""  # Module / Workflow
    summary: str = ""  # 用于 embedding 的摘要
    detail: str = ""  # 详细描述（不作为 embedding 输入）

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["type"] = self.type
        result["summary"] = self.summary
        result["detail"] = self.detail
        return result
