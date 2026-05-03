"""Agent工作流定义."""

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from app.domain.content_generator import ContentGenerator
from app.core.nodes import (
    CreateDocumentNode,
    GenerateBlocksNode,
    ListTemplateBlockNode,
    OutlineConfirmationNode,
    ProcessImageBlocksNode,
    SelectStrategyNode,
    StoreBlockListNode,
    WorkflowNode,
)
from app.core.state import AgentState, GenerationStatus
from app.infrastructure.mcp_client import MCPClient
from app.infrastructure.workspace import WorkspaceServiceAdapter
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DocumentGenerator:
    """文档生成器（LangGraph工作流）."""

    def __init__(
        self,
        mcp_client: MCPClient,
        content_generator: ContentGenerator,
        workspace_adapter: WorkspaceServiceAdapter = None,
    ):
        """初始化文档生成器.

        Args:
            mcp_client: MCP客户端
            content_generator: 内容生成器
            workspace_adapter: workspace服务适配器
        """
        self.mcp_client = mcp_client
        self.content_generator = content_generator
        self.workspace_adapter = workspace_adapter or WorkspaceServiceAdapter()
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """构建工作流.

        流程：获取模板 -> 大纲确认 -> 选择策略 -> 生成内容 -> 创建文档 -> 处理图片块 -> 存储文档块

        Returns:
            LangGraph工作流
        """
        workflow = StateGraph(AgentState)

        # 创建节点实例
        nodes = [
            ListTemplateBlockNode(self.workspace_adapter),
            OutlineConfirmationNode(self.content_generator),
            SelectStrategyNode(self.content_generator),
            GenerateBlocksNode(self.content_generator),
            CreateDocumentNode(self.workspace_adapter),
            ProcessImageBlocksNode(self.workspace_adapter),
            StoreBlockListNode(self.workspace_adapter),
        ]

        # 添加节点到工作流（包装后写入 current_node）
        for node in nodes:
            workflow.add_node(node.name, self._wrap_node(node))

        # 设置入口
        workflow.set_entry_point("list_template_block")

        # 线性流程
        workflow.add_edge("list_template_block", "outline_confirmation")
        workflow.add_edge("outline_confirmation", "select_strategy")
        workflow.add_edge("select_strategy", "generate_blocks")
        workflow.add_edge("generate_blocks", "create_document")
        workflow.add_edge("create_document", "process_image_blocks")
        workflow.add_edge("process_image_blocks", "store_block_list")
        workflow.add_edge("store_block_list", END)

        return workflow.compile()

    def _wrap_node(self, node: WorkflowNode):
        """包装节点执行函数，在执行前记录当前节点."""

        async def wrapped(state: AgentState) -> AgentState:
            state["current_node"] = node.name
            return await node.execute(state)

        return wrapped

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
            template_id=initial_state["template_id"],
        )

        try:
            result = await self.workflow.ainvoke(initial_state)

            logger.info(
                "workflow_complete",
                status=result["status"],
                total_blocks=result.get("total_blocks", 0),
                selected_strategy=result.get("selected_strategy"),
            )

            return result

        except Exception as e:
            logger.error(
                "workflow_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            initial_state["error"] = str(e)
            initial_state["status"] = GenerationStatus.FAILED.value
            initial_state["message"] = f"工作流执行失败: {str(e)}"
            return initial_state
