"""生成内容节点."""

from typing import List, Union

from app.core.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus, ListBlockResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GenerateContentNode(WorkflowNode):
    """生成内容节点."""

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_content"

    async def execute(self, state: AgentState) -> AgentState:
        """生成内容."""
        idx = state["current_block_index"]
        total = state["total_blocks"]

        if idx >= total:
            return state

        block = state["content_blocks"][idx]

        logger.info(
            "workflow_node",
            node=self.name,
            current=idx + 1,
            total=total,
            block_id=block.id,
            is_list=block.is_list,
        )

        try:
            state["status"] = GenerationStatus.GENERATING.value

            if block.is_list:
                state["message"] = f"正在生成第{idx + 1}/{total}个列表: {block.prompt[:30]}..."
            else:
                state["message"] = f"正在生成第{idx + 1}/{total}个内容块: {block.prompt[:30]}..."

            content = await self.content_generator.generate(
                block=block,
                repo_id=state["repo_id"],
            )

            state["generated_contents"][block.id] = content
            state["current_block_index"] = idx + 1

            # 记录生成结果
            if isinstance(content, ListBlockResult):
                logger.info(
                    "generate_content_success",
                    block_id=block.id,
                    is_list=True,
                    item_count=len(content.items),
                    has_children=bool(block.list_children),
                )
            else:
                logger.info(
                    "generate_content_success",
                    block_id=block.id,
                    is_list=False,
                    content_length=len(content),
                )

        except Exception as e:
            logger.error(
                "generate_content_failed",
                block_id=block.id,
                error=str(e),
            )
            state["generated_contents"][block.id] = f"[生成失败: {str(e)}]"
            state["current_block_index"] = idx + 1

        return state
