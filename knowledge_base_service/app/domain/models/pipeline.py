"""流水线状态模型定义."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class PipelineStage(Enum):
    """流水线阶段枚举."""

    REPO_TRAVERSAL = "repo_traversal"
    CODE_PARSING = "code_parsing"
    SYMBOL_EXTRACTION = "symbol_extraction"
    STRUCTURE_GRAPH_BUILD = "structure_graph_build"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    DEPENDENCY_GRAPH_BUILD = "dependency_graph_build"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    EMBEDDING_GENERATION = "embedding_generation"
    VECTOR_DB_STORE = "vector_db_store"
    MODULE_DETECTION = "module_detection"
    SEMANTIC_GRAPH_BUILD = "semantic_graph_build"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStatus(Enum):
    """流水线状态枚举."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class StageResult:
    """阶段执行结果."""

    stage: PipelineStage
    status: PipelineStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """计算阶段执行时长（秒）."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "message": self.message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StageResult":
        """从字典创建实例."""
        return cls(
            stage=PipelineStage(data["stage"]),
            status=PipelineStatus(data["status"]),
            start_time=datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None,
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            message=data.get("message", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PipelineState:
    """流水线状态."""

    pipeline_id: str
    repo_path: str
    repo_name: str
    current_stage: PipelineStage = PipelineStage.REPO_TRAVERSAL
    overall_status: PipelineStatus = PipelineStatus.PENDING
    stages: Dict[PipelineStage, StageResult] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    checkpoint_data: Dict[str, Any] = field(default_factory=dict)

    def update_stage(self, stage: PipelineStage, result: StageResult):
        """更新阶段结果."""
        self.stages[stage] = result
        self.current_stage = stage
        self.updated_at = datetime.utcnow()

    def get_stage_result(self, stage: PipelineStage) -> Optional[StageResult]:
        """获取阶段结果."""
        return self.stages.get(stage)

    @property
    def progress_percent(self) -> int:
        """计算整体进度百分比."""
        all_stages = [
            PipelineStage.REPO_TRAVERSAL,
            PipelineStage.CODE_PARSING,
            PipelineStage.SYMBOL_EXTRACTION,
            PipelineStage.STRUCTURE_GRAPH_BUILD,
            PipelineStage.DEPENDENCY_ANALYSIS,
            PipelineStage.DEPENDENCY_GRAPH_BUILD,
            PipelineStage.SEMANTIC_ANALYSIS,
            PipelineStage.EMBEDDING_GENERATION,
            PipelineStage.VECTOR_DB_STORE,
            PipelineStage.MODULE_DETECTION,
            PipelineStage.SEMANTIC_GRAPH_BUILD,
        ]
        completed = sum(
            1 for s in all_stages
            if s in self.stages and self.stages[s].status == PipelineStatus.COMPLETED
        )
        return int((completed / len(all_stages)) * 100)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "pipeline_id": self.pipeline_id,
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "current_stage": self.current_stage.value,
            "overall_status": self.overall_status.value,
            "progress_percent": self.progress_percent,
            "stages": {
                k.value: v.to_dict() for k, v in self.stages.items()
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "checkpoint_data": self.checkpoint_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        """从字典创建实例."""
        stages = {
            PipelineStage(k): StageResult.from_dict(v)
            for k, v in data.get("stages", {}).items()
        }
        return cls(
            pipeline_id=data["pipeline_id"],
            repo_path=data["repo_path"],
            repo_name=data["repo_name"],
            current_stage=PipelineStage(data["current_stage"]),
            overall_status=PipelineStatus(data["overall_status"]),
            stages=stages,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            checkpoint_data=data.get("checkpoint_data", {}),
        )
