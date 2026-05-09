"""文档条目改写Agent."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from app.api.models.schemas import RewriteBlockRequest, RewriteBlockResponse
from app.domain.content_generator_agent import ContentGeneratorAgent
from app.infrastructure.mcp_client import MCPClient
from app.infrastructure.workspace.workspace_adapter import WorkspaceServiceAdapter
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "rewrite_block.md"


def _strip_markdown_code_blocks(content: str) -> str:
    """去除 markdown 代码块标记.

    Args:
        content: 原始文本

    Returns:
        去除代码块标记后的文本
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()

_INTENT_CLASSIFICATION_PROMPT = (
    "你是一个请求意图分类器。请根据用户的改写提示词，"
    "判断该请求是否需要查询代码仓库信息才能准确完成。\n\n"
    "分类规则：\n"
    '- "text_only": 纯文本层面的改写，不需要代码知识。'
    "例如：简化表达、翻译、润色、调整语气、扩写、缩写、格式调整、"
    "修正错别字、语法优化、改写为更正式/口语化表达等。\n"
    '- "code_aware": 需要基于代码仓库信息才能准确改写。'
    "例如：提到具体类名、方法名、接口名、模块名；"
    "要求根据实现补充文档；涉及技术细节与代码逻辑对齐；"
    "要求补充参数说明、返回值说明、字段说明等。\n\n"
    "只输出一个合法的JSON对象，不要包含 markdown 代码块标记，格式如下：\n"
    '{{"intent": "text_only|code_aware", "reason": "一句话解释原因"}}'
    "\n\n"
    "用户提示词：{prompt}"
)


