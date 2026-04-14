"""模块检测策略包.

提供策略工厂和内置策略实现。

Example:
    ```python
    from app.core.stages.module_detection.strategies import (
        ModuleDetectionStrategyFactory,
        SimpleTruncationStrategy,
        ClusteringStrategy,
    )

    # 获取策略实例
    strategy = ModuleDetectionStrategyFactory.get("clustering")

    # 列出可用策略
    strategies = ModuleDetectionStrategyFactory.list_strategies()

    # 注册自定义策略
    class MyStrategy(ModuleDetectionStrategy):
        @property
        def name(self):
            return "my_strategy"

    ModuleDetectionStrategyFactory.register("my_strategy", MyStrategy)
    ```
"""

from typing import Dict, Type

from .base import ModuleDetectionResult, ModuleDetectionStrategy
from .simple_truncation import SimpleTruncationStrategy

# 注意: ClusteringStrategy 在单独的文件中定义，避免循环导入
# 它会在策略工厂中懒加载注册


class ModuleDetectionStrategyFactory:
    """模块检测策略工厂.

    管理所有模块检测策略的注册和获取。
    使用单例模式缓存策略实例。

    Attributes:
        _strategies: 策略类注册表
        _instances: 策略实例缓存
    """

    _strategies: Dict[str, Type[ModuleDetectionStrategy]] = {}
    _instances: Dict[str, ModuleDetectionStrategy] = {}
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls) -> None:
        """确保工厂已初始化（注册内置策略）."""
        if cls._initialized:
            return

        # 注册内置策略（直接注册，不调用register方法避免递归）
        cls._strategies["simple"] = SimpleTruncationStrategy

        # 延迟导入 ClusteringStrategy 避免循环依赖
        try:
            from .clustering import ClusteringStrategy

            cls._strategies["clustering"] = ClusteringStrategy
        except ImportError:
            # ClusteringStrategy 可能尚未实现
            pass

        cls._initialized = True

    @classmethod
    def register(
        cls, name: str, strategy_class: Type[ModuleDetectionStrategy]
    ) -> None:
        """注册策略.

        Args:
            name: 策略名称
            strategy_class: 策略类

        Raises:
            ValueError: 如果 name 已被注册
        """
        cls._ensure_initialized()

        if name in cls._strategies:
            raise ValueError(f"Strategy '{name}' is already registered")

        cls._strategies[name] = strategy_class

    @classmethod
    def get(cls, name: str, **kwargs) -> ModuleDetectionStrategy:
        """获取策略实例（单例模式）.

        Args:
            name: 策略名称
            **kwargs: 传递给策略构造函数的参数

        Returns:
            策略实例

        Raises:
            ValueError: 如果策略不存在
        """
        cls._ensure_initialized()

        # 检查实例缓存
        cache_key = f"{name}:{hash(tuple(sorted(kwargs.items())))}"
        if cache_key in cls._instances:
            return cls._instances[cache_key]

        # 创建新实例
        if name not in cls._strategies:
            available = list(cls._strategies.keys())
            raise ValueError(
                f"Unknown strategy: '{name}'. "
                f"Available strategies: {available}"
            )

        strategy_class = cls._strategies[name]
        strategy = strategy_class(**kwargs)

        # 验证配置
        if not strategy.validate_config():
            raise ValueError(f"Strategy '{name}' configuration is invalid")

        cls._instances[cache_key] = strategy
        return strategy

    @classmethod
    def list_strategies(cls) -> Dict[str, str]:
        """列出所有可用策略.

        Returns:
            策略名称到描述的映射
        """
        cls._ensure_initialized()

        return {
            name: strategy_class().description
            for name, strategy_class in cls._strategies.items()
        }

    @classmethod
    def clear_cache(cls) -> None:
        """清除策略实例缓存.

        主要用于测试场景。
        """
        cls._instances.clear()


__all__ = [
    "ModuleDetectionStrategy",
    "ModuleDetectionResult",
    "ModuleDetectionStrategyFactory",
    "SimpleTruncationStrategy",
]
