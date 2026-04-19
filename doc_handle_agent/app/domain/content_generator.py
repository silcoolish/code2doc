"""内容生成器 - 负责构建提示词和解析响应."""

import re
from typing import Any, Dict, List

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.generation_strategies import (
    BatchedGenerationStrategy,
    FilteredContextStrategy,
    StrategySelector,
)
from app.domain.prompts import LIST_GENERATION_SYSTEM_PROMPT
from app.domain.model import (
    DocumentBlock,
    TemplateBlock,
)
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
        logger.info("content_generator_initialized")

    async def generate_blocks_batch(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """批量生成多个block的内容.

        根据预估的token数自动选择最适合的策略：
        1. 完整上下文策略：将整个block列表交给Agent处理
        2. 精简上下文策略：过滤静态block后交给Agent处理
        3. 分批生成策略：将模板block分批处理

        Args:
            blocks: block列表（已展开list，无嵌套children）
            repo_id: 仓库ID

        Returns:
        """
        if not blocks:
            return {}

        logger.info(
            "generate_blocks_batch_start",
            block_count=len(blocks),
            template_blocks=sum(1 for b in blocks if b.is_template),
            static_blocks=sum(1 for b in blocks if not b.is_template),
            repo_id=repo_id,
        )

        # 选择最适合的策略
        strategy, estimated_tokens = self.strategy_selector.select(blocks)

        logger.info(
            "strategy_chosen",
            strategy_name=strategy.name,
            estimated_tokens=estimated_tokens,
        )

        try:
            # 执行选中的策略
            results = await strategy.execute(blocks, repo_id)

            logger.info(
                "generate_blocks_batch_complete",
                total_results=len(results),
            )

            return results

        except Exception as e:
            # 策略执行失败，降级到下一个策略
            logger.error(
                "strategy_execution_failed",
                strategy=strategy.name,
                error=str(e),
            )
            return await self._fallback_to_next_strategy(
                strategy.name, blocks, repo_id
            )

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
                error=str(e),
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
                content = f"[内容生成失败: {block.block_title}]"
            else:
                content = block.text_content or block.block_title or ""

            results[block.id] = [
                DocumentBlock(
                    block_type="heading" if block.is_heading else "paragraph",
                    text_content=content,
                    heading_level=block.heading_level,
                    source_refs=block.source_refs,
                    imgs=[],
                )
            ]

        return results

    async def generate_list_items(
        self,
        prompt: str,
        repo_id: str,
    ) -> List[str]:
        """生成列表项.

        Args:
            prompt: 提示词
            repo_id: 仓库ID

        Returns:
            列表项字符串列表
        """
        task_message = self._build_list_task_message(prompt, repo_id)
        raw_content = await self.agent.generate_with_tools(
            system_prompt=LIST_GENERATION_SYSTEM_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            max_iterations=10,
        )

        return self._parse_list_content(raw_content)

    def _build_list_task_message(self, prompt: str, repo_id: str) -> str:
        """构建列表生成任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            f"请根据以下主题生成一个简洁的标题列表:",
            f"主题: {prompt}",
            "",
            "要求：",
            "1. 列表项应该简洁明了，每个项不超过15个字",
            "2. 列表项应该是同一级别的并列关系",
            "3. 直接输出列表，每行一个列表项",
            "4. 不要输出编号或解释",
            "5. 使用纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）",
            "",
            "请开始生成。你可以使用工具来获取代码信息。",
        ]

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
