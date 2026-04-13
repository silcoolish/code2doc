"""Agent工作流定义."""

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from app.core.content_generator import ContentGenerator
from app.core.nodes import BuildDocumentNode, GenerateContentNode, ParseTemplateNode
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.docx_handler import DocxHandler
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DocumentGenerator:
    """文档生成器（LangGraph工作流）."""

    def __init__(
        self,
        mcp_client: MCPClient,
        content_generator: ContentGenerator,
        docx_handler: DocxHandler,
    ):
        """初始化文档生成器.

        Args:
            mcp_client: MCP客户端
            content_generator: 内容生成器
            docx_handler: docx处理器
        """
        self.mcp_client = mcp_client
        self.content_generator = content_generator
        self.docx_handler = docx_handler
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """构建工作流.

        Returns:
            LangGraph工作流
        """
        workflow = StateGraph(AgentState)

        # 创建节点实例
        nodes = [
            ParseTemplateNode(),
            GenerateContentNode(self.content_generator),
            BuildDocumentNode(self.docx_handler),
        ]

        # 添加节点到工作流 - 只使用抽象基类接口
        for node in nodes:
            workflow.add_node(node.name, node.execute)

        # 设置入口
        workflow.set_entry_point("parse_template")

        # 添加边
        workflow.add_edge("parse_template", "generate_content")

        workflow.add_conditional_edges(
            "generate_content",
            self._should_continue,
            {
                "continue": "generate_content",
                "done": "build_document",
                "error": END,
            },
        )

        workflow.add_edge("build_document", END)

        return workflow.compile()

    def _should_continue(self, state: AgentState) -> str:
        """判断是否继续生成.

        Args:
            state: 当前工作流状态

        Returns:
            下一个节点的路由标识
        """
        if state.get("error"):
            return "error"
        if state["current_paragraph_index"] < state["total_paragraphs"]:
            return "continue"
        return "done"

    async def run(self, initial_state: AgentState) -> AgentState:
        """运行工作流.

        Args:
            initial_state: 初始状态

        Returns:
            最终状态
        """
        logger.info(
            "workflow_start",
            repo_id=initial_state["repo_id"],
            template_path=initial_state["template_path"],
        )

        try:
            result = await self.workflow.ainvoke(initial_state)

            logger.info(
                "workflow_complete",
                status=result["status"],
                total_paragraphs=result["total_paragraphs"],
            )

            return result

        except Exception as e:
            logger.error(
                "workflow_failed",
                error=str(e),
            )
            initial_state["error"] = str(e)
            initial_state["status"] = GenerationStatus.FAILED.value
            initial_state["message"] = f"工作流执行失败: {str(e)}"
            return initial_state
