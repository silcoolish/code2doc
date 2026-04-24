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
class CodeVectorRecord(VectorRecord):
    """统一代码向量记录.

    合并了 File/Class/Method/Module/Workflow 的向量记录，
    通过 type 字段区分节点类型。
    """

    type: str = ""  # File / Class / Method / Module / Workflow
    summary: str = ""  # 用于 embedding 的摘要

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        result["type"] = self.type
        result["summary"] = self.summary
        return result
