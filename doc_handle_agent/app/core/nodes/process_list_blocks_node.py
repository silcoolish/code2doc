"""列表内容块处理节点."""

from typing import List, Set

from app.domain.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.model import TemplateBlock
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class ProcessListBlocksNode(WorkflowNode):
    """处理列表内容块节点.

    展开所有 `list=true` 的 block，将列表项替换为独立的静态 block，
    并复制子结构到每个列表项后。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "process_list_blocks"

    async def execute(self, state: AgentState) -> AgentState:
        """处理列表内容块.

        1. 遍历block列表，使用栈管理嵌套list
        2. 展开所有list block为独立静态block
        3. 统一重新赋值order_no
        """
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        try:
            state["status"] = GenerationStatus.GENERATING.value
            state["message"] = "正在处理列表内容块..."

            with log_timing("process_list_blocks", block_count=len(blocks)):
                blocks = await self._process_list_blocks(blocks, state)

            state["blocks"] = blocks
            state["total_blocks"] = len(blocks)
            state["message"] = f"列表处理完成，共{len(blocks)}个内容块待生成"

            logger.info(
                "process_list_blocks_success",
                block_count=len(blocks),
            )

        except Exception as e:
            logger.error(
                "process_list_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"列表处理失败: {str(e)}"

        return state

    async def _process_list_blocks(
        self,
        blocks: List[TemplateBlock],
        state: AgentState,
    ) -> List[TemplateBlock]:
        """处理所有list属性的block.

        使用栈来管理嵌套list：
        1. 遍历block列表
        2. 遇到list block压栈
        3. 遇到heading_level <= 栈顶的block，展开栈顶list
        4. 遇到heading_level > 栈顶且list=true的block，继续压栈
        5. 遍历完，依次弹出栈中剩余

        展开时：
        - 先生成列表项(a1,a2,a3)
        - 把index a+1到b-1的子blocks插入到每个列表项后
        - 替换后格式：(...a1,子blocks...,a2,子blocks...,a3,子blocks...,b...)
        """
        result = list(blocks)
        idx = 0
        stack: List[tuple[int, TemplateBlock, List[TemplateBlock]]] = []

        while idx < len(result):
            current_block = result[idx]

            if stack:
                top_idx, top_block, _ = stack[-1]
                current_level = current_block.heading_level if current_block.heading_level is not None else 99
                top_level = top_block.heading_level if top_block.heading_level is not None else 99
                if current_level <= top_level:
                    result = await self._expand_and_replace_list(
                        result, stack.pop(), idx, state
                    )
                    continue

            if current_block.is_list:
                children = self._find_children_in_list(current_block, result, idx)
                stack.append((idx, current_block, children))
                idx += 1
            else:
                idx += 1

        while stack:
            result = await self._expand_and_replace_list(
                result, stack.pop(), len(result), state
            )

        for i, block in enumerate(result):
            block.order_no = i

        return result

    async def _expand_and_replace_list(
        self,
        blocks: List[TemplateBlock],
        stack_item: tuple[int, TemplateBlock, List[TemplateBlock]],
        end_idx: int,
        state: AgentState,
    ) -> List[TemplateBlock]:
        """展开list block并替换到列表中."""
        list_idx, list_block, children = stack_item

        child_blocks: List[TemplateBlock] = []
        if list_idx + 1 < end_idx:
            for i in range(list_idx + 1, end_idx):
                child_blocks.append(blocks[i])

        state["message"] = f"正在处理列表: {list_block.prompt[:30] if list_block.prompt else ''}..."

        list_items = await self.content_generator.generate_list_items(
            list_block.prompt,
            state["repo_id"],
            example=list_block.example,
            list_tool=list_block.list_tool,
        )

        new_blocks: List[TemplateBlock] = []
        old_block_ids = {list_block.id}

        for i, item in enumerate(list_items):
            item_source_node_ids = item.source_refs if item.source_refs else list(list_block.source_node_ids)
            new_block = TemplateBlock(
                id=f"{list_block.id}_item_{i}",
                parent_block_id=list_block.parent_block_id,
                block_type=list_block.block_type,
                heading_level=list_block.heading_level,
                order_no=list_block.order_no + i,
                content_text=item.name,
                template="static",
                attrs={},
                source_node_ids=item_source_node_ids,
                children=[],
            )
            new_blocks.append(new_block)

            for child in child_blocks:
                child_copy = self._copy_block_with_new_parent(
                    child, new_block.id, len(new_blocks)
                )
                new_blocks.append(child_copy)
                old_block_ids.add(child.id)

        result = blocks[:list_idx] + new_blocks
        if end_idx < len(blocks):
            result.extend(blocks[end_idx:])

        for old_id in old_block_ids:
            if old_id not in state.get("generated_contents", {}):
                state["generated_contents"][old_id] = []

        return result

    def _find_children_in_list(
        self,
        parent: TemplateBlock,
        blocks: List[TemplateBlock],
        parent_idx: int,
    ) -> List[TemplateBlock]:
        """在列表中查找parent的所有直接子block."""
        children = []
        parent_level = parent.heading_level if parent.heading_level is not None else 99

        for i in range(parent_idx + 1, len(blocks)):
            block = blocks[i]
            block_level = block.heading_level if block.heading_level is not None else 99

            if block_level <= parent_level:
                break

            if block_level > parent_level:
                children.append(block)

        return children

    def _copy_block_with_new_parent(
        self,
        block: TemplateBlock,
        new_parent_id: str,
        offset: int,
    ) -> TemplateBlock:
        """复制block并设置新的parent."""
        return TemplateBlock(
            id=f"{block.id}_copy_{offset}",
            parent_block_id=new_parent_id,
            block_type=block.block_type,
            heading_level=block.heading_level,
            order_no=block.order_no + offset,
            content_text=block.content_text,
            template=block.template,
            attrs=block.attrs.copy(),
            source_refs=list(block.source_refs),
            source_node_ids=list(block.source_node_ids),
            block_style=dict(block.block_style),
            inline_styles=list(block.inline_styles),
            children=[],
        )