class RewriteAgent:
    """文档条目改写Agent.

    基于 ContentGeneratorAgent 的工具调用能力，同时支持 workspace 查询工具和知识底座 MCP tools。
    只返回改写建议文本，不执行写入操作。
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        workspace_adapter: WorkspaceServiceAdapter,
        llm_client: Any = None,
    ):
        """初始化改写Agent.

        Args:
            mcp_client: MCP客户端实例
            workspace_adapter: Workspace服务适配器
            llm_client: 可选的LLM客户端
        """
        self.agent = ContentGeneratorAgent(mcp_client, llm_client)
        self.workspace = workspace_adapter
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """加载改写专用系统提示词.

        Returns:
            系统提示词文本
        """
        try:
            return _PROMPT_PATH.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("rewrite_system_prompt_load_failed", path=str(_PROMPT_PATH), error=str(e))
            return (
                "你是技术文档改写助手。根据用户提示词改写或续写文档条目，"
                "输出JSON格式：{\"result_text\": \"...\", \"candidates\": [...], \"summary\": \"...\"}"
            )

    async def _classify_intent(self, prompt: str) -> Tuple[str, str]:
        """使用LLM判断改写意图.

        区分纯文本改写(text_only)和需要代码知识的改写(code_aware)。

        Args:
            prompt: 用户改写提示词

        Returns:
            (intent, reason) 元组
        """
        messages = [
            SystemMessage(content="你是一名精准的意图分类器，只输出JSON格式结果。"),
            HumanMessage(content=_INTENT_CLASSIFICATION_PROMPT.format(prompt=prompt)),
        ]

        try:
            response = await self.agent.llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)

            content = _strip_markdown_code_blocks(content)

            data = json.loads(content)
            intent = data.get("intent", "code_aware")
            reason = data.get("reason", "默认需要代码知识")

            if intent not in ("text_only", "code_aware"):
                intent = "code_aware"

            return intent, reason
        except Exception as e:
            logger.warning("intent_classification_failed", error=str(e), prompt=prompt)
            # 失败时保守起见，启用代码知识
            return "code_aware", f"意图识别失败，默认启用代码知识: {str(e)}"

    def _build_workspace_tools(self) -> List[Dict[str, Any]]:
        """构建 workspace 查询工具的 function 定义.

        Returns:
            OpenAI function 格式的工具列表
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_block",
                    "description": "获取单个文档条目的完整信息，包括内容、样式、属性等",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "document_id": {
                                "type": "string",
                                "description": "文档ID",
                            },
                            "block_id": {
                                "type": "string",
                                "description": "条目ID",
                            },
                        },
                        "required": ["document_id", "block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_document_blocks",
                    "description": "列取指定文档下的所有条目，用于了解文档整体结构和上下文",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "document_id": {
                                "type": "string",
                                "description": "文档ID",
                            },
                        },
                        "required": ["document_id"],
                    },
                },
            },
        ]

    async def _handle_workspace_tool(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> str:
        """处理 workspace 工具调用.

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具调用结果字符串
        """
        try:
            if tool_name == "get_block":
                document_id = tool_args.get("document_id")
                block_id = tool_args.get("block_id")
                if not document_id or not block_id:
                    return "参数错误: document_id 和 block_id 不能为空"
                result = await self.workspace.get_block(document_id, block_id)
                return json.dumps(result, ensure_ascii=False)

            elif tool_name == "get_document_blocks":
                document_id = tool_args.get("document_id")
                if not document_id:
                    return "参数错误: document_id 不能为空"
                result = await self.workspace.get_document_blocks(document_id)
                return json.dumps(result, ensure_ascii=False)

            else:
                return f"未知工具: {tool_name}"
        except Exception as e:
            logger.error(
                "workspace_tool_failed",
                tool_name=tool_name,
                error=str(e),
            )
            return f"工具调用失败: {str(e)}"

    def _build_task_message(self, request: RewriteBlockRequest) -> str:
        """构建改写任务消息.

        Args:
            request: 改写请求

        Returns:
            任务消息文本
        """
        parts = [
            f"仓库ID: {request.repo_id}",
            f"目标键: {request.target_key}",
            f"目标类型: {request.target_type}",
            f"条目ID: {request.block_id}",
        ]

        if request.block_text:
            parts.append(f"当前条目内容:\n{request.block_text}")

        if request.selected_text:
            parts.append(f"选中文本: {request.selected_text}")
            if request.selection_start is not None and request.selection_end is not None:
                parts.append(f"选区范围: {request.selection_start}-{request.selection_end}")

        parts.append(f"改写提示词: {request.prompt}")

        if request.action:
            parts.append(f"改写动作: {request.action}")

        if request.deep_think:
            parts.append("深度思考: 是")

        if request.document_id:
            parts.append(
                f"文档ID: {request.document_id}\n"
                "如需了解文档整体结构，可调用 get_document_blocks 工具。\n"
                "如需获取目标条目完整信息，可调用 get_block 工具。"
            )

        return "\n\n".join(parts)

    def _parse_response(
        self, raw_content: str, action: Optional[str] = None
    ) -> RewriteBlockResponse:
        """解析 LLM 输出为结构化响应.

        Args:
            raw_content: LLM 原始输出
            action: 改写动作，用于确定 apply_modes

        Returns:
            RewriteBlockResponse
        """
        # 确定应用方式
        if action == "continue":
            apply_modes = ["insert", "append"]
        else:
            apply_modes = ["replace"]

        # 尝试提取 JSON（LLM 可能包裹在 markdown 代码块中）
        content = _strip_markdown_code_blocks(raw_content)

        try:
            data = json.loads(content)
            return RewriteBlockResponse(
                result_text=data.get("result_text", ""),
                result_markdown=data.get("result_text", ""),
                candidates=data.get("candidates", []),
                apply_modes=apply_modes,
                summary=data.get("summary"),
            )
        except json.JSONDecodeError:
            logger.warning("rewrite_response_parse_failed", raw_content=raw_content[:200])
            # 回退：将整个输出作为 result_text
            return RewriteBlockResponse(
                result_text=raw_content,
                result_markdown=raw_content,
                candidates=[],
                apply_modes=apply_modes,
            )

    async def rewrite(self, request: RewriteBlockRequest) -> RewriteBlockResponse:
        """执行改写.

        流程:
        1. 使用LLM进行意图识别，判断是否需要代码知识
        2. 纯文本改写(text_only)时排除所有MCP知识底座工具
        3. 代码感知改写(code_aware)时保留全部工具

        Args:
            request: 改写请求

        Returns:
            改写响应
        """
        if not request.prompt or not request.prompt.strip():
            raise ValueError("prompt cannot be empty")

        logger.info(
            "rewrite_start",
            repo_id=request.repo_id,
            block_id=request.block_id,
            action=request.action,
            deep_think=request.deep_think,
        )

        # 1. 意图识别
        intent, reason = await self._classify_intent(request.prompt)
        logger.info("rewrite_intent_classified", intent=intent, reason=reason)

        # 2. 根据意图构建工具集
        extra_tools = self._build_workspace_tools()
        excluded_tools: Optional[List[str]] = None

        if intent == "text_only":
            try:
                mcp_tools = self.agent.mcp_client.get_available_tools()
                excluded_tools = [
                    t.get("function", {}).get("name")
                    for t in mcp_tools
                    if t.get("function")
                ]
                logger.info(
                    "rewrite_mcp_tools_excluded",
                    excluded_count=len(excluded_tools),
                )
            except Exception as e:
                logger.warning("rewrite_exclude_tools_failed", error=str(e))

        task_message = self._build_task_message(request)

        raw_content = await self.agent.generate_with_tools(
            system_prompt=self._system_prompt,
            task_message=task_message,
            repo_id=request.repo_id,
            task_name="rewrite",
            max_iterations=10,
            excluded_tools=excluded_tools,
            extra_tools=extra_tools,
            custom_tool_handler=self._handle_workspace_tool,
        )

        response = self._parse_response(raw_content, request.action)

        logger.info(
            "rewrite_complete",
            repo_id=request.repo_id,
            block_id=request.block_id,
            intent=intent,
            result_length=len(response.result_text),
            candidate_count=len(response.candidates),
        )
        return response
