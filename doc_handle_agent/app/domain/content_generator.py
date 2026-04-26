"""内容生成器 - 负责构建提示词和解析响应."""

import re
from typing import Any, Dict, List, Tuple

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.generation_strategies import (
    BatchedGenerationStrategy,
    FilteredContextStrategy,
    FullContextStrategy,
    StrategySelector,
)
from app.domain.model import (
    DocumentBlock,
    TemplateBlock,
)
from app.domain.static_list_provider import ListItem, StaticListProvider
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

STRATEGY_NAME_MAP = {
    "full_context": FullContextStrategy,
    "filtered_context": FilteredContextStrategy,
    "batched_generation": BatchedGenerationStrategy,
}


class ContentGenerator:
    """内容生成器 - 负责构建提示词、调用Agent生成内容、解析响应.

    使用策略模式处理不同规模的文档生成：
    - 小规模文档：使用完整上下文策略
    - 中等规模文档：使用精简上下文策略
    - 大规模文档：使用分批生成策略

    策略选择和降级逻辑由 StrategySelector 和各策略类内部处理。
    """

    def __init__(self, mcp_client: MCPClient, llm_client: Any = None):
        """初始化内容生成器.

        Args:
            mcp_client: MCP客户端实例
            llm_client: 可选的LLM客户端，如果为None则创建默认客户端
        """
        self.agent = ContentGeneratorAgent(mcp_client, llm_client)
        self.strategy_selector = StrategySelector(self.agent)
        self.static_list_provider = StaticListProvider(mcp_client)
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
    ) -> Dict[str, List[DocumentBlock]]:
        """按指定策略执行生成.

        Args:
            strategy_name: 策略名称
            blocks: block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        if not blocks:
            return {}

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

        strategy = strategy_cls(self.agent)

        try:
            results = await strategy.execute(blocks, repo_id)
            logger.info(
                "execute_strategy_complete",
                strategy_name=strategy_name,
                total_results=len(results),
            )
            return results
        except Exception as e:
            logger.error(
                "strategy_execution_failed",
                strategy=strategy_name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return await self._fallback_to_next_strategy(strategy_name, blocks, repo_id)

    async def _fallback_to_next_strategy(
        self,
        failed_strategy_name: str,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """降级到下一个策略.

        Args:
            failed_strategy_name: 失败的策略名称
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        # 根据失败的策略选择降级策略
        if failed_strategy_name == "full_context":
            logger.warning("falling_back_to_filtered_context")
            strategy = FilteredContextStrategy(self.agent)
        elif failed_strategy_name == "filtered_context":
            logger.warning("falling_back_to_batched_generation")
            strategy = BatchedGenerationStrategy(self.agent)
        else:
            # 分批策略也失败，返回错误结果
            logger.error("all_strategies_failed")
            return self._build_error_results(blocks)

        try:
            return await strategy.execute(blocks, repo_id)
        except Exception as e:
            logger.error(
                "fallback_strategy_failed",
                strategy=strategy.name,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            # 继续降级
            return await self._fallback_to_next_strategy(strategy.name, blocks, repo_id)

    def _build_error_results(
        self,
        blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """构建错误结果映射.

        当所有策略都失败时，返回静态内容或错误占位符。

        Args:
            blocks: block列表

        Returns:
            错误结果映射
        """
        results: Dict[str, List[DocumentBlock]] = {}

        for block in blocks:
            if block.is_template:
                content = f"[内容生成失败: {block.content_text}]"
            else:
                content = block.content_text or ""

            results[block.id] = [
                DocumentBlock(
                    block_type="heading" if block.is_heading else "paragraph",
                    text_content=content,
                    heading_level=block.heading_level,
                    source_refs=block.source_refs,
                    source_node_ids=block.source_node_ids,
                    imgs=[],
                )
            ]

        return results

    async def generate_list_items(
        self,
        prompt: str,
        repo_id: str,
        example: str | None = None,
        list_tool: str | None = None,
    ) -> List[ListItem]:
        """生成列表项.

        当 list_tool 有值时，直接调用静态 MCP 工具获取列表项；
        否则交由 LLM 推理生成。

        Args:
            prompt: 提示词
            repo_id: 仓库ID
            example: 生成列表项的参考示例（可选）
            list_tool: 静态工具名称（如 get_all_methods / get_all_classes / get_all_modules），为空则使用 LLM

        Returns:
            列表项列表
        """
        if list_tool:
            logger.info(
                "generate_list_items_static",
                list_tool=list_tool,
                repo_id=repo_id,
            )
            return await self.static_list_provider.get_list_items(list_tool, repo_id)

        task_message = self._build_list_task_message(prompt, repo_id, example)
        raw_content = await self.agent.generate_with_tools(
            system_prompt=LIST_GENERATION_SYSTEM_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            max_iterations=10,
        )

        item_names = self._parse_list_content(raw_content)
        return [ListItem(name=name) for name in item_names]

    def _build_list_task_message(self, prompt: str, repo_id: str, example: str | None = None) -> str:
        """构建列表生成任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            f"主题: {prompt}",
        ]

        if example:
            task_parts.extend([
                "",
                "## 参考示例",
                "以下是你应该参考的列表项示例格式：",
                "",
                example,
            ])

        task_parts.extend([
            "",
            "请开始生成。你可以使用工具来获取代码仓库信息。",
        ])

        return "\n".join(task_parts)

    def _parse_list_content(self, raw_content: str) -> List[str]:
        """解析列表格式的内容."""
        lines = raw_content.strip().split('\n')
        items = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            cleaned = re.sub(r'^(\d+[\.、]\s*|[-*•]\s+)', '', line)
            if cleaned:
                items.append(cleaned)

        if not items and raw_content.strip():
            items = [raw_content.strip()]

        return items
