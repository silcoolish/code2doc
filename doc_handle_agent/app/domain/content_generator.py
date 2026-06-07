"""内容生成器 - 负责构建提示词和解析响应."""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.generation_strategies import (
    BatchedGenerationStrategy,
    FallbackSignalError,
    FullContextStrategy,
    StrategySelector,
)
from app.domain.model import (
    DocumentBlock,
    TemplateBlock,
)
from app.domain.static_list_provider import StaticListProvider
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger
from app.config import get_settings

logger = get_logger(__name__)

STRATEGY_NAME_MAP = {
    "full_context": FullContextStrategy,
    "batched_generation": BatchedGenerationStrategy,
}


class ContentGenerator:
    """内容生成器 - 负责构建提示词、调用Agent生成内容、解析响应.

    使用策略模式处理不同规模的文档生成：
    - 小规模文档：使用完整上下文策略
    - 大规模文档：使用分批生成策略

    策略选择和降级逻辑由 StrategySelector 和各策略类内部处理。
    """

    def __init__(self, mcp_client: MCPClient, llm_client: Any = None):
        """初始化内容生成器.

        Args:
            mcp_client: MCP客户端实例
            llm_client: 可选的LLM客户端，如果为None则创建默认客户端
        """
        settings = get_settings()
        self.agent = ContentGeneratorAgent(mcp_client, llm_client)
        self.strategy_selector = StrategySelector(
            self.agent, max_batch_size=settings.batch_max_size
        )
        self.static_list_provider = StaticListProvider(mcp_client)
        self._batch_max_size = settings.batch_max_size
        logger.info("content_generator_initialized")

    async def initialize(self) -> None:
        """异步初始化内容生成器.

        代理调用底层Agent的异步初始化，获取真实的模型上下文限制。
        应在异步环境中创建后立即调用。
        """
        await self.agent.ainitialize()

    def select_strategy(
        self,
        blocks: List[TemplateBlock],
    ) -> Tuple[str, int]:
        """选择最适合的生成策略.

        Args:
            blocks: 完整block列表

        Returns:
            (策略名称, 预估token数)
        """
        strategy, estimated_tokens = self.strategy_selector.select(blocks)
        return strategy.name, estimated_tokens

    async def execute_strategy(
        self,
        strategy_name: str,
        blocks: List[TemplateBlock],
        repo_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """按指定策略执行生成.

        Args:
            strategy_name: 策略名称
            blocks: block列表
            repo_id: 仓库ID
            on_progress: 可选的进度回调函数，参数为(current, total)

        Returns:
            DocumentBlock 列表
        """
        if not blocks:
            return []

        logger.info(
            "execute_strategy_start",
            strategy_name=strategy_name,
            block_count=len(blocks),
            template_blocks=sum(1 for b in blocks if b.is_template),
            static_blocks=sum(1 for b in blocks if not b.is_template),
            repo_id=repo_id,
        )

        strategy_cls = STRATEGY_NAME_MAP.get(strategy_name)
        if not strategy_cls:
            logger.error("unknown_strategy", strategy_name=strategy_name)
            return self._build_error_results(blocks)

        if strategy_cls is BatchedGenerationStrategy:
            strategy = strategy_cls(self.agent, max_batch_size=self._batch_max_size)
        else:
            strategy = strategy_cls(self.agent)

        try:
            results = await strategy.execute(blocks, repo_id, on_progress=on_progress)
            logger.info(
                "execute_strategy_complete",
                strategy_name=strategy_name,
                total_results=len(results),
            )
            return results
        except FallbackSignalError:
            logger.warning(
                "strategy_fallback_signal",
                strategy=strategy_name,
            )
            return await self._fallback_to_next_strategy(
                strategy_name, blocks, repo_id, on_progress=on_progress
            )
        except Exception as e:
            logger.error(
                "strategy_execution_failed",
                strategy=strategy_name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return self._build_error_results(blocks)

    async def _fallback_to_next_strategy(
        self,
        failed_strategy_name: str,
        blocks: List[TemplateBlock],
        repo_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """降级到下一个策略.

        Args:
            failed_strategy_name: 失败的策略名称
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            DocumentBlock 列表
        """
        # 根据失败的策略选择降级策略
        if failed_strategy_name == "full_context":
            logger.warning("falling_back_to_batched_generation")
            strategy = BatchedGenerationStrategy(
                self.agent, max_batch_size=self._batch_max_size
            )
        else:
            # 分批策略也失败，返回错误结果
            logger.error("all_strategies_failed")
            return self._build_error_results(blocks)

        try:
            return await strategy.execute(blocks, repo_id, on_progress=on_progress)
        except FallbackSignalError:
            logger.warning(
                "fallback_strategy_signal",
                strategy=strategy.name,
            )
            return await self._fallback_to_next_strategy(
                strategy.name, blocks, repo_id, on_progress=on_progress
            )
        except Exception as e:
            logger.error(
                "fallback_strategy_failed",
                strategy=strategy.name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return self._build_error_results(blocks)

    def _build_error_results(
        self,
        blocks: List[TemplateBlock],
    ) -> List[DocumentBlock]:
        """构建错误结果列表.

        当所有策略都失败时，返回静态内容或错误占位符。

        Args:
            blocks: block列表

        Returns:
            DocumentBlock 列表
        """
        results: List[DocumentBlock] = []

        for block in blocks:
            if block.is_table:
                block_type = "table"
                if block.attrs.get("table"):
                    content = json.dumps(block.attrs["table"], ensure_ascii=False)
                elif block.is_template:
                    content = f"[内容生成失败: {block.content_text}]"
                else:
                    content = block.content_text or ""
            elif block.is_heading:
                block_type = "heading"
                content = f"[内容生成失败: {block.content_text}]" if block.is_template else (block.content_text or "")
            else:
                block_type = block.block_type or "paragraph"
                content = f"[内容生成失败: {block.content_text}]" if block.is_template else (block.content_text or "")

            results.append(
                DocumentBlock(
                    block_id=block.id,
                    block_type=block_type,
                    text_content=content,
                    heading_level=block.heading_level,
                )
            )

        return results
