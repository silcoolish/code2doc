"""模块检测策略抽象基类."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.domain.models.pipeline import PipelineContext
from app.infrastructure.db.graph.base_client import GraphDatabaseClient


@dataclass
class ModuleDetectionResult:
    """模块检测结果数据类."""

    module_ids: List[str] = field(default_factory=list)
    workflow_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModuleDetectionStrategy(ABC):
    """模块检测策略抽象基类.

    所有模块检测策略必须继承此类并实现抽象方法。
    策略模式允许在运行时切换不同的模块检测算法。

    Example:
        ```python
        # 获取策略实例
        strategy = ModuleDetectionStrategyFactory.get("clustering")

        # 执行检测
        result = await strategy.detect_modules(
            context=context,
            repo_id="repo_123",
            file_summaries={"file_1": "summary..."},
            graph_db=graph_db,
            llm_service=llm,
        )
        ```
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称.

        Returns:
            策略的唯一标识名称，如 "simple"、"clustering"
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述.

        Returns:
            策略的简短描述，用于显示和日志
        """
        pass

    @abstractmethod
    async def detect_modules(
        self,
        context: PipelineContext,
        repo_id: str,
        file_summaries: Dict[str, str],
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> ModuleDetectionResult:
        """执行模块检测.

        Args:
            context: Pipeline上下文，包含 traversal_result 等数据
            repo_id: 仓库ID
            file_summaries: 文件ID到摘要的映射
            graph_db: 图数据库客户端
            llm_service: LLM服务客户端

        Returns:
            ModuleDetectionResult: 检测结果，包含 module_ids 和 workflow_ids
        """
        pass

    def validate_config(self) -> bool:
        """验证策略配置是否有效.

        Returns:
            True 如果配置有效，否则 False

        Note:
            子类可以覆盖此方法进行特定的配置验证。
            默认实现始终返回 True。
        """
        return True
