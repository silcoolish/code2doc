"""解析模板节点."""

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.core.template_parser import TemplateParser
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ParseTemplateNode(WorkflowNode):
    """解析模板节点."""

    @property
    def name(self) -> str:
        return "parse_template"

    async def execute(self, state: AgentState) -> AgentState:
        """解析模板."""
        logger.info(
            "workflow_node",
            node=self.name,
            repo_id=state["repo_id"],
        )

        try:
            parser = TemplateParser()
            blocks = parser.parse(state["template_path"])

            state["content_blocks"] = blocks
            state["total_blocks"] = len(blocks)
            state["current_block_index"] = 0
            state["status"] = GenerationStatus.GENERATING.value
            state["message"] = f"解析完成，共{len(blocks)}个内容块待生成"

            logger.info(
                "parse_template_success",
                block_count=len(blocks),
            )

        except Exception as e:
            logger.error(
                "parse_template_failed",
                error=str(e),
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"模板解析失败: {str(e)}"

        return state
