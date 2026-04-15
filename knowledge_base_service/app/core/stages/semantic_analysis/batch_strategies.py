"""批次构建策略 - 策略模式实现.

该模块提供不同的批次构建策略，用于语义分析阶段的方法摘要生成。
不同的策略适用于不同的代码结构和依赖模式。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class BatchStrategy(ABC):
    """批次构建策略抽象基类.

    定义构建方法批次的通用接口。不同的实现可以使用不同的
    算法来决定如何将方法分组以进行批量摘要生成。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述."""
        raise NotImplementedError

    @abstractmethod
    def build_batch(
        self,
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, str],
        max_tokens: int,
    ) -> List[str]:
        """构建批次.

        Args:
            pending: 待处理方法 {method_id: {"data": {...}, "callees": [...]}}
            graph: 完整调用图 {method_id: {"data": {...}, "callees": [...]}}
            summary_cache: 已生成的 summary 缓存 {method_id: summary}
            max_tokens: 最大上下文 token 数（已预留输出空间）

        Returns:
            批次中的方法 ID 列表
        """
        raise NotImplementedError

    def estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数量.

        使用简单的字符数/4作为粗略估算。

        Args:
            text: 待估算的文本

        Returns:
            估算的 token 数量
        """
        return len(text) // 4

    def handle_fallback(
        self,
        pending: Dict[str, Dict],
        max_tokens: int,
    ) -> List[str]:
        """处理降级情况 - 当无法构建有效批次时调用.

        动态计算代码长度限制，基于 max_tokens 而不是固定值。

        Args:
            pending: 待处理方法 {method_id: {"data": {...}, "callees": [...]}}
            max_tokens: 最大上下文 token 数

        Returns:
            降级批次中的方法 ID 列表（通常为1个）
        """
        if not pending:
            return []

        # 获取第一个待处理方法
        mid = list(pending.keys())[0]
        method_data = pending[mid]["data"]
        code = method_data.get("code", "")

        # 动态计算最大字符数
        # 预留空间：输出 + 基础缓冲
        reserved_tokens = 500
        available_tokens = int(max_tokens * 0.8) - reserved_tokens
        max_chars = max(available_tokens * 4, 2000)  # 至少保留2000字符

        # 如果代码太长，截断到安全长度
        if len(code) > max_chars:
            method_data["code"] = code[:max_chars] + "\n# ... (代码已截断)"
            logger.warning(
                f"Method {mid} code truncated from {len(code)} to {max_chars} chars "
                f"(max_tokens={max_tokens})"
            )

        return [mid]


class DependencyAwareBatchStrategy(BatchStrategy):
    """依赖感知批次策略 - 默认策略.

    该策略基于方法间的调用依赖关系构建批次：
    1. 优先选择能覆盖更多批次内依赖的方法
    2. 聚合有依赖关系的方法，实现批次内依赖消解
    3. 在上下文限制内容纳尽可能多的相关方法

    适用于具有复杂调用关系的代码库，可以显著减少LLM调用次数。
    """

    @property
    def name(self) -> str:
        return "dependency_aware"

    @property
    def description(self) -> str:
        return (
            "基于方法调用依赖的智能批次构建策略，"
            "优先聚合有内部依赖的方法以减少LLM调用次数"
        )

    def build_batch(
        self,
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, str],
        max_tokens: int,
    ) -> List[str]:
        """构建智能批次 - 聚合跨依赖边界的方法.

        策略：优先选择能覆盖更多批次内依赖的方法，实现依赖消解。

        Args:
            pending: 待处理方法 {method_id: data}
            graph: 完整调用图
            summary_cache: 已生成的 summary 缓存
            max_tokens: 最大上下文 token 数（已预留输出空间）

        Returns:
            批次中的方法 ID 列表
        """
        batch: List[str] = []
        batch_content: List[str] = []  # 用于估算token的内容

        # 计算每个候选方法的聚合价值分数
        candidate_scores: List[Tuple[str, float, List[str]]] = []

        for mid, data in pending.items():
            callees = graph[mid]["callees"]

            # 统计各类依赖
            internal_deps = [
                c for c in callees
                if c in pending and c != mid  # 排除自调用
            ]

            # 聚合价值 = 内部依赖数量 + 潜在覆盖率
            score = len(internal_deps)
            if score > 0:
                # 额外加分：依赖方法也在待处理列表中
                score += 0.5

            candidate_scores.append((mid, score, internal_deps))

        # 按分数降序排序（高价值优先）
        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        # 贪心选择 - 优先聚合高价值且能容纳的方法
        for mid, score, internal_deps in candidate_scores:
            if mid in batch:
                continue

            # 计算需要额外添加的内容
            additions_tokens = 0
            additions: List[str] = []

            # 必须先加入批次内的被调用方法（依赖关系）
            for dep_id in internal_deps:
                if dep_id not in batch and dep_id in pending:
                    dep_code = pending[dep_id]["data"].get("code", "")[:1500]
                    additions.append(dep_code)
                    additions_tokens += self.estimate_tokens(dep_code)

            # 当前方法自身的token
            current_code = pending[mid]["data"].get("code", "")[:3000]
            current_tokens = self.estimate_tokens(current_code)

            # 计算加入后的总token
            current_total = sum(self.estimate_tokens(c) for c in batch_content)
            # 为输出预留空间：每个方法约150 tokens（与client.py保持一致）
            estimated_batch_size = len(batch) + len(internal_deps) + 1
            output_tokens = estimated_batch_size * 150 + 500  # 基础缓冲
            total_needed = current_total + additions_tokens + current_tokens + output_tokens

            # 检查是否超出限制（留10%余量）
            if total_needed <= max_tokens * 0.9:
                # 将依赖方法加入批次
                for dep_id in internal_deps:
                    if dep_id not in batch and dep_id in pending:
                        batch.append(dep_id)
                        dep_code = pending[dep_id]["data"].get("code", "")[:1500]
                        batch_content.append(dep_code)

                if mid not in batch:
                    batch.append(mid)
                    batch_content.append(current_code)

        # 如果无法构建有效批次，使用降级处理
        if not batch and pending:
            logger.warning("DependencyAwareBatchStrategy: 无法构建批次，使用降级处理")
            batch = self.handle_fallback(pending, max_tokens)

        return batch


