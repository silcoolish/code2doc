"""内容生成策略 - 定义不同上下文处理策略的实现."""

import json
import re
from abc import ABC, abstractmethod

from json_repair import repair_json
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.prompts import (
    FULL_CONTEXT_STRATEGY_PROMPT,
    BATCH_CONTEXT_STRATEGY_PROMPT,
)
from app.domain.model import DocumentBlock, TemplateBlock
from app.utils.logger import get_logger
from app.utils.token_estimator import TokenEstimator

logger = get_logger(__name__)

MISSING_BLOCK_PLACEHOLDER_PATTERN = re.compile(
    r"^\[内容块\s+'[^']+'\s+生成缺失\]$"
)


class FallbackSignalError(RuntimeError):
    """降级信号异常.

    当Agent返回 context_exceeded=true 时抛出，
    用于与策略执行中的其他异常区分，只捕获此异常才触发降级逻辑。
    """
    pass


class GenerationStrategy(ABC):
    """内容生成策略基类.

    定义内容生成的策略接口，不同策略处理不同规模的上下文。
    """

    # 内容生成阶段禁止使用的探索类工具
    EXCLUDED_TOOLS = ["get_repo_stats", "get_all_nodes"]

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
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """执行生成策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID
            on_progress: 可选的进度回调函数，参数为(current, total)

        Returns:
            DocumentBlock 列表
        """
        pass

    def _build_static_results(
        self,
        static_blocks: List[TemplateBlock],
    ) -> List[DocumentBlock]:
        """构建静态block的结果列表.

        Args:
            static_blocks: 静态block列表

        Returns:
            DocumentBlock 列表
        """
        results: List[DocumentBlock] = []

        for block in static_blocks:
            block_type = self._resolve_block_type(block)
            results.append(
                DocumentBlock(
                    block_id=block.id,
                    block_type=block_type,
                    text_content=block.content_text or "",
                    heading_level=block.heading_level,
                )
            )

        return results

    @staticmethod
    def _resolve_block_type(block: TemplateBlock) -> str:
        """解析 block 的结果类型."""
        if block.is_table:
            return "table"
        if block.is_heading:
            return "heading"
        return block.block_type or "paragraph"

    @staticmethod
    def _is_missing_placeholder_content(content: Optional[str]) -> bool:
        """判断是否为缺失内容占位符."""
        if not isinstance(content, str):
            return False
        return bool(MISSING_BLOCK_PLACEHOLDER_PATTERN.match(content.strip()))

    @staticmethod
    def _normalize_generated_content(
        block_type: Optional[str],
        content: Any,
    ) -> Any:
        """按块类型清洗生成内容."""
        if not isinstance(content, str):
            return content

        if block_type == "image":
            return content.strip()
        return content

    def _build_missing_result(self, block: TemplateBlock) -> DocumentBlock:
        """构建缺失内容兜底结果."""
        return DocumentBlock(
            block_id=block.id,
            block_type=self._resolve_block_type(block),
            text_content=f"[内容块 '{block.id}' 生成缺失]",
            heading_level=block.heading_level,
        )

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
                data = self._safe_json_loads(json_content)
                return data.get("context_exceeded", False)
        except (json.JSONDecodeError, AttributeError):
            pass
        return False

    @staticmethod
    def _fix_unescaped_quotes(json_str: str) -> str:
        """修复 JSON 字符串中未转义的双引号.

        LLM 有时会在字符串值内输出未转义的双引号（如代码中的引号），
        导致 json.loads 解析失败。此函数通过向后看字符判断双引号
        是合法的字符串结束还是未转义的内部引号，对后者进行转义。
        """
        result = []
        i = 0
        length = len(json_str)
        in_string = False

        while i < length:
            char = json_str[i]

            if char == '"' and not in_string:
                # 字符串开始
                in_string = True
                result.append(char)
                i += 1
            elif char == '\\' and in_string and i + 1 < length:
                # 转义序列，原样保留
                result.append(char)
                result.append(json_str[i + 1])
                i += 2
            elif char == '"' and in_string:
                # 判断是字符串结束还是未转义的内部引号
                # 向后看（跳过空白），若遇到 JSON 结构字符则为合法结束
                j = i + 1
                while j < length and json_str[j] in ' \t\n\r':
                    j += 1
                if j < length and json_str[j] in ',:}])':
                    in_string = False
                    result.append(char)
                    i += 1
                else:
                    # 未转义的双引号
                    result.append('\\"')
                    i += 1
            else:
                result.append(char)
                i += 1

        return ''.join(result)

    def _safe_json_loads(self, json_str: str) -> Any:
        """安全地解析 JSON 字符串，自动修复常见格式错误.

        先尝试标准解析，失败时调用 json_repair 修复后重试。
        json_repair 能处理 LLM 常见的 JSON 损坏模式：
        - 字符串缺少引号包裹
        - 字符串内部未转义的双引号
        - 尾部缺少逗号或括号等

        Args:
            json_str: JSON 字符串

        Returns:
            解析后的 Python 对象

        Raises:
            json.JSONDecodeError: 当自动修复也无法解析时
        """
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            fixed = repair_json(json_str)
            return json.loads(fixed)

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
            if block.is_table:
                table_schema = self._build_table_prompt_schema(block)
                if table_schema:
                    data["table_schema"] = table_schema
            result.append(data)
        return result

    def _build_table_prompt_schema(self, block: TemplateBlock) -> Dict[str, Any]:
        """构建给 LLM 使用的轻量表格结构"""
        schema_source = block.table_schema if isinstance(block.table_schema, dict) else {}
        table_source = block.attrs.get("table")
        table = table_source if isinstance(table_source, dict) else {}

        # 优先取 table 外壳里的列定义，避免当前配置被别的来源覆盖
        columns_source = self._first_list(
            table.get("columns"),
            schema_source.get("columns"),
        )
        rows_source = self._first_list(
            table.get("rows"),
            schema_source.get("rows"),
        )
        columns = self._build_table_prompt_columns(columns_source, rows_source)
        header_row = self._read_bool_value(
            table.get("headerRow"),
            table.get("header_row"),
            schema_source.get("headerRow"),
            schema_source.get("header_row"),
            block.attrs.get("headerRow"),
            block.attrs.get("header_row"),
            default=False,
        )
        header_column = self._read_bool_value(
            table.get("headerColumn"),
            table.get("header_column"),
            schema_source.get("headerColumn"),
            schema_source.get("header_column"),
            block.attrs.get("headerColumn"),
            block.attrs.get("header_column"),
            default=False,
        )

        return {
            "columns": columns,
            "headerRow": header_row,
            "headerColumn": header_column,
            "expectedRows": len(rows_source) if rows_source else None,
            "output": 'content_text 只返回 {"rows":[["单元格1","单元格2"]]}，不要返回 columns/cells/headerRow/headerColumn',
        }

    @staticmethod
    def _first_list(*values: Any) -> List[Any]:
        """返回第一个列表值"""
        for value in values:
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _read_bool_value(*values: Any, default: bool) -> bool:
        """读取布尔配置，兼容 true/false 字符串"""
        for value in values:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
        return default

    def _build_table_prompt_columns(
        self,
        columns_source: List[Any],
        rows_source: List[Any],
    ) -> List[Dict[str, Any]]:
        """提取表格列定义，避免把完整表格结构交给模型生成"""
        columns: List[Dict[str, Any]] = []
        for index, column in enumerate(columns_source):
            column_id = f"col-{index + 1}"
            label = ""
            if isinstance(column, str):
                label = column
            elif isinstance(column, dict):
                column_id = (
                    str(column.get("id") or column.get("key") or column_id)
                )
                label = str(
                    column.get("label")
                    or column.get("title")
                    or column.get("name")
                    or ""
                )
            columns.append({"id": column_id, "label": label})

        if columns:
            return columns

        inferred_count = 0
        for row in rows_source:
            if isinstance(row, list):
                inferred_count = max(inferred_count, len(row))
            elif isinstance(row, dict):
                cells = row.get("cells")
                if isinstance(cells, dict):
                    inferred_count = max(inferred_count, len(cells))
                else:
                    inferred_count = max(inferred_count, len(row))

        if inferred_count <= 0:
            inferred_count = 3

        return [
            {"id": f"col-{index + 1}", "label": ""}
            for index in range(inferred_count)
        ]

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
    ) -> List[DocumentBlock]:
        """从响应中解析block列表（只支持新JSON格式）.

        支持格式：
        - 新格式: [{"id": "...", "block_type": "paragraph", "content_text": "..."}, ...]

        Args:
            raw_content: 原始响应内容

        Returns:
            DocumentBlock 列表
        """
        results: List[DocumentBlock] = []

        json_content = self._extract_json_from_response(raw_content)
        if not json_content:
            return results

        try:
            data = self._safe_json_loads(json_content)

            if not isinstance(data, list):
                logger.warning(
                    "response_not_list_format",
                    data_type=type(data).__name__,
                )
                return results

            for item in data:
                if not isinstance(item, dict):
                    continue

                block_id = item.get("id")
                content = item.get("content_text")
                block_type = item.get("block_type")
                heading_level = item.get("heading_level")
                source_refs = item.get("sourceRefs") or item.get("source_refs") or []
                if not isinstance(source_refs, list):
                    source_refs = []
                content = self._normalize_generated_content(block_type, content)

                results.append(
                    DocumentBlock(
                        block_id=block_id,
                        block_type=block_type,
                        text_content=content,
                        heading_level=heading_level,
                        source_refs=source_refs,
                    )
                )

                logger.info(
                    "block_parsed",
                    block_id=block_id,
                    content_length=len(content) if content else 0,
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
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """执行完整上下文策略.

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID
            on_progress: 可选的进度回调函数（单批次策略忽略此参数）

        Returns:
            DocumentBlock 列表

        Raises:
            FallbackSignalError: 当Agent返回降级信号时
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
            task_name="full_context",
            max_iterations=15,
            excluded_tools=self.EXCLUDED_TOOLS,
        )

        # 检查降级信号
        if self._is_fallback_signal(raw_content):
            logger.warning("full_context_strategy_fallback_signal")
            raise FallbackSignalError("Agent returned fallback signal")

        return self._parse_response(raw_content, blocks)

    def _build_task_message(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
        context_description: str = ""
    ) -> str:
        """构建任务消息."""
        desc = f"共 {len(blocks)} 个内容块（包含静态和模板内容块），请按规则处理所有内容块。"
        return super()._build_task_message(blocks, repo_id, desc)

    def _parse_response(
        self,
        raw_content: str,
        blocks: List[TemplateBlock],
    ) -> List[DocumentBlock]:
        """解析响应.

        Args:
            raw_content: 原始响应内容
            blocks: 原始block列表
        """
        results = self._parse_blocks_from_response(raw_content)
        result_ids = {r.block_id for r in results if r.block_id}

        # 为未解析到的block创建默认结果
        for block in blocks:
            if block.id not in result_ids:
                logger.warning(
                    "block_missing_in_response",
                    block_id=block.id,
                    fallback_to_default=True,
                )
                if block.content_text and not self._is_missing_placeholder_content(block.content_text):
                    results.append(
                        DocumentBlock(
                            block_id=block.id,
                            block_type=self._resolve_block_type(block),
                            text_content=block.content_text,
                            heading_level=block.heading_level,
                        )
                    )
                else:
                    results.append(self._build_missing_result(block))

        return results


class BatchedGenerationStrategy(GenerationStrategy):
    """分批生成策略.

    按文档标题层级将 block 分组，每批保留完整的章节结构（含静态块），
    由 Agent 逐批生成。批次内静态块作为结构上下文，template 块作为生成目标。

    适用场景：文档规模较大，即使过滤静态block后仍然超出模型上下文限制。
    """

    @property
    def name(self) -> str:
        return "batched_generation"

    async def execute(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[DocumentBlock]:
        """执行分批生成策略.

        按需构建批次：生成一个批次，处理一个批次，再生成下一个。
        每个批次从上一个批次结束位置的下一个 block 开始，
        按原始列表顺序逐个添加 block，若发现父 block 不在当前批次，
        则将父 block 按原始顺序插入到正确位置，直到根 block 也在批次中。

        Args:
            blocks: 完整block列表
            repo_id: 仓库ID
            on_progress: 可选的进度回调函数，参数为(current, total)

        Returns:
            DocumentBlock 列表
        """
        logger.info(
            "batched_generation_strategy_execute",
            total_blocks=len(blocks),
        )

        static_blocks = [b for b in blocks if not b.is_template]
        template_blocks = [b for b in blocks if b.is_template]

        if not template_blocks:
            return self._build_static_results(static_blocks)

        block_map = {b.id: b for b in blocks}
        index_map = {b.id: i for i, b in enumerate(blocks)}

        all_template_results: List[DocumentBlock] = []
        generated_ids: Set[str] = set()
        i = 0
        batch_num = 0

        while i < len(blocks):
            batch_num += 1
            batch, next_i = self._build_next_batch(
                blocks=blocks,
                start_idx=i,
                block_map=block_map,
                index_map=index_map,
                generated_ids=generated_ids,
            )

            if not batch:
                break

            templates_to_generate = [
                b for b in batch if b.is_template and b.id not in generated_ids
            ]
            if not templates_to_generate:
                logger.info(
                    "batch_all_generated",
                    batch_num=batch_num,
                    start_idx=i,
                    next_idx=next_i,
                )
                i = next_i
                continue

            logger.info(
                "processing_batch",
                batch_num=batch_num,
                start_idx=i,
                next_idx=next_i,
                batch_size=len(batch),
                template_count=len(templates_to_generate),
                static_count=len(batch) - len(templates_to_generate),
            )

            try:
                batch_results = await self._process_batch(
                    batch, repo_id, batch_num, generated_ids
                )
            except FallbackSignalError:
                logger.warning(
                    "batch_fallback_signal",
                    batch_num=batch_num,
                )
                raise
            except Exception as e:
                logger.error(
                    "batch_processing_exception",
                    batch_num=batch_num,
                    error_type=type(e).__name__,
                    error=str(e),
                    exc_info=True,
                )
                i = next_i
                continue

            # 替换模板内容并记录已生成 block
            for result in batch_results:
                if result.block_id:
                    all_template_results.append(result)
                    generated_ids.add(result.block_id)
                    block = block_map.get(result.block_id)
                    if block:
                        block.content_text = result.text_content

            # 触发进度回调
            if on_progress:
                on_progress(len(generated_ids), len(template_blocks))

            i = next_i

        # 构建静态block的结果
        static_results = self._build_static_results(static_blocks)

        # 合并结果（保持原始顺序）
        result_map = {
            r.block_id: r for r in all_template_results + static_results if r.block_id
        }
        all_results: List[DocumentBlock] = []
        for block in blocks:
            if block.id in result_map:
                all_results.append(result_map[block.id])
            else:
                all_results.append(self._build_missing_result(block))

        # 统计缺失的模板 block
        template_block_ids = {b.id for b in template_blocks}
        result_ids = {r.block_id for r in all_template_results if r.block_id}
        missing_ids = template_block_ids - result_ids

        logger.info(
            "batched_generation_strategy_complete",
            total_results=len(all_results),
            template_results=len(all_template_results),
            static_results=len(static_results),
            missing_blocks=len(missing_ids),
        )

        return all_results

    def _get_ancestor_ids(
        self,
        block_idx: int,
        blocks: List[TemplateBlock],
    ) -> List[str]:
        """基于 heading_level 获取祖先ID列表.

        从当前节点向列表之前找最近的标题等级低于该节点的节点，
        直到根节点。不使用 parent_block_id 字段。

        Args:
            block_idx: 当前 block 在列表中的索引
            blocks: 完整 block 列表

        Returns:
            祖先ID列表（按文档顺序，根在前）
        """
        if block_idx <= 0 or block_idx >= len(blocks):
            return []

        current = blocks[block_idx]
        ancestors: List[str] = []

        if current.is_heading:
            search_level = current.heading_level
        else:
            # 非标题节点：先找到向前最近的标题作为锚点
            search_level = 0
            for j in range(block_idx - 1, -1, -1):
                if blocks[j].is_heading:
                    search_level = blocks[j].heading_level
                    ancestors.insert(0, blocks[j].id)
                    break
            if search_level == 0:
                return []

        # 继续向上找祖先标题
        for j in range(block_idx - 1, -1, -1):
            candidate = blocks[j]
            if candidate.is_heading and candidate.heading_level < search_level:
                ancestors.insert(0, candidate.id)
                search_level = candidate.heading_level
                if search_level == 1:
                    break

        return ancestors

    # 每批最大模板 block 数量（静态/标题 block 不计入限制）
    MAX_TEMPLATE_BLOCKS_PER_BATCH = 20

    def _build_next_batch(
        self,
        blocks: List[TemplateBlock],
        start_idx: int,
        block_map: Dict[str, TemplateBlock],
        index_map: Dict[str, int],
        generated_ids: Optional[Set[str]] = None,
    ) -> Tuple[List[TemplateBlock], int]:
        """从 start_idx 开始构建下一个批次.

        按原始列表顺序逐个添加 block，若父 block 不在当前批次，
        则按原始顺序插入到正确位置，直到根 block 也在批次中。
        当待生成的模板 block 数量达到上限时停止（静态/标题 block 不计入限制）。

        Args:
            blocks: 完整 block 列表
            start_idx: 本次起始索引（包含）
            block_map: block ID 到 block 的映射
            index_map: block ID 到原始索引的映射
            generated_ids: 已生成完毕的 block ID 集合

        Returns:
            (批次 block 列表, 下一个起始索引)
        """
        if start_idx >= len(blocks):
            return [], start_idx

        generated_ids = generated_ids or set()
        batch: List[TemplateBlock] = []
        batch_ids: Set[str] = set()
        i = start_idx

        def _count_templates_to_generate(blocks_to_count: List[TemplateBlock]) -> int:
            """统计待生成的模板 block 数量."""
            return sum(
                1 for b in blocks_to_count if b.is_template and b.id not in generated_ids
            )

        while i < len(blocks):
            block = blocks[i]
            ancestor_ids = self._get_ancestor_ids(i, blocks)

            # 需要加入的祖先（不在当前批次中）
            needed_ancestor_ids = [aid for aid in ancestor_ids if aid not in batch_ids]
            needed_ancestors = [block_map[aid] for aid in needed_ancestor_ids if aid in block_map]

            blocks_to_add = needed_ancestors.copy()
            if block.id not in batch_ids:
                blocks_to_add.append(block)

            # 检查待生成的模板 block 是否超出限制
            current_templates = _count_templates_to_generate(batch)
            adding_templates = _count_templates_to_generate(blocks_to_add)
            if batch and current_templates + adding_templates > self.MAX_TEMPLATE_BLOCKS_PER_BATCH:
                break

            # 按原始顺序插入祖先
            for anc in needed_ancestors:
                if anc.id in batch_ids:
                    continue
                insert_pos = self._find_insert_position(batch, anc, index_map)
                batch.insert(insert_pos, anc)
                batch_ids.add(anc.id)

            # 加入当前 block（按原始顺序应位于所有已处理 block 之后）
            if block.id not in batch_ids:
                batch.append(block)
                batch_ids.add(block.id)

            i += 1

        return batch, i

    @staticmethod
    def _find_insert_position(
        batch: List[TemplateBlock],
        block: TemplateBlock,
        index_map: Dict[str, int],
    ) -> int:
        """找到 block 在 batch 中的正确插入位置，保持原始相对顺序.

        Args:
            batch: 当前批次
            block: 待插入的 block
            index_map: block ID 到原始索引的映射

        Returns:
            插入位置索引
        """
        block_idx = index_map[block.id]
        for j, b in enumerate(batch):
            if index_map[b.id] > block_idx:
                return j
        return len(batch)

    async def _process_batch(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
        batch_num: int,
        generated_ids: Optional[Set[str]] = None,
    ) -> List[DocumentBlock]:
        """处理单个批次.

        Args:
            batch: 当前批次的block列表（含 static 和 template）
            repo_id: 仓库ID
            batch_num: 批次编号
            generated_ids: 已在之前批次中生成完毕的 block ID 集合

        Returns:
            批次生成结果

        Raises:
            FallbackSignalError: 当批次处理失败时
        """
        task_message = self._build_task_message(batch, repo_id, generated_ids)

        raw_content = await self.agent.generate_with_tools(
            system_prompt=BATCH_CONTEXT_STRATEGY_PROMPT,
            task_message=task_message,
            repo_id=repo_id,
            task_name="batch",
            max_iterations=15,
            excluded_tools=self.EXCLUDED_TOOLS,
        )

        # 检查降级信号
        if self._is_fallback_signal(raw_content):
            logger.warning(
                "batch_fallback_signal_received",
                batch_num=batch_num,
            )
            raise FallbackSignalError("Agent returned fallback signal")

        results = self._parse_response(
            raw_content,
            batch,
            generated_ids=generated_ids,
            fill_missing_placeholders=False,
        )

        for result in results:
            if not result.block_id:
                continue
            block = next((item for item in batch if item.id == result.block_id), None)
            if block:
                block.content_text = result.text_content

        missing_blocks = self._get_missing_template_blocks(
            batch,
            results,
            generated_ids=generated_ids,
        )
        if not missing_blocks:
            return self._fill_missing_template_results(
                batch,
                results,
                generated_ids=generated_ids,
            )

        # 首轮批次可能被模型漏回部分模板块，合并重试避免单块串行放大耗时
        retry_results = await self._retry_missing_blocks(
            batch=batch,
            repo_id=repo_id,
            batch_num=batch_num,
            generated_ids=generated_ids,
            missing_blocks=missing_blocks,
            existing_results=results,
        )

        for result in retry_results:
            if not result.block_id:
                continue
            block = next((item for item in batch if item.id == result.block_id), None)
            if block:
                block.content_text = result.text_content

        return self._fill_missing_template_results(
            batch,
            results + retry_results,
            generated_ids=generated_ids,
        )

    def _build_task_message(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
        generated_ids: Optional[Set[str]] = None,
        active_template_ids: Optional[Set[str]] = None,
    ) -> str:
        """构建批次任务消息.

        已生成的 block 会被当作 static 处理，避免 LLM 重复生成。
        active_template_ids 用于缺失块重试，限制本轮只生成目标模板块
        """
        generated_ids = generated_ids or set()
        target_template_ids = self._get_batch_target_ids(
            batch,
            generated_ids,
            active_template_ids,
        )
        template_count = len(target_template_ids)
        static_count = len(batch) - template_count
        desc = (
            f"共 {len(batch)} 个内容块（含 {template_count} 个模板块、"
            f"{static_count} 个静态块）。请为模板块生成内容，静态块保持原样。"
        )

        retry_scope = ""
        if active_template_ids is not None:
            retry_scope = (
                f"本次只生成以下模板块: {', '.join(sorted(active_template_ids))}。"
                "其他内容块仅作为上下文保留原样，返回的 JSON 数组中只保留这些目标模板块，不要回传无关 static 块。"
            )
        else:
            retry_scope = (
                f"本次只生成以下模板块: {', '.join(sorted(target_template_ids))}。"
                "返回的 JSON 数组只包含这些模板块，不要回传 static 块。"
            )

        payload = self._serialize_batch_blocks(batch, generated_ids, active_template_ids)
        blocks_json = json.dumps(payload, ensure_ascii=False, indent=2)

        parts = [
            f"仓库ID: {repo_id}",
            "",
            desc,
        ]
        if retry_scope:
            parts.extend(["", retry_scope])
        parts.extend([
            "",
            "## 内容块列表",
            "",
            "```json",
            blocks_json,
            "```",
        ])
        return "\n".join(parts)

    @staticmethod
    def _should_generate_in_batch(
        block: TemplateBlock,
        generated_ids: Set[str],
        active_template_ids: Optional[Set[str]] = None,
    ) -> bool:
        """判断当前批次中某个块是否需要生成."""
        if not block.is_template or block.id in generated_ids:
            return False
        if active_template_ids is None:
            return True
        return block.id in active_template_ids

    def _get_batch_target_ids(
        self,
        batch: List[TemplateBlock],
        generated_ids: Set[str],
        active_template_ids: Optional[Set[str]] = None,
    ) -> Set[str]:
        """收口当前批次真正需要模型生成的模板块 ID"""
        return {
            block.id
            for block in batch
            if self._should_generate_in_batch(
                block,
                generated_ids,
                active_template_ids,
            )
        }

    def _serialize_batch_blocks(
        self,
        blocks: List[TemplateBlock],
        generated_ids: Optional[Set[str]] = None,
        active_template_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """将block列表序列化为LLM所需的精简格式.

        已生成的 block 会被当作 static 处理，避免 LLM 重复生成内容。
        active_template_ids 存在时，仅目标模板块暴露为 template

        Args:
            blocks: 原始block列表
            generated_ids: 已生成完毕的 block ID 集合
            active_template_ids: 本轮允许生成的模板 block ID 集合

        Returns:
            精简后的字典列表
        """
        generated_ids = generated_ids or set()
        result: List[Dict[str, Any]] = []
        for block in blocks:
            should_generate = self._should_generate_in_batch(
                block,
                generated_ids,
                active_template_ids,
            )
            data: Dict[str, Any] = {
                "id": block.id,
                "block_type": block.block_type,
                "heading_level": block.heading_level,
                "content_text": block.content_text,
                "template": "template" if should_generate else "static",
            }
            if should_generate:
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
            if block.is_table:
                table_schema = self._build_table_prompt_schema(block)
                if table_schema:
                    data["table_schema"] = table_schema
            result.append(data)
        return result

    def _parse_response(
        self,
        raw_content: str,
        batch: List[TemplateBlock],
        generated_ids: Optional[Set[str]] = None,
        active_template_ids: Optional[Set[str]] = None,
        fill_missing_placeholders: bool = True,
    ) -> List[DocumentBlock]:
        """解析批次响应，只提取 template 块的结果，static 块使用原始内容.

        Args:
            raw_content: 原始响应内容
            batch: 批次block列表（含 static 和 template）
            fill_missing_placeholders: 是否为未返回的模板块补缺失占位

        Returns:
            DocumentBlock 列表
        """
        generated_ids = generated_ids or set()
        results = self._parse_blocks_from_response(raw_content)
        target_template_ids = self._get_batch_target_ids(
            batch,
            generated_ids,
            active_template_ids,
        )
        filtered_results = [
            result
            for result in results
            if result.block_id in target_template_ids
        ]

        if not fill_missing_placeholders:
            return filtered_results

        return self._fill_missing_template_results(
            batch,
            filtered_results,
            generated_ids=generated_ids,
            active_template_ids=active_template_ids,
        )

    def _get_missing_template_blocks(
        self,
        batch: List[TemplateBlock],
        results: List[DocumentBlock],
        generated_ids: Optional[Set[str]] = None,
        active_template_ids: Optional[Set[str]] = None,
    ) -> List[TemplateBlock]:
        """找出当前批次中仍未生成成功的模板块."""
        generated_ids = generated_ids or set()
        result_ids = {result.block_id for result in results if result.block_id}
        target_template_ids = self._get_batch_target_ids(
            batch,
            generated_ids,
            active_template_ids,
        )
        return [
            block
            for block in batch
            if block.id in target_template_ids and block.id not in result_ids
        ]

    def _fill_missing_template_results(
        self,
        batch: List[TemplateBlock],
        results: List[DocumentBlock],
        generated_ids: Optional[Set[str]] = None,
        active_template_ids: Optional[Set[str]] = None,
    ) -> List[DocumentBlock]:
        """为当前批次仍缺失的模板块补占位结果."""
        generated_ids = generated_ids or set()
        result_ids = {result.block_id for result in results if result.block_id}
        target_template_ids = self._get_batch_target_ids(
            batch,
            generated_ids,
            active_template_ids,
        )
        filled_results = list(results)

        for block in batch:
            if block.id not in target_template_ids or block.id in result_ids:
                continue
            filled_results.append(self._build_missing_result(block))

        return filled_results

    def _build_retry_batch(
        self,
        batch: List[TemplateBlock],
        missing_block: TemplateBlock,
    ) -> List[TemplateBlock]:
        """为缺失块重试构建最小上下文批次."""
        try:
            target_index = next(
                index for index, block in enumerate(batch) if block.id == missing_block.id
            )
        except StopIteration:
            return [missing_block]

        block_map = {block.id: block for block in batch}
        selected_ids: Set[str] = set()
        retry_batch: List[TemplateBlock] = []

        ancestor_ids = self._get_ancestor_ids(target_index, batch)
        for ancestor_id in ancestor_ids:
            ancestor_block = block_map.get(ancestor_id)
            if ancestor_block and ancestor_block.id not in selected_ids:
                retry_batch.append(ancestor_block)
                selected_ids.add(ancestor_block.id)

        previous_context: List[TemplateBlock] = []
        previous_index = target_index - 1
        while previous_index >= 0:
            previous_block = batch[previous_index]
            if previous_block.is_heading:
                break
            if previous_block.id not in selected_ids:
                previous_context.append(previous_block)
            previous_index -= 1
            if len(previous_context) >= 2:
                break

        for previous_block in reversed(previous_context):
            retry_batch.append(previous_block)
            selected_ids.add(previous_block.id)

        if missing_block.id not in selected_ids:
            retry_batch.append(missing_block)
            selected_ids.add(missing_block.id)

        next_index = target_index + 1
        next_context_count = 0
        while next_index < len(batch):
            next_block = batch[next_index]
            if next_block.is_heading:
                break
            if next_block.id not in selected_ids:
                retry_batch.append(next_block)
                selected_ids.add(next_block.id)
                next_context_count += 1
            next_index += 1
            if next_context_count >= 2:
                break

        return retry_batch

    def _build_merged_retry_batch(
        self,
        batch: List[TemplateBlock],
        missing_blocks: List[TemplateBlock],
    ) -> List[TemplateBlock]:
        """为多个缺失块构建一次合并重试上下文"""
        selected_ids: Set[str] = set()
        retry_batch: List[TemplateBlock] = []

        def add_block(block: TemplateBlock) -> None:
            if block.id in selected_ids:
                return
            retry_batch.append(block)
            selected_ids.add(block.id)

        for missing_block in missing_blocks:
            for block in self._build_retry_batch(batch, missing_block):
                add_block(block)

        # 多个缺失块共享上下文时按原顺序重排，避免重试提示词来回跳跃
        index_map = {block.id: index for index, block in enumerate(batch)}
        retry_batch.sort(key=lambda item: index_map.get(item.id, len(batch)))
        return retry_batch

    async def _retry_missing_blocks(
        self,
        batch: List[TemplateBlock],
        repo_id: str,
        batch_num: int,
        generated_ids: Optional[Set[str]],
        missing_blocks: List[TemplateBlock],
        existing_results: List[DocumentBlock],
    ) -> List[DocumentBlock]:
        """合并重试批次中缺失的模板块"""
        retry_results: List[DocumentBlock] = []
        retry_generated_ids = set(generated_ids or set())
        retry_generated_ids.update(
            result.block_id for result in existing_results if result.block_id
        )

        active_template_ids = {block.id for block in missing_blocks}
        logger.warning(
            "retry_missing_blocks_merged",
            batch_num=batch_num,
            block_ids=sorted(active_template_ids),
        )
        try:
            # 这里只补一次，避免回到逐块串行重试
            retry_batch = self._build_merged_retry_batch(batch, missing_blocks)
            task_message = self._build_task_message(
                batch=retry_batch,
                repo_id=repo_id,
                generated_ids=retry_generated_ids,
                active_template_ids=active_template_ids,
            )
            raw_content = await self.agent.generate_with_tools(
                system_prompt=BATCH_CONTEXT_STRATEGY_PROMPT,
                task_message=task_message,
                repo_id=repo_id,
                task_name="batch_retry",
                max_iterations=8,
                excluded_tools=self.EXCLUDED_TOOLS,
            )
            if self._is_fallback_signal(raw_content):
                logger.warning(
                    "retry_missing_blocks_fallback_signal",
                    batch_num=batch_num,
                    block_ids=sorted(active_template_ids),
                )
                return retry_results

            parsed_retry_results = self._parse_response(
                raw_content,
                retry_batch,
                generated_ids=retry_generated_ids,
                active_template_ids=active_template_ids,
                fill_missing_placeholders=False,
            )
            seen_retry_ids: Set[str] = set()
            for retry_result in parsed_retry_results:
                if retry_result.block_id not in active_template_ids:
                    continue
                if retry_result.block_id in seen_retry_ids:
                    continue
                retry_results.append(retry_result)
                seen_retry_ids.add(retry_result.block_id)
                retry_generated_ids.add(retry_result.block_id)
                resolved_block = next(
                    (item for item in batch if item.id == retry_result.block_id),
                    None,
                )
                if resolved_block:
                    resolved_block.content_text = retry_result.text_content

            missing_retry_ids = active_template_ids - seen_retry_ids
            if missing_retry_ids:
                logger.warning(
                    "retry_missing_blocks_partial",
                    batch_num=batch_num,
                    missing_block_ids=sorted(missing_retry_ids),
                )
        except Exception as ex:
            logger.warning(
                "retry_missing_blocks_failed",
                batch_num=batch_num,
                block_ids=sorted(active_template_ids),
                error_type=type(ex).__name__,
                error=str(ex),
            )

        return retry_results


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

    # 每 1K token 预估生成耗时（秒），用于时间预算判定
    TIME_PER_1K_TOKENS = 3.0
    TIME_SAFETY_RATIO = 0.7

    def select(self, blocks: List[TemplateBlock]) -> tuple[GenerationStrategy, int]:
        """选择最适合的生成策略.

        策略选择逻辑（TokenEstimator 已内部包含安全余量）：
        1. 完整上下文策略：预估 token < 上下文限制 且 预估耗时 < 超时阈值
        2. 分批生成策略：以上不满足

        Args:
            blocks: 完整block列表

        Returns:
            (选择的策略实例, 预估token数)
        """
        context_limit = self.agent.context_limit
        timeout_limit = self.agent.timeout

        # 使用 TokenEstimator 预估完整上下文的 token
        full_context_tokens = TokenEstimator.estimate_full_context(blocks)

        # 预估耗时判定：大上下文即使未越界也可能因处理缓慢而超时
        estimated_time_sec = (full_context_tokens / 1000) * self.TIME_PER_1K_TOKENS
        fits_time_budget = estimated_time_sec < timeout_limit * self.TIME_SAFETY_RATIO

        # 如果完整上下文在安全范围内且时间预算充足，选择完整上下文策略
        if full_context_tokens < context_limit and fits_time_budget:
            logger.info(
                "strategy_selected",
                strategy="full_context",
                estimated_tokens=full_context_tokens,
                context_limit=context_limit,
                estimated_time_sec=round(estimated_time_sec, 1),
                timeout_limit=timeout_limit,
            )
            return FullContextStrategy(self.agent), full_context_tokens

        # 否则选择分批生成策略（保留完整文档结构，按标题层级分批）
        logger.info(
            "strategy_selected",
            strategy="batched_generation",
            estimated_tokens=full_context_tokens,
            context_limit=context_limit,
            estimated_time_sec=round(estimated_time_sec, 1),
            timeout_limit=timeout_limit,
        )
        return BatchedGenerationStrategy(self.agent), full_context_tokens
