"""模块检测阶段处理器.

提供基于策略模式的模块检测功能，支持多种检测算法。

Example:
    ```python
    from app.core.stages.module_detection import ModuleDetectionStage

    # 创建阶段处理器（自动使用配置的策略）
    stage = ModuleDetectionStage()

    # 执行阶段
    result = await stage.execute(context)
    ```

Configuration:
    通过环境变量配置策略:

    ```bash
    # 选择策略: "simple" | "clustering"
    MODULE_DETECTION_STRATEGY=clustering

    # 简单策略配置
    SIMPLE_STRATEGY_MAX_FILES=100

    # 聚类策略配置
    CLUSTERING_STRATEGY_MAX_CLUSTER_SIZE=80
    CLUSTERING_STRATEGY_MAX_CONCURRENCY=5
    ```

Strategies:
    - **simple**: 简单截断策略，适合小型仓库 (<100文件)
    - **clustering**: 分层聚类策略，支持任意规模仓库
"""

from .module_detection import ModuleDetectionStage
from .strategies import (
    ModuleDetectionStrategy,
    ModuleDetectionStrategyFactory,
    SimpleTruncationStrategy,
    ModuleDetectionResult,
)
from .models import (
    FileCluster,
    WorkflowInfo,
    ModuleInfo,
    ClusterModuleResult,
    MergedModule,
    FileDependency,
)

# 延迟导入 ClusteringStrategy 避免循环依赖
try:
    from .strategies import ClusteringStrategy
except ImportError:
    ClusteringStrategy = None

__all__ = [
    "ModuleDetectionStage",
    "ModuleDetectionStrategy",
    "ModuleDetectionStrategyFactory",
    "SimpleTruncationStrategy",
    "ClusteringStrategy",
    "ModuleDetectionResult",
    "FileCluster",
    "WorkflowInfo",
    "ModuleInfo",
    "ClusterModuleResult",
    "MergedModule",
    "FileDependency",
]