class SimpleBatchStrategy(BatchStrategy):
    """简单批次策略.

    该策略仅基于代码大小构建批次，不考虑方法间的依赖关系。
    按照代码大小排序后，在上下文限制内尽可能多地添加方法。

    适用于代码依赖关系较少或需要快速处理的场景。
    """

    # 默认每个方法预留的代码长度
    DEFAULT_CODE_LIMIT = 2000
    # 输出预留tokens（每个方法）
    OUTPUT_TOKENS_PER_METHOD = 150
    # 基础缓冲tokens
    BASE_BUFFER_TOKENS = 500

    @property
    def name(self) -> str:
        return "simple"

    @property
    def description(self) -> str:
        return (
            "简单的基于代码大小的批次构建策略，"
            "不考虑方法间依赖关系，按顺序填充"
        )

    def build_batch(
        self,
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, str],
        max_tokens: int,
    ) -> List[str]:
        """构建简单批次.

        仅基于代码大小，不考虑依赖关系。

        Args:
            pending: 待处理方法 {method_id: data}
            graph: 完整调用图
            summary_cache: 已生成的 summary 缓存
            max_tokens: 最大上下文 token 数（已预留输出空间）

        Returns:
            批次中的方法 ID 列表
        """
        batch: List[str] = []
        batch_tokens = 0

        # 按代码长度排序（短的优先，可以容纳更多方法）
        sorted_methods = sorted(
            pending.items(),
            key=lambda x: len(x[1]["data"].get("code", "")),
        )

        for mid, data in sorted_methods:
            code = data["data"].get("code", "")
            # 截断代码
            code_limit = self.DEFAULT_CODE_LIMIT
            truncated_code = code[:code_limit] if len(code) > code_limit else code
            code_tokens = self.estimate_tokens(truncated_code)

            # 计算加入后的总token
            new_batch_size = len(batch) + 1
            output_tokens = new_batch_size * self.OUTPUT_TOKENS_PER_METHOD + self.BASE_BUFFER_TOKENS
            total_needed = batch_tokens + code_tokens + output_tokens

            # 检查是否超出限制（留10%余量）
            if total_needed <= max_tokens * 0.9:
                batch.append(mid)
                batch_tokens += code_tokens
            else:
                # 如果批次为空且这个方法太大，尝试截断后加入
                if not batch and len(code) > 0:
                    # 尝试使用更小的代码限制
                    emergency_limit = 1000
                    emergency_code = code[:emergency_limit]
                    emergency_tokens = self.estimate_tokens(emergency_code)
                    emergency_output = self.OUTPUT_TOKENS_PER_METHOD + self.BASE_BUFFER_TOKENS

                    if emergency_tokens + emergency_tokens <= max_tokens * 0.9:
                        batch.append(mid)
                        logger.warning(
                            f"Method {mid} is very large, using emergency limit "
                            f"({emergency_limit} chars)"
                        )

        # 如果无法构建有效批次，使用降级处理
        if not batch and pending:
            logger.warning("SimpleBatchStrategy: 无法构建批次，使用降级处理")
            batch = self.handle_fallback(pending, max_tokens)

        return batch


