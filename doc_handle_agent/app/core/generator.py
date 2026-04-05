"""Agent工作流定义."""

import asyncio
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from app.core.content_generator import ContentGenerator
from app.core.state import AgentState, ContentBlock, GenerationStatus
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
        from app.core.template_parser import TemplateParser

        workflow = StateGraph(AgentState)

        # 定义节点
        async def parse_template(state: AgentState) -> AgentState:
            """解析模板."""
            logger.info(
                "workflow_node",
                node="parse_template",
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

        async def generate_content(state: AgentState) -> AgentState:
            """生成内容."""
            idx = state["current_block_index"]
            total = state["total_blocks"]

            if idx >= total:
                return state

            block = state["content_blocks"][idx]

            logger.info(
                "workflow_node",
                node="generate_content",
                current=idx + 1,
                total=total,
                block_id=block.id,
            )

            try:
                # 更新状态
                state["status"] = GenerationStatus.GENERATING.value
                state["message"] = f"正在生成第{idx + 1}/{total}个内容块: {block.prompt[:30]}..."

                # 生成内容
                content = await self.content_generator.generate(
                    block=block,
                    repo_id=state["repo_id"],
                )

                # 保存结果
                state["generated_contents"][block.id] = content
                state["current_block_index"] = idx + 1

                logger.info(
                    "generate_content_success",
                    block_id=block.id,
                    content_length=len(content),
                )

            except Exception as e:
                logger.error(
                    "generate_content_failed",
                    block_id=block.id,
                    error=str(e),
                )
                # 记录错误但继续处理
                state["generated_contents"][block.id] = f"[生成失败: {str(e)}]"
                state["current_block_index"] = idx + 1

            return state

        async def build_document(state: AgentState) -> AgentState:
            """构建文档."""
            logger.info(
                "workflow_node",
                node="build_document",
                output_path=state["output_path"],
            )

            try:
                state["status"] = GenerationStatus.BUILDING.value
                state["message"] = "正在构建最终文档..."

                # 替换内容块
                output_path = self.docx_handler.replace_blocks(
                    template_path=state["template_path"],
                    output_path=state["output_path"],
                    block_contents=state["generated_contents"],
                )

                state["status"] = GenerationStatus.COMPLETED.value
                state["message"] = f"文档生成完成: {output_path}"

                logger.info(
                    "build_document_success",
                    output_path=output_path,
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

        # 条件边
        def should_continue(state: AgentState) -> str:
            """判断是否继续生成."""
            if state.get("error"):
                return "error"
            if state["current_block_index"] < state["total_blocks"]:
                return "continue"
            return "done"

        # 添加节点
        workflow.add_node("parse_template", parse_template)
        workflow.add_node("generate_content", generate_content)
        workflow.add_node("build_document", build_document)

        # 设置入口
        workflow.set_entry_point("parse_template")

        # 添加边
        workflow.add_edge("parse_template", "generate_content")

        workflow.add_conditional_edges(
            "generate_content",
            should_continue,
            {
                "continue": "generate_content",
                "done": "build_document",
                "error": END,
            },
        )

        workflow.add_edge("build_document", END)

        return workflow.compile()

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
                total_blocks=result["total_blocks"],
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
