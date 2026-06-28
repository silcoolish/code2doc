"""大纲确认节点."""

import asyncio
import copy
import json
import re
from typing import Any, Dict, List, Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.content_generator import ContentGenerator
from app.domain.model import TemplateBlock
from app.domain.prompts import LIST_GENERATION_SYSTEM_PROMPT
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)

_EXPAND_PROGRESS_INTERVAL = 50
_ORDER_KEY_LENGTH = 8
_ORDER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_STATIC_LIST_NAMES = {
    "get_all_methods": "函数列表",
    "get_all_classes": "类列表",
    "get_all_modules": "模块列表",
}


class OutlineConfirmationNode(WorkflowNode):
    """大纲确认节点.

    对文档大纲中的模板列表块进行确认和展开：
    1. 应用层递归展开 isList=true 的模板列表项，LLM 仅负责生成列表项名称
    2. 自动识别并复制子内容块，支持嵌套列表展开
    3. 优先使用静态工具（list_tool）获取列表，完全绕过 LLM 输出限制

    注意：单个模板内容块（is_template=true 且 isList=false）的 content_text
    生成由后续 generate_blocks 节点负责，本节点不处理。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.agent = content_generator.agent
        self.static_list_provider = content_generator.static_list_provider

    @property
    def name(self) -> str:
        return "outline_confirmation"

    async def execute(self, state: AgentState) -> AgentState:
        """执行大纲确认.

        1. 对 block 列表递归展开模板块
        2. 重新分配 id 和 order_no
        """
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        reporter = state.get("__progress_reporter")

        try:
            state["status"] = GenerationStatus.PARSING.value
            state["message"] = "正在确认文档大纲..."

            if reporter:
                await reporter.report_percent(0, "正在确认文档大纲...")

            with log_timing("outline_confirmation", block_count=len(blocks)):
                sorted_blocks = sorted(blocks, key=lambda b: b.order_no)
                expanded_blocks = await self._expand_blocks(
                    sorted_blocks, state["repo_id"], reporter=reporter
                )

                self._assign_block_identity(expanded_blocks)

                state["blocks"] = expanded_blocks
                state["total_blocks"] = len(expanded_blocks)
                if reporter:
                    await reporter.report_percent(100, f"大纲确认完成，共{len(expanded_blocks)}个内容块")
                else:
                    state["message"] = f"大纲确认完成，共{len(expanded_blocks)}个内容块"

            logger.info(
                "outline_confirmation_success",
                original_count=len(blocks),
                new_count=len(expanded_blocks),
            )

        except Exception as e:
            logger.error(
                "outline_confirmation_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"大纲确认失败: {str(e)}"

        return state

    async def _expand_blocks(
        self,
        blocks: List[TemplateBlock],
        repo_id: str,
        parent_context: str = "",
        reporter=None,
    ) -> List[TemplateBlock]:
        """递归展开 block 列表中的模板列表块.

        遇到 isList=true 的块时，识别子内容块、生成列表项、递归展开。
        其他块（包括单个模板内容块）原样保留，由后续节点处理。
        """
        result: List[TemplateBlock] = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if block.is_list:
                children = self._get_child_blocks(blocks, i)
                items = await self._generate_list_items(block, repo_id, parent_context)
                if reporter:
                    await reporter.report_percent(
                        35,
                        self._build_list_expand_message(block, len(items)),
                    )

                total_items = len(items)
                for item_index, item in enumerate(items, start=1):
                    item_text = item.name if hasattr(item, "name") else str(item)
                    item_source_refs = item.source_refs if hasattr(item, "source_refs") else []
                    item_block = self._create_item_block(block, item_text, item_source_refs)
                    result.append(item_block)

                    expanded_children = await self._expand_blocks(
                        children,
                        repo_id,
                        parent_context=item_text,
                        reporter=reporter,
                    )
                    result.extend(expanded_children)

                    if item_index % _EXPAND_PROGRESS_INTERVAL == 0:
                        await asyncio.sleep(0)
                        if reporter:
                            await reporter.report_percent(
                                self._calculate_expand_percent(item_index, total_items),
                                f"正在展开文档大纲 {item_index}/{total_items}...",
                            )

                i += 1 + len(children)
            else:
                result.append(copy.deepcopy(block))
                i += 1

        return result

    @staticmethod
    def _assign_block_identity(blocks: List[TemplateBlock]) -> None:
        """按当前顺序重新分配块 ID 和排序号."""
        for index, block in enumerate(blocks):
            block.order_no = OutlineConfirmationNode._key_for_sequence(index)
            block.id = str(index)

    @staticmethod
    def _key_for_sequence(index: int) -> str:
        """生成固定长度顺序排序键，避免大文档顺序块把 sort_order 撑长."""
        value = index
        chars = []
        for _ in range(_ORDER_KEY_LENGTH):
            value, remainder = divmod(value, len(_ORDER_ALPHABET))
            chars.append(_ORDER_ALPHABET[remainder])
        return "".join(reversed(chars))

    @staticmethod
    def _calculate_expand_percent(current: int, total: int) -> float:
        """把列表展开进度映射到大纲确认节点内部百分比."""
        if total <= 0:
            return 35
        return 35 + min(60, (current / total) * 60)

    @staticmethod
    def _build_list_expand_message(block: TemplateBlock, item_count: int) -> str:
        """构建列表展开进度文案."""
        list_name = block.content_text or block.list_tool or "列表"
        if block.list_tool:
            list_name = OutlineConfirmationNode._get_static_list_name(block.list_tool)
        return f"已获取{item_count}个{list_name}条目，正在展开文档大纲..."

    @staticmethod
    def _get_child_blocks(
        blocks: List[TemplateBlock], parent_index: int
    ) -> List[TemplateBlock]:
        """识别父内容块的子内容块.

        子内容块定义为：在扁平列表中，位于父块之后，且 heading_level
        大于父块 heading_level 的连续内容块，直到遇到 heading_level
        小于或等于父块的块为止。

        非标题块的 heading_level 可能为 null/None，统一视为 99。
        """
        parent = blocks[parent_index]
        parent_level = parent.heading_level or 99
        children: List[TemplateBlock] = []
        for j in range(parent_index + 1, len(blocks)):
            child_level = blocks[j].heading_level or 99
            if child_level <= parent_level:
                break
            children.append(blocks[j])
        return children

    async def _generate_list_items(
        self,
        block: TemplateBlock,
        repo_id: str,
        parent_context: str = "",
    ) -> List[Any]:
        """为模板列表块生成列表项名称.

        优先使用 block.list_tool 调用静态工具获取全量列表；
        否则调用 LLM 生成字符串数组。
        """
        if block.list_tool:
            logger.info(
                "outline_list_using_static_tool",
                list_tool=block.list_tool,
                repo_id=repo_id,
            )
            try:
                list_items = await self.static_list_provider.get_list_items(
                    block.list_tool, repo_id
                )
                if not list_items:
                    list_name = self._get_static_list_name(block.list_tool)
                    raise ValueError(
                        f"{list_name}为空，请先完成知识库初始化后再生成文档"
                    )
                return list_items
            except Exception as e:
                logger.error(
                    "static_list_tool_failed",
                    list_tool=block.list_tool,
                    error=str(e),
                )
                raise

        raw_content = await self._call_llm_for_list_items(
            block.prompt or "",
            block.example,
            repo_id,
            parent_context,
        )
        items = self._parse_string_list(raw_content)

        if not items:
            logger.warning(
                "llm_list_generation_empty",
                prompt=block.prompt,
                parent_context=parent_context,
            )
            items = [block.prompt or "未命名项"]

        return items

    @staticmethod
    def _get_static_list_name(list_tool: str) -> str:
        """获取静态列表工具的中文名称."""
        return _STATIC_LIST_NAMES.get(list_tool, list_tool)

    async def _call_llm_for_list_items(
        self,
        prompt: str,
        example: Optional[str],
        repo_id: str,
        parent_context: str = "",
    ) -> str:
        """调用 LLM 生成列表项字符串数组."""
        task_parts: List[str] = [f"仓库ID: {repo_id}"]
        if parent_context:
            task_parts.append(f"当前上下文：{parent_context}")
        task_parts.append(f"任务：{prompt}")
        if example:
            task_parts.extend(["", "## 参考示例", example])

        return await self.agent.generate_with_tools(
            system_prompt=LIST_GENERATION_SYSTEM_PROMPT,
            task_message="\n".join(task_parts),
            repo_id=repo_id,
            task_name="list_generation",
            max_iterations=10,
        )

    def _create_item_block(
        self,
        original: TemplateBlock,
        content_text: str,
        source_refs: Optional[List[Dict[str, Any]]] = None,
    ) -> TemplateBlock:
        """基于原始模板块创建列表展开项."""
        new_block = copy.deepcopy(original)

        new_block.id = ""
        new_block.content_text = content_text
        new_block.attrs.pop("isList", None)
        new_block.attrs.pop("prompt", None)
        new_block.attrs.pop("example", None)

        if new_block.block_type == "heading":
            new_block.attrs["templateType"] = "static"

        if source_refs:
            new_block.source_refs = source_refs

        new_block.attrs["template_block_id"] = original.id

        return new_block

    def _parse_string_list(self, raw_content: str) -> List[str]:
        """从 LLM 响应中解析字符串数组.

        支持以下格式：
        - JSON 数组：["项1", "项2"]
        - 含 items/blocks/list 键的 JSON 对象
        - Markdown 列表行（降级解析）
        """
        content = raw_content.strip()

        # 提取 ```json 代码块
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()

        # 尝试解析 JSON 数组或对象
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return [
                    str(item)
                    for item in data
                    if item is not None and str(item).strip()
                ]
            elif isinstance(data, dict):
                for key in ("items", "blocks", "list"):
                    if key in data and isinstance(data[key], list):
                        return [
                            str(item)
                            for item in data[key]
                            if item is not None and str(item).strip()
                        ]
        except json.JSONDecodeError:
            pass

        # 降级：按行解析 markdown 列表
        items: List[str] = []
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^(\d+[\.、]\s*|[-*•]\s+)", "", line)
            cleaned = cleaned.strip().strip('"').strip("'")
            if cleaned and cleaned not in ("[", "]", "{", "}", "``"):
                items.append(cleaned)

        return items
