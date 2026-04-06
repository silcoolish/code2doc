"""构建文档节点."""

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus, ListBlockResult
from app.infrastructure.docx_handler import DocxHandler
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BuildDocumentNode(WorkflowNode):
    """构建文档节点."""

    def __init__(self, docx_handler: DocxHandler):
        self.docx_handler = docx_handler

    @property
    def name(self) -> str:
        return "build_document"

    async def execute(self, state: AgentState) -> AgentState:
        """构建文档."""
        logger.info(
            "workflow_node",
            node=self.name,
            output_path=state["output_path"],
        )

        try:
            state["status"] = GenerationStatus.BUILDING.value
            state["message"] = "正在构建最终文档..."

            output_path = self.docx_handler.replace_blocks(
                template_path=state["template_path"],
                output_path=state["output_path"],
                block_contents=state["generated_contents"],
            )

            state["status"] = GenerationStatus.COMPLETED.value
            state["message"] = f"文档生成完成: {output_path}"

            # 统计生成内容
            total_blocks = len(state["generated_contents"])
            list_blocks = sum(
                1 for content in state["generated_contents"].values()
                if isinstance(content, ListBlockResult)
            )
            text_blocks = total_blocks - list_blocks

            logger.info(
                "build_document_success",
                output_path=output_path,
                total_blocks=total_blocks,
                text_blocks=text_blocks,
                list_blocks=list_blocks,
            )

        except Exception as e:
            logger.error(
                "build_document_failed",
                error=str(e),
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"文档构建失败: {str(e)}"

        return state
