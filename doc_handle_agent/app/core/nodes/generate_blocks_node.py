"""内容生成节点."""

import json
from typing import List

from app.domain.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.model import TemplateBlock, DocumentBlock
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class GenerateBlocksNode(WorkflowNode):
    """生成内容块节点.

    根据state中选定的策略，执行内容生成，
    更新block内容并构建doc_blocks。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_blocks"

    async def execute(self, state: AgentState) -> AgentState:
        """生成所有block的内容.

        1. 从state读取选中的策略和blocks
        2. 执行策略生成内容
        3. 更新block的content_text和source信息
        4. 构建doc_blocks
        """
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        strategy_name = state.get("selected_strategy") or "batched_generation"

        try:
            state["status"] = GenerationStatus.GENERATING.value
            state["message"] = f"正在使用 {strategy_name} 策略生成内容..."

            with log_timing("generate_blocks", strategy=strategy_name, total_blocks=len(blocks)):
                results = await self.content_generator.execute_strategy(
                    strategy_name=strategy_name,
                    blocks=blocks,
                    repo_id=state["repo_id"],
                )

            # 构建文档blocks
            doc_blocks = self._build_document_blocks(blocks, results)
            state["doc_blocks"] = doc_blocks

            logger.info(
                "generate_blocks_complete",
                strategy=strategy_name,
                total_blocks=len(blocks),
                result_count=len(results),
            )

        except Exception as e:
            logger.error(
                "generate_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"内容生成失败: {str(e)}"

        return state

    def _build_document_blocks(
        self,
        blocks: List[TemplateBlock],
        results: List[DocumentBlock],
    ) -> List[dict]:
        """构建文档blocks.

        用生成结果更新block内容后，整合到block结构中，字段对齐 workspace DocumentBlockPayload。
        """
        # 用生成结果更新block内容
        for result in results:
            if not result.block_id:
                continue
            block = next((b for b in blocks if b.id == result.block_id), None)
            if block:
                block.content_text = result.text_content
                if block.is_table and result.text_content:
                    try:
                        table_data = json.loads(result.text_content)
                        if isinstance(table_data, dict):
                            block.attrs["table"] = table_data
                    except json.JSONDecodeError:
                        logger.warning(
                            "table_content_parse_failed",
                            block_id=block.id,
                            content=result.text_content[:200],
                        )

        doc_blocks: List[dict] = []

        for block in blocks:
            block_data = {
                "id": block.id,
                "parentBlockId": block.parent_block_id,
                "blockType": block.block_type,
                "headingLevel": block.heading_level,
                "orderNo": block.order_no,
                "contentText": block.content_text,
                "blockStyle": block.block_style,
                "inlineStyles": block.inline_styles,
                "attrs": block.attrs,
                "sourceRefs": block.source_refs,
            }
            doc_blocks.append(block_data)

        return doc_blocks
