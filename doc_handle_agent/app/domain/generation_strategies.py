"""内容生成策略 - 定义不同上下文处理策略的实现."""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.prompts import (
    FULL_CONTEXT_STRATEGY_PROMPT,
    FILTERED_CONTEXT_STRATEGY_PROMPT,
)
from app.domain.model import DocumentBlock, TemplateBlock
from app.utils.logger import get_logger
from app.utils.token_estimator import TokenEstimator

logger = get_logger(__name__)


class GenerationStrategy(ABC):
    """内容生成策略基类.

    定义内容生成的策略接口，不同策略处理不同规模的上下文。
    """

    def __init__(self, agent: ContentGeneratorAgent):
        """初始化策略.

        Args:
            agent: 内容生成器Agent实例
        """
        self.agent = agent

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称."""
        pass

    @abstractmethod
    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """执行生成策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            {block ID: [DocumentBlock]} 映射
        """
        pass

    def _build_static_results(
        self,
        static_blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """构建静态block的结果映射.

        Args:
            static_blocks: 静态block列表

        Returns:
            {block ID: [DocumentBlock]} 映射
        """
        results: Dict[str, List[DocumentBlock]] = {}

        for block in static_blocks:
            results[block.id] = [
                DocumentBlock(
                    block_type="heading" if block.is_heading else "paragraph",
                    text_content=block.content_text or "",
                    heading_level=block.heading_level,
                    source_refs=block.source_refs,
                    source_node_ids=block.source_node_ids,
                    imgs=[],
                )
            ]

        return results

    def _extract_json_from_response(self, raw_content: str) -> str | None:
        """从响应中提取JSON内容.

        Args:
            raw_content: 原始响应

        Returns:
            提取的JSON字符串，如果没有则返回None
        """

        raw_content = raw_content.strip()

        # 查找JSON代码块
        if "```json" in raw_content:
            start = raw_content.find("```json") + 7
            end = raw_content.find("```", start)
            if end > start:
                return raw_content[start:end].strip()

        # 查找普通代码块
        if "```" in raw_content:
            start = raw_content.find("```") + 3
            end = raw_content.find("```", start)
            if end > start:
                return raw_content[start:end].strip()

        # 尝试直接提取（如果内容以 [ 或 { 开头）
        stripped = raw_content.strip()
        if stripped.startswith("["):
            end = stripped.rfind("]")
            if end > 0:
                return stripped[: end + 1]
        elif stripped.startswith("{"):
            end = stripped.rfind("}")
            if end > 0:
                return stripped[: end + 1]

        # 回退：查找JSON对象边界
        json_start = raw_content.find("{")
        json_end = raw_content.rfind("}")
        if json_start >= 0 and json_end > json_start:
            return raw_content[json_start : json_end + 1]

        return None

    def _is_fallback_signal(self, raw_content: str) -> bool:
        """检查是否是降级信号.

        Args:
            raw_content: Agent返回的原始内容

        Returns:
        """

        try:
            json_content = self._extract_json_from_response(raw_content)
            if json_content:
                data = json.loads(json_content)
                return data.get("context_exceeded", False)
        except (json.JSONDecodeError, AttributeError):
            pass
        return False

    def _apply_length_constraints(
        self,
        content: str,
        min_length: int | None,
        max_length: int | None,
    ) -> str:
        """应用长度限制.

        Args:
            content: 内容
            min_length: 最小长度
            max_length: 最大长度

        Returns:
            处理后的内容
        """
        if max_length and len(content) > max_length * 1.2:
            logger.warning(
                "content_exceeds_max_length",
                actual_length=len(content),
                max_length=max_length,
            )

        return content

    def _serialize_blocks(
        self,
        blocks: List[TemplateBlock],
    ) -> List[Dict[str, Any]]:
        """将block列表序列化为LLM所需的精简格式.

        严格遵循 block_format_guide.md 的字段要求，
        过滤掉blockStyle、inlineStyles、sourceRefs等LLM不需要的字段，
        只保留与内容生成相关的核心属性。

        Args:
            blocks: 原始block列表

        Returns:
            精简后的字典列表
        """
        result: List[Dict[str, Any]] = []
        for block in blocks:
            data: Dict[str, Any] = {
                "id": block.id,
                "block_type": block.block_type,
                "heading_level": block.heading_level,
                "content_text": block.content_text,
                "template": "template" if block.is_template else "static",
            }
            if block.is_template:
                if block.prompt:
                    data["prompt"] = block.prompt
                if block.image_id:
                    data["image_id"] = block.image_id
                if block.min_length is not None:
                    data["min_length"] = block.min_length
                if block.max_length is not None:
                    data["max_length"] = block.max_length
                if block.example:
                    data["example"] = block.example
            result.append(data)
        return result

    def _build_task_message(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
        context_description: str = "",
    ) -> str:
        """构建任务消息.

        将block列表序列化为JSON后直接嵌入提示词，
        由LLM自行解析字段含义并生成内容。

        Args:
            blocks: block列表
            repo_id: 仓库ID
            context_description: 上下文描述（如"共X个内容块"）

        Returns:
            任务消息字符串
        """
        payload = self._serialize_blocks(blocks)
        blocks_json = json.dumps(payload, ensure_ascii=False, indent=2)

        parts = [
            f"仓库ID: {repo_id}",
            "",
            context_description,
            "",
            "## 内容块列表",
            "",
            "```json",
            blocks_json,
            "```",
        ]
        return "\n".join(parts)


    def _parse_blocks_from_response(
        self,
        raw_content: str,
        blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """从响应中解析block列表（统一处理新旧两种JSON格式）.

        支持格式：
        - 新格式: [{"id": "...", "block_type": "paragraph", "content_text": "..."}, ...]
        - 旧格式: {"paragraphs": [{"paragraph_id": "...", "content": "...", "is_heading": false}, ...]}

        Args:
            raw_content: 原始响应内容
            blocks: 原始block列表（用于id匹配和属性回退）

        Returns:
            {block ID: [DocumentBlock]} 解析结果映射
        """
        results: Dict[str, List[DocumentBlock]] = {}

        json_content = self._extract_json_from_response(raw_content)
        if not json_content:
            return results

        try:
            data = json.loads(json_content)

            # 统一处理两种格式：列表格式和字典格式
            if isinstance(data, list):
                paragraph_list = data
            elif isinstance(data, dict):
                paragraph_list = data.get("paragraphs", [])
            else:
                paragraph_list = []

            block_map = {b.id: b for b in blocks}

            for idx, item in enumerate(paragraph_list):
                if not isinstance(item, dict):
                    continue

                # 获取block_id（新格式用id，旧格式用paragraph_id）
                block_id = item.get("id") or item.get("paragraph_id")

                # 如果id为空，尝试按索引顺序匹配
                if not block_id and idx < len(blocks):
                    block_id = blocks[idx].id

                if not block_id or block_id not in block_map:
                    continue

                block = block_map[block_id]

                content = item.get("content_text")
                block_type = item.get("block_type")
                heading_level = item.get("heading_level")

                # 处理图片类型的block
                if block.is_image_block:
                    image_url = content.strip()
                    if image_url:
                        results[block_id] = [
                            DocumentBlock(
                                block_type=block_type,
                                text_content=f"![{block.content_text}]({image_url})",
                                heading_level=0,
                                source_refs=block.source_refs,
                                source_node_ids=block.source_node_ids,
                                imgs=[image_url],
                            )
                        ]
                        logger.info(
                            "image_block_parsed",
                            block_id=block_id,
                            image_url=image_url,
                        )
                    else:
                        results[block_id] = [
                            DocumentBlock(
                                block_type=block_type,
                                text_content=f"[图片获取失败: {block.content_text}]",
                                heading_level=0,
                                source_refs=block.source_refs,
                                source_node_ids=block.source_node_ids,
                                imgs=[],
                            )
                        ]
                    continue

                # 应用长度限制
                content = self._apply_length_constraints(
                    content,
                    block.min_length,
                    block.max_length,
                )

                results[block_id] = [
                    DocumentBlock(
                        block_type=block_type,
                        text_content=content,
                        heading_level=heading_level,
                        source_refs=block.source_refs,
                        source_node_ids=block.source_node_ids,
                        imgs=[],
                    )
                ]

                logger.info(
                    "block_parsed",
                    block_id=block_id,
                    content_length=len(content),
                )

        except json.JSONDecodeError as e:
            logger.error(
                "response_json_parse_failed",
                error=str(e),
                exc_info=True,
            )

        return results


class FullContextStrategy(GenerationStrategy):
    """完整上下文策略.

    将整个block列表（包含静态和模板）交给Agent处理。
    Agent智能识别静态block（保留原样）和模板block（生成内容）。

    适用场景：文档规模较小，总token数在模型上下文限制的安全范围内。
    """

    @property
    def name(self) -> str:
        return "full_context"

    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """执行完整上下文策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射

        Raises:
            RuntimeError: 当Agent返回降级信号时
        """
        logger.info(
            "full_context_strategy_execute",
            block_count=len(blocks),
            template_blocks=sum(1 for b in blocks if b.is_template),
            static_blocks=sum(1 for b in blocks if not b.is_template),
        )

        task_message = self._build_task_message(blocks, repo_id)

        raw_content = await self.agent.generate_with_tools(
            system_prompt=FULL_CONTEXT_STRATEGY_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            max_iterations=15,
        )

        # 检查降级信号
        if self._is_fallback_signal(raw_content):
            logger.warning("full_context_strategy_fallback_signal")
            raise RuntimeError("Agent returned fallback signal")

        return self._parse_response(raw_content, blocks)

    def _build_task_message(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> str:
        """构建任务消息."""
        desc = f"共 {len(blocks)} 个内容块（包含静态和模板内容块），请按规则处理所有内容块。"
        return super()._build_task_message(blocks, repo_id, desc)

    def _parse_response(
        self,
        raw_content: str,
        blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """解析响应.

        Args:
            raw_content: 原始响应内容
            blocks: 原始block列表
        """
        results = self._parse_blocks_from_response(raw_content, blocks)

        # 为未解析到的block创建默认结果
        for block in blocks:
            if block.id not in results:
                logger.warning(
                    "block_missing_in_response",
                    block_id=block.id,
                    fallback_to_default=True,
                )
                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=block.content_text
                        or f"[内容块 '{block.id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        source_node_ids=block.source_node_ids,
                        imgs=[],
                    )
                ]

        return results


class FilteredContextStrategy(GenerationStrategy):
    """精简上下文策略.

    过滤掉静态block，只将模板block交给Agent处理。
    生成完成后，将结果与静态block手动拼接复原。

    适用场景：静态block较多，过滤后可以减少上下文占用。
    """

    @property
    def name(self) -> str:
        return "filtered_context"

    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """执行精简上下文策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射

        Raises:
            RuntimeError: 当Agent返回降级信号时
        """
        logger.info(
            "filtered_context_strategy_execute",
            total_blocks=len(blocks),
        )

        # 分离静态和模板block
        static_blocks = [b for b in blocks if not b.is_template]
        template_blocks = [b for b in blocks if b.is_template]

        logger.info(
            "blocks_separated",
            static_count=len(static_blocks),
            template_count=len(template_blocks),
        )

        if not template_blocks:
            # 没有模板block，直接返回静态结果
            return self._build_static_results(static_blocks)

        task_message = self._build_task_message(template_blocks, repo_id)

        raw_content = await self.agent.generate_with_tools(
            system_prompt=FILTERED_CONTEXT_STRATEGY_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            max_iterations=15,
        )

        # 检查降级信号
        if self._is_fallback_signal(raw_content):
            logger.warning("filtered_context_strategy_fallback_signal")
            raise RuntimeError("Agent returned fallback signal")

        # 解析模板block的生成结果
        template_results = self._parse_response(raw_content, template_blocks)

        # 构建静态block的结果
        static_results = self._build_static_results(static_blocks)

        # 合并结果（保持原始顺序）
        all_results: Dict[str, List[DocumentBlock]] = {}
        for block in blocks:
            if block.id in template_results:
                all_results[block.id] = template_results[block.id]
            elif block.id in static_results:
                all_results[block.id] = static_results[block.id]

        logger.info(
            "filtered_context_strategy_complete",
            total_results=len(all_results),
            template_results=len(template_results),
            static_results=len(static_results),
        )

        return all_results

    def _build_task_message(
        self,
        template_blocks: List[TemplateBlock],
        repo_id: str,
    ) -> str:
        """构建任务消息."""
        desc = f"共 {len(template_blocks)} 个模板内容块，请依次为每个内容块生成内容。"
        return super()._build_task_message(template_blocks, repo_id, desc)

    def _parse_response(
        self,
        raw_content: str,
        template_blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """解析响应.

        Args:
            raw_content: 原始响应内容
            template_blocks: 模板block列表
        """
        results = self._parse_blocks_from_response(raw_content, template_blocks)

        # 为未解析到的block创建默认结果
        for block in template_blocks:
            if block.id not in results:
                logger.warning(
                    "block_missing_in_response",
                    block_id=block.id,
                    fallback_to_default=True,
                )
                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=f"[内容块 '{block.id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        source_node_ids=block.source_node_ids,
                        imgs=[],
                    )
                ]

        return results


class BatchedGenerationStrategy(GenerationStrategy):
    """分批生成策略.

    将模板block分批处理，每批单独调用Agent生成。
    最后将所有批次的结果与静态block手动拼接复原。

    适用场景：文档规模较大，即使过滤静态block后仍然超出模型上下文限制。
    """

    # 安全余量比例 - 为工具调用结果预留空间
    SAFETY_RATIO = 0.6

    # 最大每批block数量
    MAX_BATCH_SIZE = 20

    # 最大并发批次数量 - 防止同时发起过多LLM调用压垮API
    MAX_CONCURRENCY = 3

    @property
    def name(self) -> str:
        return "batched_generation"

    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """执行分批生成策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        logger.info(
            "batched_generation_strategy_execute",
            total_blocks=len(blocks),
        )

        # 分离静态和模板block
        static_blocks = [b for b in blocks if not b.is_template]
        template_blocks = [b for b in blocks if b.is_template]

        if not template_blocks:
            return self._build_static_results(static_blocks)

        # 计算每批的block数量
        batch_size = self._calculate_batch_size(template_blocks)
        total_batches = (len(template_blocks) + batch_size - 1) // batch_size

        logger.info(
            "batch_calculation",
            template_count=len(template_blocks),
            batch_size=batch_size,
            total_batches=total_batches,
        )

        # 分批处理（各批次之间无依赖，限制并发避免压垮LLM API）
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async def _process_batch_limited(
            batch: List[TemplateBlock],
            repo_id: str,
            batch_num: int,
        ) -> Dict[str, List[DocumentBlock]]:
            async with semaphore:
                return await self._process_batch(batch, repo_id, batch_num)

        tasks = []
        for i in range(0, len(template_blocks), batch_size):
            batch = template_blocks[i : i + batch_size]
            batch_num = i // batch_size + 1

            logger.info(
                "scheduling_batch",
                batch_num=batch_num,
                total_batches=total_batches,
                batch_size=len(batch),
            )

            tasks.append(_process_batch_limited(batch, repo_id, batch_num))

        # 并行执行所有批次（受semaphore限制最大并发数）
        batch_results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_template_results: Dict[str, List[DocumentBlock]] = {}
        for batch_num, batch_results in enumerate(batch_results_list, start=1):
            if isinstance(batch_results, Exception):
                logger.error(
                    "batch_processing_exception",
                    batch_num=batch_num,
                    error_type=type(batch_results).__name__,
                    error=str(batch_results),
                    exc_info=True,
                )
                continue
            all_template_results.update(batch_results)

        # 构建静态block的结果
        static_results = self._build_static_results(static_blocks)

        # 合并结果（保持原始顺序）
        all_results: Dict[str, List[DocumentBlock]] = {}
        for block in blocks:
            if block.id in all_template_results:
                all_results[block.id] = all_template_results[block.id]
            elif block.id in static_results:
                all_results[block.id] = static_results[block.id]

        # 为缺失的模板 block 补充占位符（某个批次异常时）
        template_block_ids = {b.id for b in template_blocks}
        missing_ids = template_block_ids - set(all_template_results.keys())
        for block_id in missing_ids:
            block = next((b for b in template_blocks if b.id == block_id), None)
            if block:
                logger.warning(
                    "batch_block_missing_fallback",
                    block_id=block_id,
                )
                all_results[block_id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=f"[内容块 '{block_id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        source_node_ids=block.source_node_ids,
                        imgs=[],
                    )
                ]

        logger.info(
            "batched_generation_strategy_complete",
            total_results=len(all_results),
            template_results=len(all_template_results),
            static_results=len(static_results),
            missing_blocks=len(missing_ids),
        )

        return all_results

    def _calculate_batch_size(self, template_blocks: List[TemplateBlock]) -> int:
        """计算每批处理的block数量.

        使用 TokenEstimator 根据预估的token数和模型上下文限制动态计算。

        Args:
            template_blocks: 模板block列表

        Returns:
            每批block数量
        """
        return TokenEstimator.estimate_batch_size(
            template_blocks,
            self.agent.context_limit,
        )

    async def _process_batch(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
        batch_num: int,
    ) -> Dict[str, List[DocumentBlock]]:
        """处理单个批次.

        Args:
            batch: 当前批次的block列表
            repo_id: 仓库ID
            batch_num: 批次编号

        Returns:
            批次生成结果

        Raises:
            RuntimeError: 当批次处理失败时
        """
        task_message = self._build_task_message(batch, repo_id)

        raw_content = await self.agent.generate_with_tools(
            system_prompt=FILTERED_CONTEXT_STRATEGY_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            max_iterations=15,
        )

        # 检查降级信号
        if self._is_fallback_signal(raw_content):
            logger.warning(
                "batch_fallback_signal_received",
                batch_num=batch_num,
            )
            raise RuntimeError("Agent returned fallback signal")

        return self._parse_response(raw_content, batch)

    def _build_task_message(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
    ) -> str:
        """构建批次任务消息."""
        desc = f"共 {len(batch)} 个模板内容块，请依次为每个内容块生成内容。"
        return super()._build_task_message(batch, repo_id, desc)

    def _parse_response(
        self,
        raw_content: str,
        batch: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """解析批次响应.

        Args:
            raw_content: 原始响应内容
            batch: 批次block列表

        Returns:
            生成结果映射
        """
        results = self._parse_blocks_from_response(raw_content, batch)

        # 为未解析到的block创建默认结果
        for block in batch:
            if block.id not in results:
                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=f"[内容块 '{block.id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        source_node_ids=block.source_node_ids,
                        imgs=[],
                    )
                ]

        return results


