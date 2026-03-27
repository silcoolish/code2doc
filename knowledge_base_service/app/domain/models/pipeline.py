"""流水线状态模型定义."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class PipelineLogRecord:
    """流水线日志记录.

    用于记录流水线执行过程中的事件，以 JSON Lines 格式存储。
    支持断点续传，失败后可以从日志中恢复执行状态。
    """

    timestamp: datetime
    level: str  # INFO, ERROR, WARNING
    pipeline_id: str
    event: str  # pipeline_started, stage_started, stage_completed, stage_failed, pipeline_completed, pipeline_failed, pipeline_resumed
    stage: Optional["PipelineStage"] = None
    duration: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "pipeline_id": self.pipeline_id,
            "event": self.event,
            "stage": self.stage.value if self.stage else None,
            "duration": self.duration,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineLogRecord":
        """从字典创建实例."""
        # 避免循环导入
        from app.domain.models.pipeline import PipelineStage

        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            level=data["level"],
            pipeline_id=data["pipeline_id"],
            event=data["event"],
            stage=PipelineStage(data["stage"]) if data.get("stage") else None,
            duration=data.get("duration"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

@dataclass
class PipelineContext:
    """流水线上下文."""

    pipeline_id: str
    repo_id: str
    repo_path: str
    repo_name: str
    config: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    current_stage: "PipelineStage" = field(init=False)
    overall_status: "PipelineStatus" = field(init=False)
    stages: Dict["PipelineStage", "StageResult"] = field(
        default_factory=dict, init=False
    )
    created_at: datetime = field(default_factory=datetime.utcnow, init=False)
    updated_at: datetime = field(default_factory=datetime.utcnow, init=False)
    progress: float = field(default=0.0, init=False)
    pipeline_msg: str = field(default="", init=False)  # 流水线运行信息
    stage_msg: str = field(default="", init=False)  # 阶段执行信息

    def __post_init__(self):
        """初始化后设置默认值."""

        self.current_stage = STAGE_ORDER[0]
        self.overall_status = PipelineStatus.PENDING

    def update_stage(self, stage: "PipelineStage", result: "StageResult"):
        """更新阶段结果."""
        self.stages[stage] = result
        self.current_stage = stage
        self.updated_at = datetime.utcnow()
        self._update_progress_on_complete(stage)

    def get_stage_result(self, stage: "PipelineStage") -> Optional["StageResult"]:
        """获取阶段结果."""
        return self.stages.get(stage)

    def _update_progress_on_complete(self, completed_stage: "PipelineStage"):
        """阶段完成时更新进度百分比（基于权重）."""
        total_weight = sum(STAGE_WEIGHTS.values())
        if total_weight == 0:
            total_weight = 1.0

        # 计算已完成阶段的权重和
        completed_weight = 0.0
        for stage in STAGE_ORDER:
            if stage in self.stages and self.stages[stage].status == PipelineStatus.COMPLETED:
                completed_weight += STAGE_WEIGHTS.get(stage, 1.0)
            if stage == completed_stage:
                break

        self.progress = round((completed_weight / total_weight) * 100, 2)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "pipeline_id": self.pipeline_id,
            "repo_id": self.repo_id,
            "repo_path": self.repo_path,
            "repo_name": self.repo_name,
            "current_stage": self.current_stage.value,
            "overall_status": self.overall_status.value,
            "progress": self.progress,
            "pipeline_msg": self.pipeline_msg,
            "stage_msg": self.stage_msg,
            "stages": {k.value: v.to_dict() for k, v in self.stages.items()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "config": self.config,
            "data": self._serialize_data(self.data),
        }

    def _serialize_data(self, data: Any) -> Any:
        """递归序列化数据.

        处理包含 to_dict 方法的对象和其他非 JSON 序列化类型。
        """
        try:
            if hasattr(data, 'to_dict') and callable(getattr(data, 'to_dict')):
                return data.to_dict()
        except (AttributeError, TypeError):
            pass

        if isinstance(data, dict):
            return {k: self._serialize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_data(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, Enum):
            return data.value
        else:
            return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineContext":
        """从字典创建实例."""
        from app.domain.models.pipeline import (
            PipelineStage,
            PipelineStatus,
            StageResult,
        )

        ctx = cls(
            pipeline_id=data["pipeline_id"],
            repo_id=data.get("repo_id", ""),
            repo_path=data["repo_path"],
            repo_name=data["repo_name"],
            config=data.get("config", {}),
            data=data.get("data", {}),
        )
        ctx.stages = {
            PipelineStage(k): StageResult.from_dict(v)
            for k, v in data.get("stages", {}).items()
        }
        ctx.current_stage = PipelineStage(data["current_stage"])
        ctx.overall_status = PipelineStatus(data["overall_status"])
        ctx.progress = data.get("progress", 0.0)
        ctx.pipeline_msg = data.get("pipeline_msg", "")
        ctx.stage_msg = data.get("stage_msg", "")
        ctx.created_at = (
            datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.utcnow()
        )
        ctx.updated_at = (
            datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.utcnow()
        )
        return ctx



class PipelineStage(Enum):
    """流水线阶段枚举."""

    REPO_TRAVERSAL = "repo_traversal"
    STRUCTURE_GRAPH_BUILD = "structure_graph_build"
    DEPENDENCY_GRAPH_BUILD = "dependency_graph_build"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    EMBEDDING_GENERATION = "embedding_generation"
    VECTOR_DB_STORE = "vector_db_store"
    MODULE_DETECTION = "module_detection"
    SEMANTIC_GRAPH_BUILD = "semantic_graph_build"
    COMPLETED = "completed"
    FAILED = "failed"



# 流水线阶段执行顺序（全局常量）
STAGE_ORDER: List[PipelineStage] = [
    PipelineStage.STRUCTURE_GRAPH_BUILD,  # 合并了 repo_traversal
    PipelineStage.DEPENDENCY_GRAPH_BUILD,
    PipelineStage.SEMANTIC_ANALYSIS,
    PipelineStage.MODULE_DETECTION,
    PipelineStage.VECTOR_DB_STORE,  # 合并了 embedding_generation
]

# 阶段权重配置（权重越大，所占进度越多）
STAGE_WEIGHTS: Dict[PipelineStage, float] = {
    PipelineStage.STRUCTURE_GRAPH_BUILD: 3.0,  # 文件遍历和解析，最耗时
    PipelineStage.DEPENDENCY_GRAPH_BUILD: 2.0,  # 依赖分析
    PipelineStage.SEMANTIC_ANALYSIS: 2.0,  # LLM 生成摘要
    PipelineStage.MODULE_DETECTION: 1.5,  # 模块检测
    PipelineStage.VECTOR_DB_STORE: 1.5,  # 向量存储
}


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


