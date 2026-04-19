"""内容生成策略 - 定义不同上下文处理策略的实现."""

from abc import ABC, abstractmethod
from typing import Dict, List

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.prompts import (
    STRATEGY1_FULL_CONTEXT_PROMPT,
    STRATEGY2_FILTERED_CONTEXT_PROMPT,
)
from app.domain.model import DocumentBlock, TemplateBlock
from app.utils.logger import get_logger

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
                    text_content=block.text_content or block.block_title or "",
                    heading_level=block.heading_level,
                    source_refs=block.source_refs,
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
        import json

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

        # 尝试查找JSON对象边界
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
            是否是降级信号
        """
        import json

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
            system_prompt=STRATEGY1_FULL_CONTEXT_PROMPT,
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
        """构建任务消息.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID

        Returns:
            任务消息
        """
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            "## 完整文档内容块列表",
            f"共 {len(blocks)} 个内容块。请处理所有内容块：",
            "- 对于 `template='static'` 的内容块：保留其 `block_title` 或 `text_content` 作为内容",
            "- 对于 `template='template'` 的内容块：根据 `prompt` 生成新内容",
            "",
            "### 内容块列表",
            "",
        ]

        for i, block in enumerate(blocks, 1):
            task_parts.append(f"#### 内容块{i}")
            task_parts.append(f"- ID: {block.id}")
            task_parts.append(f"- 类型: {'标题' if block.is_heading else '正文'}")
            task_parts.append(f"- 模板类型: {block.template}")
            task_parts.append(f"- 标题/主题: {block.block_title}")

            if block.is_template:
                task_parts.append(f"- 生成提示词: {block.prompt or '无'}")

                # 添加长度限制
                length_constraints = []
                if block.min_length:
                    length_constraints.append(f"最少{block.min_length}字")
                if block.max_length:
                    length_constraints.append(f"最多{block.max_length}字")

                if length_constraints:
                    task_parts.append(f"- 字数要求: {', '.join(length_constraints)}")

                # 添加参考示例
                if block.example:
                    task_parts.append(f"- 参考示例: {block.example}")
            else:
                task_parts.append(f"- 静态内容: {block.text_content or block.block_title}")

            task_parts.append("")

        task_parts.extend(
            [
                "## 输出要求",
                '请按照以下JSON格式输出所有内容块的内容（包含静态和模板内容块）：',
                "```json",
                "{",
                '  "paragraphs": [',
            ]
        )

        for block in blocks:
            task_parts.extend(
                [
                    "    {",
                    f'      "paragraph_id": "{block.id}",',
                    '      "content": "生成的内容",',
                    f'      "is_heading": {str(block.is_heading).lower()}',
                    "    },",
                ]
            )

        task_parts.extend(
            [
                "  ]",
                "}",
                "```",
                "",
                "## 格式要求",
                "- 静态内容块直接保留原标题或正文",
                "- 模板内容块生成纯文本格式，不要包含任何Markdown标记",
                "- 正文必须是完整的段落式描述，不要分点简述",
                "- 正文首行必须空两格（添加两个全角空格）",
                "- 标题不要添加数字序号",
                "",
                "请开始生成。你可以使用工具来获取代码信息。",
            ]
        )

        return "\n".join(task_parts)

    def _parse_response(
        self,
        raw_content: str,
        blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """解析响应.

        Args:
            raw_content: 原始响应内容
            blocks: 原始block列表

        Returns:
            生成结果映射
        """
        import json

        results: Dict[str, List[DocumentBlock]] = {}

        json_content = self._extract_json_from_response(raw_content)

        if json_content:
            try:
                data = json.loads(json_content)
                paragraph_list = data.get("paragraphs", [])
                block_map = {b.id: b for b in blocks}

                for item in paragraph_list:
                    block_id = item.get("paragraph_id")
                    content = item.get("content", "")
                    is_heading = item.get("is_heading", False)

                    if block_id and block_id in block_map:
                        block = block_map[block_id]

                        content = self._apply_length_constraints(
                            content,
                            block.min_length,
                            block.max_length,
                        )

                        results[block_id] = [
                            DocumentBlock(
                                block_type="heading" if is_heading else "paragraph",
                                text_content=content,
                                heading_level=block.heading_level if is_heading else 0,
                                source_refs=block.source_refs,
                                imgs=[],
                            )
                        ]

                        logger.info(
                            "block_parsed",
                            block_id=block_id,
                            content_length=len(content),
                        )

            except json.JSONDecodeError as e:
                logger.error("response_json_parse_failed", error=str(e))

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
                        text_content=block.text_content
                        or block.block_title
                        or f"[内容块 '{block.id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
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
            system_prompt=STRATEGY2_FILTERED_CONTEXT_PROMPT,
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
        """构建任务消息.

        Args:
            template_blocks: 模板block列表
            repo_id: 仓库ID

        Returns:
            任务消息
        """
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            "## 模板内容块列表",
            f"共 {len(template_blocks)} 个模板内容块，请依次为每个内容块生成内容。",
            "",
        ]

        for i, block in enumerate(template_blocks, 1):
            type_desc = "标题" if block.is_heading else "正文"
            task_parts.append(f"### 内容块{i}")
            task_parts.append(f"- ID: {block.id}")
            task_parts.append(f"- 类型: {type_desc}")
            task_parts.append(f"- 主题: {block.prompt or block.block_title}")

            # 添加长度限制
            length_constraints = []
            if block.min_length:
                length_constraints.append(f"最少{block.min_length}字")
            if block.max_length:
                length_constraints.append(f"最多{block.max_length}字")

            if length_constraints:
                task_parts.append(f"- 字数要求: {', '.join(length_constraints)}")

            # 添加参考示例
            if block.example:
                task_parts.append(f"- 参考示例: {block.example}")

            task_parts.append("")

        task_parts.extend(
            [
                "## 输出要求",
                '请按照以下JSON格式输出所有内容块的内容：',
                "```json",
                "{",
                '  "paragraphs": [',
            ]
        )

        for block in template_blocks:
            task_parts.extend(
                [
                    "    {",
                    f'      "paragraph_id": "{block.id}",',
                    '      "content": "生成的段落内容",',
                    f'      "is_heading": {str(block.is_heading).lower()}',
                    "    },",
                ]
            )

        task_parts.extend(
            [
                "  ]",
                "}",
                "```",
                "",
                "## 格式要求",
                "- 使用纯文本格式，不要包含任何Markdown标记",
                "- 正文必须是完整的段落式描述，不要分点简述",
                "- 正文首行必须空两格（添加两个全角空格）",
                "- 标题不要添加数字序号",
                "",
                "请开始生成。你可以使用工具来获取代码信息。",
            ]
        )

        return "\n".join(task_parts)

    def _parse_response(
        self,
        raw_content: str,
        template_blocks: List[TemplateBlock],
    ) -> Dict[str, List[DocumentBlock]]:
        """解析响应.

        Args:
            raw_content: 原始响应内容
            template_blocks: 模板block列表

        Returns:
            生成结果映射
        """
        import json

        results: Dict[str, List[DocumentBlock]] = {}

        json_content = self._extract_json_from_response(raw_content)

        if json_content:
            try:
                data = json.loads(json_content)
                paragraph_list = data.get("paragraphs", [])
                block_map = {b.id: b for b in template_blocks}

                for item in paragraph_list:
                    block_id = item.get("paragraph_id")
                    content = item.get("content", "")
                    is_heading = item.get("is_heading", False)

                    if block_id and block_id in block_map:
                        block = block_map[block_id]

                        content = self._apply_length_constraints(
                            content,
                            block.min_length,
                            block.max_length,
                        )

                        results[block_id] = [
                            DocumentBlock(
                                block_type="heading" if is_heading else "paragraph",
                                text_content=content,
                                heading_level=block.heading_level if is_heading else 0,
                                source_refs=block.source_refs,
                                imgs=[],
                            )
                        ]

                        logger.info(
                            "block_parsed",
                            block_id=block_id,
                            content_length=len(content),
                        )

            except json.JSONDecodeError as e:
                logger.error("response_json_parse_failed", error=str(e))

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

        # 分批处理
        all_template_results: Dict[str, List[DocumentBlock]] = {}

        for i in range(0, len(template_blocks), batch_size):
            batch = template_blocks[i : i + batch_size]
            batch_num = i // batch_size + 1

            logger.info(
                "processing_batch",
                batch_num=batch_num,
                total_batches=total_batches,
                batch_size=len(batch),
            )

            batch_results = await self._process_batch(batch, repo_id, batch_num)
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

        logger.info(
            "batched_generation_strategy_complete",
            total_results=len(all_results),
            template_results=len(all_template_results),
            static_results=len(static_results),
        )

        return all_results

    def _calculate_batch_size(self, template_blocks: List[TemplateBlock]) -> int:
        """计算每批处理的block数量.

        根据预估的token数和模型上下文限制动态计算。

        Args:
            template_blocks: 模板block列表

        Returns:
            每批block数量
        """
        if not template_blocks:
            return 0

        # 预估每个block的平均token数
        total_chars = sum(
            len(b.id)
            + len(b.block_title)
            + len(b.prompt or "")
            + len(b.markdown_content)
            + len(b.text_content or "")
            + 100  # JSON开销
            for b in template_blocks
        )
        total_tokens = total_chars // 2
        avg_tokens_per_block = total_tokens // len(template_blocks)

        # 获取模型上下文限制
        context_limit = self.agent.context_limit

        # 计算安全批次大小
        safe_context = context_limit * self.SAFETY_RATIO
        batch_size = int(safe_context // avg_tokens_per_block) if avg_tokens_per_block > 0 else self.MAX_BATCH_SIZE

        # 确保每批至少1个，最多MAX_BATCH_SIZE个
        batch_size = max(1, min(batch_size, self.MAX_BATCH_SIZE))

        return batch_size

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
        """
        try:
            task_message = self._build_task_message(batch, repo_id)

            raw_content = await self.agent.generate_with_tools(
                system_prompt=STRATEGY2_FILTERED_CONTEXT_PROMPT,
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
                # 降级为单个block逐个生成
                return await self._generate_individual(batch, repo_id)

            return self._parse_response(raw_content, batch)

        except Exception as e:
            logger.error(
                "batch_processing_failed",
                batch_num=batch_num,
                error=str(e),
            )
            # 降级为单个block逐个生成
            return await self._generate_individual(batch, repo_id)

    def _build_task_message(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
    ) -> str:
        """构建批次任务消息.

        Args:
            batch: 批次block列表
            repo_id: 仓库ID

        Returns:
            任务消息
        """
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            "## 模板内容块列表",
            f"共 {len(batch)} 个模板内容块，请依次为每个内容块生成内容。",
            "",
        ]

        for i, block in enumerate(batch, 1):
            type_desc = "标题" if block.is_heading else "正文"
            task_parts.append(f"### 内容块{i}")
            task_parts.append(f"- ID: {block.id}")
            task_parts.append(f"- 类型: {type_desc}")
            task_parts.append(f"- 主题: {block.prompt or block.block_title}")

            # 添加长度限制
            length_constraints = []
            if block.min_length:
                length_constraints.append(f"最少{block.min_length}字")
            if block.max_length:
                length_constraints.append(f"最多{block.max_length}字")

            if length_constraints:
                task_parts.append(f"- 字数要求: {', '.join(length_constraints)}")

            # 添加参考示例
            if block.example:
                task_parts.append(f"- 参考示例: {block.example}")

            task_parts.append("")

        task_parts.extend(
            [
                "## 输出要求",
                '请按照以下JSON格式输出所有内容块的内容：',
                "```json",
                "{",
                '  "paragraphs": [',
            ]
        )

        for block in batch:
            task_parts.extend(
                [
                    "    {",
                    f'      "paragraph_id": "{block.id}",',
                    '      "content": "生成的段落内容",',
                    f'      "is_heading": {str(block.is_heading).lower()}',
                    "    },",
                ]
            )

        task_parts.extend(
            [
                "  ]",
                "}",
                "```",
                "",
                "## 格式要求",
                "- 使用纯文本格式，不要包含任何Markdown标记",
                "- 正文必须是完整的段落式描述，不要分点简述",
                "- 正文首行必须空两格（添加两个全角空格）",
                "- 标题不要添加数字序号",
                "",
                "请开始生成。你可以使用工具来获取代码信息。",
            ]
        )

        return "\n".join(task_parts)

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
        import json

        results: Dict[str, List[DocumentBlock]] = {}

        json_content = self._extract_json_from_response(raw_content)

        if json_content:
            try:
                data = json.loads(json_content)
                paragraph_list = data.get("paragraphs", [])
                block_map = {b.id: b for b in batch}

                for item in paragraph_list:
                    block_id = item.get("paragraph_id")
                    content = item.get("content", "")
                    is_heading = item.get("is_heading", False)

                    if block_id and block_id in block_map:
                        block = block_map[block_id]

                        content = self._apply_length_constraints(
                            content,
                            block.min_length,
                            block.max_length,
                        )

                        results[block_id] = [
                            DocumentBlock(
                                block_type="heading" if is_heading else "paragraph",
                                text_content=content,
                                heading_level=block.heading_level if is_heading else 0,
                                source_refs=block.source_refs,
                                imgs=[],
                            )
                        ]

            except json.JSONDecodeError as e:
                logger.error("batch_response_json_parse_failed", error=str(e))

        # 为未解析到的block创建默认结果
        for block in batch:
            if block.id not in results:
                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=f"[内容块 '{block.id}' 生成缺失]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        imgs=[],
                    )
                ]

        return results

    async def _generate_individual(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
    ) -> Dict[str, List[DocumentBlock]]:
        """逐个生成block（降级方案）.

        Args:
            blocks: block列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        from app.domain.prompts import CONTENT_GENERATION_SYSTEM_PROMPT

        logger.warning(
            "fallback_to_individual_generation",
            block_count=len(blocks),
        )

        results: Dict[str, List[DocumentBlock]] = {}

        for block in blocks:
            try:
                type_desc = "标题" if block.is_heading else "正文"
                task_parts = [
                    f"仓库ID: {repo_id}",
                    "",
                    f"请根据以下主题生成{type_desc}内容:",
                    f"主题: {block.prompt}",
                ]

                length_constraints = []
                if block.min_length:
                    length_constraints.append(f"最少{block.min_length}字")
                if block.max_length:
                    length_constraints.append(f"最多{block.max_length}字")

                if length_constraints:
                    task_parts.append(f"\n字数要求: {', '.join(length_constraints)}")

                if block.example:
                    task_parts.extend(["\n参考示例:", block.example])

                task_parts.append("\n请生成一段完整的内容。")
                task_parts.extend(
                    [
                        "\n格式要求：",
                        "- 使用纯文本格式，不要包含任何Markdown标记",
                        "- 直接输出内容，不要使用代码块包裹",
                    ]
                )

                if block.is_heading:
                    task_parts.append("- 标题应为纯文本，不要添加数字序号")
                else:
                    task_parts.extend(
                        [
                            "- 正文必须是完整的段落式描述，不要分点简述",
                            "- 正文首行必须空两格（添加两个全角空格）",
                            "- 正文要详细说明实现原理、处理逻辑、关键步骤等",
                        ]
                    )

                task_parts.append("\n请开始生成。你可以使用工具来获取代码信息。")
                task_message = "\n".join(task_parts)

                raw_content = await self.agent.generate_with_tools(
                    system_prompt=CONTENT_GENERATION_SYSTEM_PROMPT,
                    task_message=task_message,
                    repo_id=repo_id,
                    max_iterations=10,
                )

                content = raw_content.strip()
                import re
                content = re.sub(r'^#{1,6}\s*', '', content)
                content = re.sub(r'\*\*', '', content)
                content = re.sub(r'\*', '', content)

                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=content,
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        imgs=[],
                    )
                ]

            except Exception as e:
                logger.error(
                    "individual_generation_failed",
                    block_id=block.id,
                    error=str(e),
                )
                results[block.id] = [
                    DocumentBlock(
                        block_type="heading" if block.is_heading else "paragraph",
                        text_content=f"[生成失败: {str(e)}]",
                        heading_level=block.heading_level,
                        source_refs=block.source_refs,
                        imgs=[],
                    )
                ]

        return results


class StrategySelector:
    """策略选择器.

    根据预估的token数和模型上下文限制选择最适合的生成策略。
    """

    # 安全比例 - 使用80%的上下文限制作为安全阈值
    SAFETY_RATIO = 0.8

    def __init__(self, agent: ContentGeneratorAgent):
        """初始化策略选择器.

        Args:
            agent: 内容生成器Agent实例
        """
        self.agent = agent

    def select(self, blocks: List[TemplateBlock]) -> tuple[GenerationStrategy, int]:
        """选择最适合的生成策略.

        策略选择逻辑：
        1. 完整上下文策略：完整block列表token < 80%上下文限制
        2. 精简上下文策略：过滤静态后token < 80%上下文限制
        3. 分批生成策略：以上都不满足

        Args:
            blocks: 完整block列表

        Returns:
            (选择的策略实例, 预估token数)
        """
        context_limit = self.agent.context_limit

        # 预估完整上下文的token
        full_context_tokens = self._estimate_tokens(blocks)

        # 如果完整上下文在安全范围内，选择完整上下文策略
        if full_context_tokens < context_limit * self.SAFETY_RATIO:
            logger.info(
                "strategy_selected",
                strategy="full_context",
                estimated_tokens=full_context_tokens,
                context_limit=context_limit,
            )
            return FullContextStrategy(self.agent), full_context_tokens

        # 预估精简上下文的token（过滤静态block）
        template_blocks = [b for b in blocks if b.is_template]
        filtered_context_tokens = self._estimate_tokens(template_blocks)

        # 如果精简上下文在安全范围内，选择精简上下文策略
        if filtered_context_tokens < context_limit * self.SAFETY_RATIO:
            logger.info(
                "strategy_selected",
                strategy="filtered_context",
                estimated_tokens=filtered_context_tokens,
                context_limit=context_limit,
                template_blocks=len(template_blocks),
                static_blocks=len(blocks) - len(template_blocks),
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

    def _estimate_tokens(self, blocks: List[TemplateBlock]) -> int:
        """预估block列表的token数量.

        Args:
            blocks: block列表

        Returns:
            预估token数
        """
        # 预估每个block的字符数
        total_chars = sum(
            len(b.id)
            + len(b.block_title)
            + len(b.prompt or "")
            + len(b.markdown_content)
            + len(b.text_content or "")
            + 100  # JSON开销
            for b in blocks
        )

        # 转换为token (保守估计: 2字符/token) + 安全余量
        return total_chars // 2 + 20000
