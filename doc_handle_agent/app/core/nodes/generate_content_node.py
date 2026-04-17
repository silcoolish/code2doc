"""生成内容节点."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.core.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus, TemplateBlock
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ListExpansionResult:
    """列表展开结果."""

    new_blocks: List[TemplateBlock]  # 替换原block的新block列表
    old_block_ids: Set[str]  # 被替换的原始block ID集合


@dataclass
class ProcessedBlock:
    """处理后的block（包含生成内容）."""

    block: TemplateBlock
    generated_content: str = ""
    generated_children: List["ProcessedBlock"] = field(default_factory=list)


class GenerateContentNode(WorkflowNode):
    """生成内容节点.

    按列表顺序处理block，优先处理list属性的子block。
    处理完所有list属性后，为每个block生成内容。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_content"

    async def execute(self, state: AgentState) -> AgentState:
        """生成内容.

        执行流程：
        1. 处理所有list属性的block（从 deepest 开始，优先处理子list）
        2. 为所有非list block生成内容
        """
        blocks: List[TemplateBlock] = state.get("blocks", [])
        current_idx = state.get("current_block_index", 0)
        total = len(blocks)

        if current_idx >= total:
            return state

        try:
            state["status"] = GenerationStatus.GENERATING.value

            # 第一步：处理所有list属性的block
            # 从当前索引开始处理（因为前面的可能已经处理过了）
            blocks = self._process_list_blocks(blocks, current_idx, state)
            state["blocks"] = blocks
            state["total_blocks"] = len(blocks)

            # 第二步：为所有非list block生成内容
            while state["current_block_index"] < state["total_blocks"]:
                idx = state["current_block_index"]
                block = blocks[idx]

                # 跳过已处理的block（通过检查generated_contents）
                if block.id in state.get("generated_contents", {}):
                    state["current_block_index"] = idx + 1
                    continue

                # 生成内容
                await self._generate_block_content(state, block, idx)
                state["current_block_index"] = idx + 1

        except Exception as e:
            logger.error("generate_content_failed", error=str(e))
            state["error"] = str(e)

        return state

    def _process_list_blocks(
        self,
        blocks: List[TemplateBlock],
        start_idx: int,
        state: AgentState,
    ) -> List[TemplateBlock]:
        """处理所有list属性的block.

        从start_idx开始遍历，优先处理子list，再处理父list。

        Args:
            blocks: 原始block列表
            start_idx: 起始索引
            state: 状态（用于更新消息）

        Returns:
            处理后的block列表（所有block都没有list属性）
        """
        result = list(blocks)  # 复制列表
        idx = start_idx

        while idx < len(result):
            block = result[idx]

            # 如果不是list block，跳过
            if not block.is_list:
                idx += 1
                continue

            # 查找该block的所有子block（在当前列表中）
            children = self._find_children_in_list(block, result, idx)

            # 检查子block中是否有list属性的
            child_list_indices = [
                i for i, child in enumerate(children) if child.is_list
            ]

            if child_list_indices:
                # 有list属性的子block，优先处理最后一个（最深的）
                # 找到这个子block在result中的实际索引
                last_list_child = children[child_list_indices[-1]]
                child_idx_in_result = next(
                    (i for i, b in enumerate(result) if b.id == last_list_child.id),
                    -1,
                )
                if child_idx_in_result > idx:
                    # 跳到子list处处理
                    idx = child_idx_in_result
                    continue

            # 没有list属性的子block，处理当前list block
            state["message"] = f"正在处理列表: {block.prompt[:30] if block.prompt else ''}..."

            # 展开list block
            expansion = self._expand_list_block(block, children)

            # 替换原block及其子block
            result = self._replace_blocks_in_list(
                result, idx, block, children, expansion.new_blocks
            )

            # 记录被替换的block ID，避免重复处理
            for old_id in expansion.old_block_ids:
                if old_id not in state.get("generated_contents", {}):
                    state["generated_contents"][old_id] = []

            # 索引保持不变，继续处理新插入的block
            # 但新block都不是list属性，会在while循环中被跳过

        return result

    def _find_children_in_list(
        self,
        parent: TemplateBlock,
        blocks: List[TemplateBlock],
        parent_idx: int,
    ) -> List[TemplateBlock]:
        """在列表中查找parent的所有直接子block.

        利用有序性：子block一定在parent之后，且heading_level大于parent。
        在parent之后、遇到同层级或更高层级的block之前，heading_level大于parent的都是其子block。

        Args:
            parent: 父block
            blocks: block列表
            parent_idx: parent在列表中的索引

        Returns:
            子block列表
        """
        children = []
        parent_level = parent.heading_level

        for i in range(parent_idx + 1, len(blocks)):
            block = blocks[i]

            # 如果遇到同层级或更高层级的block，说明parent的子block已结束
            if block.heading_level <= parent_level:
                break

            # 只取直接子block（层级比parent大1）
            if block.heading_level == parent_level + 1:
                children.append(block)

        return children

    def _expand_list_block(
        self,
        list_block: TemplateBlock,
        children: List[TemplateBlock],
    ) -> ListExpansionResult:
        """展开list block.

        调用content_generator生成列表项，每个列表项替换为一个新的block。
        新block包含原list_block的所有子block作为其子block。

        Args:
            list_block: 带有list属性的block
            children: list_block的直接子block列表

        Returns:
            展开结果
        """
        # TODO: 这里需要调用content_generator生成列表项
        # 暂时返回一个占位实现，后续需要完善

        # 生成列表项（这里需要实际调用LLM）
        list_items = self._generate_list_items(list_block, children)

        new_blocks = []
        old_block_ids = {list_block.id}

        # 为每个列表项创建一个新的block
        for i, item_content in enumerate(list_items):
            # 创建新的block（代表一个列表项）
            new_block = TemplateBlock(
                id=f"{list_block.id}_item_{i}",
                parent_block_id=list_block.parent_block_id,
                block_type=list_block.block_type,
                block_title=item_content,  # 列表项内容作为标题
                heading_level=list_block.heading_level,
                order_no=list_block.order_no + i,
                markdown_content=f"- {item_content}",
                text_content=item_content,
                template="static",  # 列表项是静态内容
                attrs={},  # 清空attrs，不再有list属性
                source_refs=list_block.source_refs,
                children=[],  # 子block在列表中体现
            )

            # 为每个列表项添加原list_block的子block作为其子block
            # 这些子block需要复制，并调整parent_block_id
            for child in children:
                child_copy = self._copy_block_with_new_parent(
                    child, new_block.id, len(new_blocks)
                )
                new_blocks.append(child_copy)
                old_block_ids.add(child.id)

            new_blocks.append(new_block)

        return ListExpansionResult(
            new_blocks=new_blocks,
            old_block_ids=old_block_ids,
        )

    def _generate_list_items(
        self,
        list_block: TemplateBlock,
        children: List[TemplateBlock],
    ) -> List[str]:
        """生成列表项.

        TODO: 这里需要调用content_generator或LLM来生成列表项。
        暂时返回占位符。

        Args:
            list_block: list属性的block
            children: 子block列表

        Returns:
            列表项字符串列表
        """
        # 临时实现：返回示例列表项
        # 实际应该调用content_generator.generate_list_items
        prompt = list_block.prompt or "列表项"
        return [f"{prompt} 1", f"{prompt} 2", f"{prompt} 3"]

    def _copy_block_with_new_parent(
        self,
        block: TemplateBlock,
        new_parent_id: str,
        offset: int,
    ) -> TemplateBlock:
        """复制block并设置新的parent.

        Args:
            block: 原始block
            new_parent_id: 新的parent block ID
            offset: 顺序偏移量

        Returns:
            复制后的新block
        """
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

    def _replace_blocks_in_list(
        self,
        blocks: List[TemplateBlock],
        list_idx: int,
        list_block: TemplateBlock,
        children: List[TemplateBlock],
        new_blocks: List[TemplateBlock],
    ) -> List[TemplateBlock]:
        """在列表中替换block.

        用new_blocks替换list_block及其children。

        Args:
            blocks: 原始block列表
            list_idx: list_block的索引
            list_block: 被替换的list block
            children: list_block的子block列表
            new_blocks: 新的block列表

        Returns:
            替换后的新列表
        """
        # 计算需要移除的范围
        remove_count = 1  # list_block本身
        remove_ids = {list_block.id}

        # 收集所有需要移除的子block（包括嵌套的）
        for child in children:
            if child.id not in remove_ids:
                remove_ids.add(child.id)
                remove_count += 1
                # 递归收集孙block
                grand_children = self._find_children_in_list(child, blocks, list_idx)
                for gc in grand_children:
                    remove_ids.add(gc.id)

        # 构建新列表
        result = blocks[:list_idx] + new_blocks

        # 添加list_block之后的其他block（跳过被移除的）
        for i in range(list_idx + 1, len(blocks)):
            if blocks[i].id not in remove_ids:
                result.append(blocks[i])

        return result

    async def _generate_block_content(
        self,
        state: AgentState,
        block: TemplateBlock,
        idx: int,
    ) -> None:
        """为单个block生成内容.

        Args:
            state: 工作流状态
            block: 要处理的block
            idx: block索引
        """
        total = state["total_blocks"]

        logger.info(
            "generate_block_content_start",
            current=idx + 1,
            total=total,
            block_id=block.id,
            block_title=block.block_title[:30] if block.block_title else "",
        )

        state["message"] = f"正在生成第{idx + 1}/{total}个内容块: {block.block_title[:30] if block.block_title else ''}..."

        try:
            # 将TemplateBlock转换为TemplateParagraph进行生成
            from app.core.state import GeneratedContentResult, TemplateParagraph

            paragraph = TemplateParagraph(
                id=block.id,
                is_template=block.is_template,
                text=block.markdown_content,
                style_name=f"Heading {block.heading_level}" if block.is_heading else "Normal",
                is_heading=block.is_heading,
                prompt=block.prompt,
                is_list=block.is_list,
                min_length=block.min_length,
                max_length=block.max_length,
                img=block.img,
                example=block.example,
            )

            # 调用生成器
            results = await self.content_generator.generate(
                paragraph=paragraph,
                repo_id=state["repo_id"],
            )

            # 保存生成的内容
            state["generated_contents"][block.id] = results

            # 更新block的text_content
            if results:
                block.text_content = results[0].content

            # 收集图片信息
            images = []
            for result in results:
                images.extend(result.images)
                images.extend(self._collect_images_recursive(result.children))

            if images:
                state["generated_images"][block.id] = images

            logger.info(
                "generate_block_content_success",
                block_id=block.id,
                result_count=len(results),
                image_count=len(images),
            )

        except Exception as e:
            logger.error("generate_block_content_failed", block_id=block.id, error=str(e))
            from app.core.state import GeneratedContentResult

            state["generated_contents"][block.id] = [
                GeneratedContentResult(
                    is_heading=block.is_heading,
                    content=f"[生成失败: {str(e)}]",
                    children=[],
                    images=[],
                )
            ]
            block.text_content = f"[生成失败: {str(e)}]"

    def _collect_images_recursive(self, results: list) -> list:
        """递归收集所有子block的图片."""
        from app.core.state import GeneratedContentResult

        images = []
        for result in results:
            if isinstance(result, GeneratedContentResult):
                images.extend(result.images)
                if result.children:
                    images.extend(self._collect_images_recursive(result.children))
        return images
