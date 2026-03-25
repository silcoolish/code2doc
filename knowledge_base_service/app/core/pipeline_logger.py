"""流水线日志管理器 - 替代CheckpointManager的版本."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.domain.models.pipeline import PipelineStage, PipelineStatus, STAGE_ORDER, PipelineContext

logger = logging.getLogger(__name__)


@dataclass
class PipelineLogRecord:
    """流水线日志记录."""

    timestamp: datetime
    level: str  # INFO, ERROR, WARNING
    pipeline_id: str
    event: str  # pipeline_started, stage_started, stage_completed, stage_failed, pipeline_completed, pipeline_failed, pipeline_resumed
    stage: Optional[PipelineStage] = None
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

    def to_jsonl(self) -> str:
        """转换为 JSON Lines 格式字符串."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineLogRecord":
        """从字典创建实例."""
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

    @classmethod
    def from_line(cls, line: str) -> "PipelineLogRecord":
        """从 JSON Lines 行创建实例."""
        return cls.from_dict(json.loads(line))


class PipelineLogManager:
    """流水线日志管理器 - 替代CheckpointManager.

    新目录结构:
    log/
        - system.log       # 系统日志
        - pipeline/        # 流水线日志根目录
            - {repo_id}/   # 仓库专属目录
                - execution.log    # 当前执行日志
                - context.json     # 当前执行上下文
                - history/         # 历史日志
                    - execution.{timestamp}.log
    """

    def __init__(self, log_dir: str = "./log"):
        """初始化日志管理器.

        Args:
            log_dir: 日志根目录路径
        """
        self.log_dir = Path(log_dir)
        self.pipeline_dir = self.log_dir / "pipeline"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)

    def _get_repo_dir(self, repo_id: str) -> Path:
        """获取仓库专属目录.

        Args:
            repo_id: 仓库ID

        Returns:
            仓库目录路径
        """
        return self.pipeline_dir / repo_id

    def _get_log_file_path(self, repo_id: str) -> Path:
        """获取执行日志文件路径.

        Args:
            repo_id: 仓库ID

        Returns:
            日志文件路径
        """
        return self._get_repo_dir(repo_id) / "execution.log"

    def _get_context_file_path(self, repo_id: str) -> Path:
        """获取上下文文件路径.

        Args:
            repo_id: 仓库ID

        Returns:
            上下文文件路径
        """
        return self._get_repo_dir(repo_id) / "context.json"

    def _get_history_dir(self, repo_id: str) -> Path:
        """获取历史日志目录.

        Args:
            repo_id: 仓库ID

        Returns:
            历史日志目录路径
        """
        return self._get_repo_dir(repo_id) / "history"

    def create_repo_log_dir(self, repo_id: str) -> Path:
        """创建仓库日志目录.

        Args:
            repo_id: 仓库ID

        Returns:
            创建的目录路径
        """
        repo_dir = self._get_repo_dir(repo_id)
        repo_dir.mkdir(parents=True, exist_ok=True)
        # 同时创建history目录
        history_dir = repo_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created repo log directory: {repo_dir}")
        return repo_dir

    def _archive_old_logs(self, repo_id: str) -> None:
        """归档旧日志文件.

        当为仓库新建流水线时：
        1. 删除旧的context.json
        2. 将旧的execution.log移入history文件夹

        Args:
            repo_id: 仓库ID
        """
        repo_dir = self._get_repo_dir(repo_id)
        if not repo_dir.exists():
            return

        context_path = self._get_context_file_path(repo_id)
        log_path = self._get_log_file_path(repo_id)
        history_dir = self._get_history_dir(repo_id)

        # 删除旧的context.json
        if context_path.exists():
            try:
                context_path.unlink()
                logger.debug(f"Deleted old context: {context_path}")
            except Exception as e:
                logger.warning(f"Failed to delete old context: {e}")

        # 将旧的execution.log移入history
        if log_path.exists():
            try:
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                history_log_path = history_dir / f"execution.{timestamp}.log"
                log_path.rename(history_log_path)
                logger.debug(f"Archived old log to: {history_log_path}")
            except Exception as e:
                logger.warning(f"Failed to archive old log: {e}")

    def prepare_new_pipeline(self, repo_id: str) -> Path:
        """为新建流水线准备日志目录.

        Args:
            repo_id: 仓库ID

        Returns:
            仓库目录路径
        """
        # 归档旧日志
        self._archive_old_logs(repo_id)
        # 创建目录
        return self.create_repo_log_dir(repo_id)

    def log_event(self, repo_id: str, event: Dict[str, Any]) -> None:
        """追加日志事件到文件.

        Args:
            repo_id: 仓库ID
            event: 事件数据字典，应包含 event 字段
        """
        log_path = self._get_log_file_path(repo_id)

        # 确保目录存在
        self.create_repo_log_dir(repo_id)

        # 构建日志记录
        record = PipelineLogRecord(
            timestamp=datetime.utcnow(),
            level=event.get("level", "INFO"),
            pipeline_id=event.get("pipeline_id", ""),
            event=event["event"],
            stage=PipelineStage(event["stage"]) if event.get("stage") else None,
            duration=event.get("duration"),
            error=event.get("error"),
            metadata={k: v for k, v in event.items() if k not in [
                "event", "level", "stage", "duration", "error", "pipeline_id"
            ]},
        )

        try:
            # 使用追加模式写入（支持续写）
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(record.to_jsonl() + "\n")
            logger.debug(f"Logged event '{record.event}' for repo {repo_id}")
        except Exception as e:
            logger.error(f"Failed to write log for repo {repo_id}: {e}")

    def _read_log_records(self, repo_id: str) -> List[PipelineLogRecord]:
        """读取日志文件中的所有记录.

        Args:
            repo_id: 仓库ID

        Returns:
            日志记录列表
        """
        log_path = self._get_log_file_path(repo_id)
        if not log_path.exists():
            return []

        records = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            record = PipelineLogRecord.from_line(line)
                            records.append(record)
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning(f"Failed to parse log line: {e}")
        except Exception as e:
            logger.error(f"Failed to read log file {log_path}: {e}")

        return records

    # ==================== 上下文管理（替代CheckpointManager）====================

    async def save_context(self, ctx: "PipelineContext") -> None:
        """保存流水线上下文.

        Args:
            ctx: 流水线上下文
        """
        context_path = self._get_context_file_path(ctx.repo_id)
        self.create_repo_log_dir(ctx.repo_id)

        try:
            with open(context_path, "w", encoding="utf-8") as f:
                json.dump(ctx.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"Context saved: {context_path}")
        except Exception as e:
            logger.error(f"Failed to save context: {e}")
            raise


    async def load_context(self, repo_id: str) -> Optional["PipelineContext"]:
        """通过repo_id加载流水线上下文.

        Args:
            repo_id: 仓库ID

        Returns:
            流水线上下文或None
        """
        context_path = self._get_context_file_path(repo_id)
        if not context_path.exists():
            return None

        try:
            with open(context_path, "r", encoding="utf-8") as f:
                data = json.load(f)



            return PipelineContext.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load context for repo {repo_id}: {e}")
            return None

    async def clear_context(self, repo_id: str) -> None:
        """清除流水线上下文.

        Args:
            repo_id: 仓库ID
        """
        context_path = self._get_context_file_path(repo_id)
        if context_path.exists():
            context_path.unlink()
            logger.debug(f"Context cleared: {context_path}")

    async def get_active_pipeline_id(self, repo_id: str) -> Optional[str]:
        """获取仓库当前活跃的流水线ID.

        Args:
            repo_id: 仓库ID

        Returns:
            流水线ID或None
        """
        ctx = await self.load_context_by_repo_id(repo_id)
        if ctx and ctx.overall_status in (PipelineStatus.RUNNING, PipelineStatus.PAUSED):
            return ctx.pipeline_id
        return None

    # ==================== 阶段状态查询 ====================

    def get_completed_stages(self, repo_id: str) -> List[PipelineStage]:
        """从日志获取已完成的阶段列表.

        Args:
            repo_id: 仓库ID

        Returns:
            已完成阶段的列表
        """
        records = self._read_log_records(repo_id)
        completed_stages = []

        for record in records:
            if record.event == "stage_completed" and record.stage:
                if record.stage not in completed_stages:
                    completed_stages.append(record.stage)
            elif record.event == "stage_failed" and record.stage:
                # 如果阶段失败，它不算已完成
                if record.stage in completed_stages:
                    completed_stages.remove(record.stage)

        return completed_stages

    def get_resume_stage(self, repo_id: str) -> Optional[PipelineStage]:
        """获取应该恢复的阶段（第一个失败/未完成/未开始的阶段）.

        按阶段顺序找到第一个需要执行的阶段：
        - 如果阶段曾经失败过，需要重试
        - 如果阶段开始但未完成（异常情况），需要重试
        - 如果阶段未开始，从这里开始执行

        Args:
            repo_id: 仓库ID

        Returns:
            应该恢复的阶段，如果流水线已完成则返回 None
        """
        records = self._read_log_records(repo_id)
        if not records:
            return None

        # 按时间顺序分析每个阶段的最终状态
        # 后面的记录会覆盖前面的状态
        stage_status: Dict[PipelineStage, str] = {}
        for record in records:
            if record.event == "stage_started" and record.stage:
                stage_status[record.stage] = "started"
            elif record.event == "stage_completed" and record.stage:
                stage_status[record.stage] = "completed"
            elif record.event == "stage_failed" and record.stage:
                stage_status[record.stage] = "failed"
            elif record.event == "pipeline_completed":
                return None  # 流水线已完成

        # 按阶段顺序找到第一个需要处理的阶段
        for stage in STAGE_ORDER:
            status = stage_status.get(stage)
            if status == "failed":
                # 找到失败的阶段，返回该阶段重试
                return stage
            elif status == "started":
                # 找到开始但未完成的阶段（异常情况），返回该阶段重试
                return stage
            elif status is None:
                # 找到未开始的阶段，返回该阶段
                return stage
            # 如果状态是 "completed"，继续检查下一个阶段

        # 所有阶段都已完成
        return None

    # ==================== 便捷日志方法 ====================

    def log_pipeline_started(
        self,
        repo_id: str,
        pipeline_id: str,
        repo_name: str,
        repo_path: str
    ) -> None:
        """记录流水线启动事件."""
        self.log_event(repo_id, {
            "event": "pipeline_started",
            "pipeline_id": pipeline_id,
            "repo_name": repo_name,
            "repo_path": repo_path
        })

    def log_pipeline_resumed(
        self,
        repo_id: str,
        pipeline_id: str,
        completed_stages: List[PipelineStage],
        resume_from: Optional[PipelineStage] = None,
    ) -> None:
        """记录流水线恢复事件."""
        self.log_event(repo_id, {
            "event": "pipeline_resumed",
            "pipeline_id": pipeline_id,
            "completed_stages": [s.value for s in completed_stages],
            "resume_from": resume_from.value if resume_from else None,
        })

    def log_pipeline_completed(self, repo_id: str, pipeline_id: str) -> None:
        """记录流水线完成事件."""
        self.log_event(repo_id, {
            "event": "pipeline_completed",
            "pipeline_id": pipeline_id,
        })

    def log_pipeline_failed(self, repo_id: str, pipeline_id: str, failed_stage: PipelineStage) -> None:
        """记录流水线失败事件."""
        self.log_event(repo_id, {
            "event": "pipeline_failed",
            "pipeline_id": pipeline_id,
            "failed_stage": failed_stage.value,
        })

    def log_stage_started(self, repo_id: str, pipeline_id: str, stage: PipelineStage) -> None:
        """记录阶段开始事件."""
        self.log_event(repo_id, {
            "event": "stage_started",
            "pipeline_id": pipeline_id,
            "stage": stage.value,
        })

    def log_stage_completed(
        self,
        repo_id: str,
        pipeline_id: str,
        stage: PipelineStage,
        duration: float,
    ) -> None:
        """记录阶段完成事件."""
        self.log_event(repo_id, {
            "event": "stage_completed",
            "pipeline_id": pipeline_id,
            "stage": stage.value,
            "duration": duration,
        })

    def log_stage_failed(
        self,
        repo_id: str,
        pipeline_id: str,
        stage: PipelineStage,
        duration: float,
        error: str,
    ) -> None:
        """记录阶段失败事件."""
        self.log_event(repo_id, {
            "event": "stage_failed",
            "pipeline_id": pipeline_id,
            "stage": stage.value,
            "duration": duration,
            "error": error,
            "level": "ERROR",
        })


# 全局日志管理器实例
_pipeline_log_manager: Optional[PipelineLogManager] = None


def get_pipeline_log_manager(log_dir: Optional[str] = None) -> PipelineLogManager:
    """获取全局流水线日志管理器实例.

    Args:
        log_dir: 日志目录路径，首次调用时有效

    Returns:
        PipelineLogManager 实例
    """
    global _pipeline_log_manager
    if _pipeline_log_manager is None:
        from app.config import get_settings

        _pipeline_log_manager = PipelineLogManager(log_dir or get_settings().log_dir)
    return _pipeline_log_manager