class StrategySelector:
    """策略选择器.

    根据预估的token数和模型上下文限制选择最适合的生成策略。
    """

    def __init__(self, agent: ContentGeneratorAgent):
        """初始化策略选择器.

        Args:
            agent: 内容生成器Agent实例
        """
        self.agent = agent

    def select(self, blocks: List[TemplateBlock]) -> tuple[GenerationStrategy, int]:
        """选择最适合的生成策略.

        策略选择逻辑（TokenEstimator 已内部包含安全余量）：
        1. 完整上下文策略：预估 token < 上下文限制
        2. 精简上下文策略：过滤静态后预估 token < 上下文限制
        3. 分批生成策略：以上都不满足

        Args:
            blocks: 完整block列表

        Returns:
            (选择的策略实例, 预估token数)
        """
        context_limit = self.agent.context_limit

        # 使用 TokenEstimator 预估完整上下文的 token
        full_context_tokens = TokenEstimator.estimate_full_context(blocks)

        # 如果完整上下文在安全范围内，选择完整上下文策略
        # TokenEstimator 已内部包含安全余量，直接与 context_limit 比较
        if full_context_tokens < context_limit:
            logger.info(
                "strategy_selected",
                strategy="full_context",
                estimated_tokens=full_context_tokens,
                context_limit=context_limit,
            )
            return FullContextStrategy(self.agent), full_context_tokens

        # 预估精简上下文的 token（过滤静态 block）
        template_blocks = [b for b in blocks if b.is_template]
        static_blocks = [b for b in blocks if not b.is_template]
        filtered_context_tokens = TokenEstimator.estimate_filtered_context(
            template_blocks, static_blocks
        )

        # 如果精简上下文在安全范围内，选择精简上下文策略
        if filtered_context_tokens < context_limit:
            logger.info(
                "strategy_selected",
                strategy="filtered_context",
                estimated_tokens=filtered_context_tokens,
                context_limit=context_limit,
                template_blocks=len(template_blocks),
                static_blocks=len(static_blocks),
            )
            return FilteredContextStrategy(self.agent), filtered_context_tokens

        # 否则选择分批生成策略
        logger.info(
            "strategy_selected",
            strategy="batched_generation",
            estimated_tokens=filtered_context_tokens,
            context_limit=context_limit,
            template_blocks=len(template_blocks),
        )
        return BatchedGenerationStrategy(self.agent), filtered_context_tokens
