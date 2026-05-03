"""Token 估算器 - 提供准确的 LLM 上下文 token 估算."""

from typing import List, Optional

from app.domain.model import TemplateBlock


class TokenEstimator:
    """Token 估算器.

    综合考虑系统提示词、输入内容、输出格式和工具返回预留，
    提供更准确的 token 估算，避免策略误选。
    """

    # 混合文本保守估计: 2 字符/token
    CHARS_PER_TOKEN_MIXED = 2.0

    # 系统提示词基础开销 (token 数)
    SYSTEM_PROMPT_BASE = 1500

    # 每个 block 的描述开销 (JSON 字段名 + 格式)
    BLOCK_OVERHEAD_TOKENS = 80

    # 每个 block 的输出 JSON 开销
    BLOCK_OUTPUT_TOKENS = 150

    # 单次工具调用返回预留 (代码详情可能很大)
    TOOL_RESPONSE_RESERVE = 8000

    # 最大工具调用次数预留
    MAX_TOOL_CALLS = 5

    # 安全余量比例 (比原来的 0.8 更保守)
    SAFETY_RATIO = 0.75

    @classmethod
    def estimate_full_context(
        cls,
        blocks: List[TemplateBlock],
        system_prompt_length: Optional[int] = None,
    ) -> int:
        """估算完整上下文策略的 token 数.

        Args:
            blocks: 完整 block 列表
            system_prompt_length: 系统提示词字符长度 (可选)

        Returns:
            预估 token 总数
        """
        total = 0

        # 系统提示词
        if system_prompt_length:
            total += int(system_prompt_length / cls.CHARS_PER_TOKEN_MIXED)
        else:
            total += cls.SYSTEM_PROMPT_BASE

        # 输入内容: 所有 block 的描述
        total += cls._estimate_input_tokens(blocks)

        # 输出格式: 所有 block 的 JSON
        total += len(blocks) * cls.BLOCK_OUTPUT_TOKENS

        # 工具调用预留
        total += cls.TOOL_RESPONSE_RESERVE * cls.MAX_TOOL_CALLS

        # 安全余量 (除以 ratio 即放大估算)
        total = int(total / cls.SAFETY_RATIO)

        return total

    @classmethod
    def estimate_batch_size(
        cls,
        template_blocks: List[TemplateBlock],
        context_limit: int,
        system_prompt_length: Optional[int] = None,
    ) -> int:
        """计算分批策略下每批的最大 block 数量.

        Args:
            template_blocks: 模板 block 列表
            context_limit: 模型上下文限制
            system_prompt_length: 系统提示词字符长度 (可选)

        Returns:
            每批最大 block 数量
        """
        if not template_blocks:
            return 0

        # 每批可用的安全 token 数
        safe_tokens = int(context_limit * cls.SAFETY_RATIO)

        # 减去固定开销
        system_tokens = (
            int(system_prompt_length / cls.CHARS_PER_TOKEN_MIXED)
            if system_prompt_length
            else cls.SYSTEM_PROMPT_BASE
        )
        tool_reserve = cls.TOOL_RESPONSE_RESERVE * 2  # 批次内预留 2 次工具调用

        available_tokens = safe_tokens - system_tokens - tool_reserve

        if available_tokens <= 0:
            return 1

        # 计算每个 block 的平均 token 开销
        avg_input = cls._estimate_input_tokens(template_blocks) / max(len(template_blocks), 1)
        avg_output = cls.BLOCK_OUTPUT_TOKENS

        tokens_per_block = avg_input + avg_output

        if tokens_per_block <= 0:
            return 1

        batch_size = int(available_tokens / tokens_per_block)
        return max(1, min(batch_size, 20))  # 至少1个，最多20个

    @classmethod
    def _estimate_input_tokens(cls, blocks: List[TemplateBlock]) -> int:
        """估算输入内容的 token 数.

        Args:
            blocks: block 列表

        Returns:
            预估输入 token 数
        """
        total_chars = sum(
            len(b.id)
            + len(b.content_text)
            + len(b.prompt or "")
            + len(b.example or "")
            for b in blocks
        )

        # 混合文本使用保守估计
        content_tokens = int(total_chars / cls.CHARS_PER_TOKEN_MIXED)

        # 加上每个 block 的结构化开销
        overhead_tokens = len(blocks) * cls.BLOCK_OVERHEAD_TOKENS

        return content_tokens + overhead_tokens