class TopologicalBatchStrategy(BatchStrategy):
    """拓扑排序批次策略.

    该策略基于方法的拓扑排序构建批次，确保被调用的方法
    先于调用者处理。适用于调用关系清晰的代码库。

    通过优先处理叶节点（被调用者），为后续方法的摘要生成
    提供更完整的上下文信息。
    """

    @property
    def name(self) -> str:
        return "topological"

    @property
    def description(self) -> str:
        return (
            "基于拓扑排序的批次构建策略，"
            "确保被调用方法先于调用者处理"
        )

    def build_batch(
        self,
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, Dict],
        max_tokens: int,
    ) -> List[str]:
        """构建拓扑排序批次.

        按拓扑顺序处理方法，被调用的方法先处理。

        Args:
            pending: 待处理方法 {method_id: data}
            graph: 完整调用图
            summary_cache: 已生成的 summary 缓存
            max_tokens: 最大上下文 token 数（已预留输出空间）

        Returns:
            批次中的方法 ID 列表
        """
        from collections import defaultdict, deque

        # 只考虑pending中的方法的子图
        pending_ids = set(pending.keys())

        # 计算入度（被多少pending中的方法调用）
        in_degree = defaultdict(int)
        for mid in pending_ids:
            in_degree[mid] = 0

        for mid, data in pending.items():
            for callee_id in data["callees"]:
                if callee_id in pending_ids and callee_id != mid:
                    in_degree[mid] += 1

        # Kahn算法：入度为0的节点是叶节点（不被其他pending方法调用）
        queue = deque([mid for mid in pending_ids if in_degree[mid] == 0])

        # 按拓扑顺序选择方法，直到达到token限制
        batch: List[str] = []
        batch_tokens = 0

        # 输出预留
        output_buffer = self.OUTPUT_TOKENS_PER_METHOD + 500

        while queue:
            mid = queue.popleft()

            # 检查token限制
            code = pending[mid]["data"].get("code", "")[:3000]
            code_tokens = self.estimate_tokens(code)
            new_batch_size = len(batch) + 1
            output_tokens = new_batch_size * self.OUTPUT_TOKENS_PER_METHOD + 500
            total_needed = batch_tokens + code_tokens + output_tokens

            if total_needed <= max_tokens * 0.9:
                batch.append(mid)
                batch_tokens += code_tokens

                # 找到所有调用该方法的方法，减少其入度
                for other_mid, other_data in pending.items():
                    if mid in other_data["callees"]:
                        in_degree[other_mid] -= 1
                        if in_degree[other_mid] == 0:
                            queue.append(other_mid)
            else:
                # Token限制达到，停止添加
                break

        # 如果无法构建有效批次，使用降级处理
        if not batch and pending:
            logger.warning("TopologicalBatchStrategy: 无法构建批次，使用降级处理")
            batch = self.handle_fallback(pending, max_tokens)

        return batch


class BatchStrategyFactory:
    """批次策略工厂.

    用于创建和管理批次策略实例。
    """

    _strategies: Dict[str, type] = {
        "dependency_aware": DependencyAwareBatchStrategy,
        "simple": SimpleBatchStrategy,
        "topological": TopologicalBatchStrategy,
    }

    @classmethod
    def create(cls, strategy_name: str) -> BatchStrategy:
        """创建策略实例.

        Args:
            strategy_name: 策略名称

        Returns:
            策略实例

        Raises:
            ValueError: 如果策略不存在
        """
        strategy_name = strategy_name.lower()
        if strategy_name not in cls._strategies:
            available = ", ".join(cls._strategies.keys())
            raise ValueError(
                f"Unknown batch strategy: {strategy_name}. "
                f"Available strategies: {available}"
            )
        return cls._strategies[strategy_name]()

    @classmethod
    def register(cls, name: str, strategy_class: type):
        """注册新策略.

        Args:
            name: 策略名称
            strategy_class: 策略类
        """
        cls._strategies[name.lower()] = strategy_class

    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """获取所有可用的策略名称.

        Returns:
            策略名称列表
        """
        return list(cls._strategies.keys())

    @classmethod
    def get_default_strategy(cls) -> BatchStrategy:
        """获取默认策略实例.

        Returns:
            默认策略实例（DependencyAwareBatchStrategy）
        """
        return cls._strategies["dependency_aware"]()
