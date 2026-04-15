"""模块检测阶段处理器 - 策略模式实现."""

import logging
from typing import Any, Dict, Optional

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.llm import get_llm_service
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db.graph.base_client import GraphDatabaseClient
from app.infrastructure.db import get_graph_db_client

from .strategies import ModuleDetectionStrategyFactory

logger = logging.getLogger(__name__)


class ModuleDetectionStage(PipelineStageHandler):
    """模块检测阶段处理器 - 使用策略模式支持多种检测算法.

    Input (context.data):
        - traversal_result: TraversalResult - 遍历结果，从中读取 files 列表
        - file_summaries: Dict[str, str] - 文件ID到摘要的映射

    Output (context.data):
        - module_ids: List[str] - 检测到的模块ID列表
        - workflow_ids: List[str] - 检测到的业务流程ID列表

    Side Effects:
        - 在图数据库中创建 Module 和 Workflow 节点
        - 创建 File -> Module, File -> Workflow, Workflow -> Module 的 BELONG_TO 关系
        - 创建 Workflow -> Class/Method 的 CONTAIN 关系（语义图构建）

    Configuration:
        - MODULE_DETECTION_STRATEGY: 策略名称 ("simple" | "clustering")
        - SIMPLE_STRATEGY_MAX_FILES: 简单策略最大文件数
        - CLUSTERING_STRATEGY_MAX_CLUSTER_SIZE: 聚类策略簇大小
        - CLUSTERING_STRATEGY_MAX_CONCURRENCY: 聚类策略并发数
    """

    stage = PipelineStage.MODULE_DETECTION
    weight = 1.5  # 模块检测

    def __init__(
        self,
        strategy_name: Optional[str] = None,
        strategy_config: Optional[Dict[str, Any]] = None,
    ):
        self.llm_service = get_llm_service()
        self.graph_db: GraphDatabaseClient = get_graph_db_client()
        self._strategy = None
        self._strategy_name = strategy_name
        self._strategy_config = strategy_config or {}

    def _get_strategy(self) -> Any:
        """获取配置的模块检测策略.

        优先使用构造函数传入的策略参数，否则从配置读取。

        Returns:
            ModuleDetectionStrategy: 策略实例

        Raises:
            ValueError: 如果策略配置无效
        """
        if self._strategy is not None:
            return self._strategy

        # 优先使用传入的策略名称，否则从配置获取
        if self._strategy_name:
            strategy_name = self._strategy_name
            strategy_kwargs = self._strategy_config.copy()
        else:
            # 从配置获取策略名称
            settings = get_settings()
            strategy_name = getattr(settings, "module_detection_strategy", "simple")

            # 获取策略特定配置
            strategy_kwargs = {}
            if strategy_name == "simple":
                strategy_kwargs["max_files"] = getattr(
                    settings, "simple_strategy_max_files", 100
                )
            elif strategy_name == "clustering":
                strategy_kwargs["max_cluster_size"] = getattr(
                    settings, "clustering_strategy_max_cluster_size", 80
                )
                strategy_kwargs["max_concurrency"] = getattr(
                    settings, "clustering_strategy_max_concurrency", 5
                )

        # 获取策略实例
        self._strategy = ModuleDetectionStrategyFactory.get(
            strategy_name, **strategy_kwargs
        )

        logger.info(
            f"Using module detection strategy: {strategy_name} "
            f"({self._strategy.description})"
        )

        return self._strategy

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行模块检测阶段.

        Args:
            context: 流水线上下文

        Returns:
            StageResult: 阶段执行结果
        """
        try:
            # 获取输入数据
            file_summaries = context.data.get("file_summaries", {})
            repo_name = context.repo_name
            repo_id = getattr(context, "repo_id", repo_name)

            # 获取策略实例
            strategy = self._get_strategy()

            context.stage_msg = f"使用 {strategy.name} 策略进行模块检测..."
            logger.info(f"Starting module detection with {strategy.name} strategy")

            # 执行策略检测
            result = await strategy.detect_modules(
                context=context,
                repo_id=repo_id,
                file_summaries=file_summaries,
                graph_db=self.graph_db,
                llm_service=self.llm_service,
            )

            # 将结果存入上下文
            context.data["module_ids"] = result.module_ids
            context.data["workflow_ids"] = result.workflow_ids

            # 构建统计信息
            stats = {
                "strategy": strategy.name,
                "modules_detected": len(result.module_ids),
                "workflows_detected": len(result.workflow_ids),
                **result.metadata,
            }

            context.stage_msg = (
                f"模块检测完成: {len(result.module_ids)} 个模块, "
                f"{len(result.workflow_ids)} 个工作流 "
                f"(使用 {strategy.name} 策略)"
            )
            logger.info(f"Module detection completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Module detection completed using {strategy.name} strategy",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Module detection failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )
