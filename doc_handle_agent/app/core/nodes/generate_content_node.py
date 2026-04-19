"""生成内容节点."""

from dataclasses import dataclass
from typing import List, Set

from app.domain.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.model import TemplateBlock
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ListExpansionResult:
    """列表展开结果."""

    new_blocks: List[TemplateBlock]  # 替换原block的新block列表
    old_block_ids: Set[str]  # 被替换的原始block ID集合


class GenerateContentNode(WorkflowNode):
    """生成内容节点.

    按列表顺序处理block，优先处理list属性的子block。
    处理完所有list属性后，将整个block列表交由内容生成器批量生成。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_content"

    async def execute(self, state: AgentState) -> AgentState:
        """生成内容.

        执行流程：
        1. 处理所有list属性的block（从 deepest 开始，优先递归处理子list）
        2. 将整个block列表（包含静态和模板block）交由内容生成器批量生成
           降级策略由内容生成器内部处理
        """
        blocks: List[TemplateBlock] = state.get("blocks", [])

        if not blocks:
            return state

        try:
            state["status"] = GenerationStatus.GENERATING.value

            # 第一步：递归处理所有list属性的block
            blocks = await self._process_list_blocks(blocks, state)
            state["blocks"] = blocks
            state["total_blocks"] = len(blocks)

            # 第二步：将整个block列表交由内容生成器批量生成
            # 内容生成器内部处理降级策略
            await self._generate_blocks_content(state, blocks)

        except Exception as e:
            logger.error("generate_content_failed", error=str(e))
            state["error"] = str(e)

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

        Args:
            blocks: 原始block列表
            state: 状态（用于更新消息）

        Returns:
            处理后的block列表（所有block都没有list属性）
        """
        result = list(blocks)
        idx = 0
        # 栈中存储 (list_block_index, list_block, children_blocks)
        stack: List[tuple[int, TemplateBlock, List[TemplateBlock]]] = []

        while idx < len(result):
            current_block = result[idx]

            # 如果栈不为空，检查是否需要展开栈顶的list
            if stack:
                top_idx, top_block, _ = stack[-1]
                # 获取heading_level，正文(None)默认为99
                current_level = current_block.heading_level if current_block.heading_level is not None else 99
                top_level = top_block.heading_level if top_block.heading_level is not None else 99
                # 如果当前block的heading_level <= 栈顶block，展开栈顶
                if current_level <= top_level:
                    # 展开栈顶的list block
                    result = await self._expand_and_replace_list(
                        result, stack.pop(), idx, state
                    )
                    # 从当前位置继续（新插入的block会在后续被跳过，因为不是list）
                    continue

            # 如果当前block是list，压栈
            if current_block.is_list:
                children = self._find_children_in_list(current_block, result, idx)
                stack.append((idx, current_block, children))
                idx += 1
            else:
                idx += 1

        # 处理栈中剩余的list
        while stack:
            top_idx, top_block, children = stack[-1]
            # 展开到列表末尾
            result = await self._expand_and_replace_list(
                result, stack.pop(), len(result), state
            )

        # 统一重新赋值 order_no，从 0 开始
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
        """展开list block并替换到列表中.

        Args:
            blocks: 原始block列表
            stack_item: (list_block_index, list_block, children_blocks)
            end_idx: 结束索引（遇到此索引位置的block时停止，包含该block之后的所有内容）
            state: 状态

        Returns:
            替换后的新列表
        """
        list_idx, list_block, children = stack_item

        # 获取子block列表（a+1到b-1）
        child_blocks: List[TemplateBlock] = []
        if list_idx + 1 < end_idx:
            for i in range(list_idx + 1, end_idx):
                child_blocks.append(blocks[i])

        state["message"] = f"正在处理列表: {list_block.prompt[:30] if list_block.prompt else ''}..."

        # 生成列表项
        list_items = await self.content_generator.generate_list_items(list_block.prompt, state["repo_id"])

        # 构建新的block列表
        # 格式：(...a1,子blocks...,a2,子blocks...,a3,子blocks...,b...)
        new_blocks: List[TemplateBlock] = []
        old_block_ids = {list_block.id}

        for i, item_content in enumerate(list_items):
            # 创建列表项block
            new_block = TemplateBlock(
                id=f"{list_block.id}_item_{i}",
                parent_block_id=list_block.parent_block_id,
                block_type=list_block.block_type,
                block_title=item_content,
                heading_level=list_block.heading_level,
                order_no=list_block.order_no + i,
                markdown_content=f"- {item_content}",
                text_content=item_content,
                template="static",
                attrs={},
                source_refs=list_block.source_refs,
                children=[],
            )

            # 先添加列表项block
            new_blocks.append(new_block)

            # 再添加子blocks（复制到每个列表项后）
            for child in child_blocks:
                child_copy = self._copy_block_with_new_parent(
                    child, new_block.id, len(new_blocks)
                )
                new_blocks.append(child_copy)
                old_block_ids.add(child.id)

        # 构建新列表
        result = blocks[:list_idx] + new_blocks

        # 添加end_idx之后的block
        if end_idx < len(blocks):
            result.extend(blocks[end_idx:])

        # 记录被替换的block ID
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
        """在列表中查找parent的所有直接子block.

        利用有序性：子block一定在parent之后，且heading_level大于parent。

        Args:
            parent: 父block
            blocks: block列表
            parent_idx: parent在列表中的索引

        Returns:
            子block列表
        """
        children = []
        parent_level = parent.heading_level if parent.heading_level is not None else 99

        for i in range(parent_idx + 1, len(blocks)):
            block = blocks[i]
            block_level = block.heading_level if block.heading_level is not None else 99

            if block_level <= parent_level:
                break

            if block_level == parent_level + 1:
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
            block_title=block.block_title,
            heading_level=block.heading_level,
            order_no=block.order_no + offset,
            markdown_content=block.markdown_content,
            text_content=block.text_content,
            template=block.template,
            attrs=block.attrs.copy(),
            source_refs=list(block.source_refs),
            children=[],
        )

    async def _generate_blocks_content(
        self,
        state: AgentState,
        blocks: List[TemplateBlock],
    ) -> None:
        """生成所有block的内容.

        将整个block列表（包含静态block和模板block）交由内容生成器批量生成。
        降级策略由内容生成器内部处理，节点层不处理降级。

        生成的内容结果中包含图片ID列表作为属性。

        Args:
            state: 工作流状态
            blocks: 完整的block列表（包含静态和模板block）
        """
        if not blocks:
            logger.info("no_blocks_to_generate")
            return

        total = len(blocks)
        logger.info(
            "generate_blocks_content_start",
            total_blocks=total,
            template_blocks=sum(1 for b in blocks if b.is_template),
            static_blocks=sum(1 for b in blocks if not b.is_template),
        )

        state["message"] = f"正在生成 {total} 个内容块..."

        # 将整个block列表交给内容生成器处理
        # 内容生成器内部处理：批量生成、上下文检测、降级策略
        results = await self.content_generator.generate_blocks_batch(
            blocks=blocks,
            repo_id=state["repo_id"],
        )

        # 保存生成结果到state
        for block_id, result_list in results.items():
            state["generated_contents"][block_id] = result_list

            # 更新block的text_content、markdown_content和图片信息
            if result_list:
                block = next((b for b in blocks if b.id == block_id), None)
                if block:
                    text_content = result_list[0].text_content
                    block.text_content = text_content
                    # 根据block_type和heading_level生成markdown_content
                    block.markdown_content = self._generate_markdown_content(
                        text_content, block.block_type, block.heading_level
                    )
                    # 图片ID直接作为block属性存储
                    if result_list[0].imgs:
                        block.source_refs = result_list[0].imgs

            # 收集图片信息到state
            images = []
            for result in result_list:
                images.extend(result.imgs)

            if images:
                state["generated_images"][block_id] = images

        # 更新进度
        state["current_block_index"] = len(blocks)

        logger.info(
            "generate_blocks_content_complete",
            total_blocks=total,
            result_count=len(results),
        )

    def _generate_markdown_content(
        self, text_content: str, block_type: str, heading_level: int
    ) -> str:
        """根据text_content、block_type和heading_level生成markdown_content.

        Args:
            text_content: 生成的文本内容
            block_type: block类型 ("heading" | "paragraph")
            heading_level: 标题层级

        Returns:
            生成的markdown内容
        """
        if block_type == "heading":
            # 根据heading_level生成对应数量的#
            level = max(1, min(6, heading_level))  # 限制在1-6之间
            return f"{'#' * level} {text_content}"
        else:
            # paragraph类型直接返回文本内容
            return text_content
