"""draw.io 图优化 Agent."""

import json
import re
from time import perf_counter
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.api.models.schemas import OptimizeDrawioDiagramRequest
from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.drawio_xml_tools import (
    apply_diagram_operations,
    extract_root_cells_xml,
    is_mxcell_xml_complete,
    validate_drawio_xml,
    wrap_with_mxfile,
)
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_XML_OPTIMIZE_SYSTEM_PROMPT = """你是 draw.io XML 图表编辑助手。你需要参照 next-ai-draw-io 的工具调用方式，基于当前画布 XML 修改图表。

你只能返回一个 JSON 对象，用它表达一次工具调用，不要输出 Markdown、解释文字或代码围栏。

可用工具:
1. display_diagram: 创建新图或大幅重构图。参数为 {"tool":"display_diagram","xml":"<mxCell .../>..."}
2. edit_diagram: 小范围修改现有图。参数为 {"tool":"edit_diagram","operations":[...]}

edit_diagram operations:
- update: {"operation":"update","cell_id":"3","new_xml":"<mxCell id=\\"3\\" ...>...</mxCell>"}
- add: {"operation":"add","cell_id":"new1","new_xml":"<mxCell id=\\"new1\\" ...>...</mxCell>"}
- delete: {"operation":"delete","cell_id":"5"}

关键规则:
1. 当前 draw.io XML 是唯一事实源，优先保留用户已经编辑过的节点、ID、布局和连线
2. 小改动优先使用 edit_diagram，不要整图重画
3. 只有用户要求大幅重构、当前 XML 不可用或需要整体换版式时才使用 display_diagram
4. display_diagram 的 xml 只能包含 mxCell 片段，不要包含 mxfile、mxGraphModel、root、id=0、id=1
5. update/add 的 new_xml 必须是完整 mxCell，id 必须等于 cell_id
6. 所有新增 id 必须唯一，不得复用当前 XML 中已有 id
7. edge 必须显式 source/target，source/target 必须引用已存在或同批新增的 cell id
8. 连线使用 orthogonalEdgeStyle，并尽量设置 exitX、exitY、entryX、entryY，避免穿过节点
9. 容器节点不要覆盖子节点文字；子节点 parent 可指向容器，但几何坐标必须相对容器且留出标题区
10. XML 属性中的 <、>、&、" 必须转义为 &lt;、&gt;、&amp;、&quot;
"""


class DrawioDiagramOptimizeAgent:
    """基于当前 draw.io XML 执行 AI 优化的轻量 Agent."""

    def __init__(
        self,
        mcp_client: Optional[MCPClient] = None,
        llm_client: Any = None,
    ):
        """初始化 draw.io 图优化 Agent."""
        self.agent = ContentGeneratorAgent(mcp_client or MCPClient(), llm_client)

    async def optimize_xml(self, request: OptimizeDrawioDiagramRequest) -> str:
        """按 next-ai-draw-io 的工具协议优化当前 draw.io XML."""
        current_xml = (request.current_xml or "").strip()
        if not current_xml:
            raise ValueError("current_xml is required for draw.io XML optimization")

        started_at = perf_counter()
        task_message = self._build_task_message(request, error_feedback=None)
        last_error = ""
        for attempt in range(2):
            messages = [
                SystemMessage(content=_XML_OPTIMIZE_SYSTEM_PROMPT),
                HumanMessage(content=task_message),
            ]
            response = await self.agent.llm.ainvoke(messages)
            raw_content = response.content if hasattr(response, "content") else str(response)
            try:
                tool_call = self._normalize_tool_call(self._parse_json_object(raw_content))
                optimized_xml, error = self._execute_tool_call(current_xml, tool_call)
                if not error:
                    logger.info(
                        "drawio_xml_optimize_complete",
                        repo_id=request.repo_id,
                        block_id=request.block_id,
                        duration_ms=round((perf_counter() - started_at) * 1000),
                        attempt=attempt + 1,
                        tool=self._resolve_tool_name(tool_call),
                    )
                    return optimized_xml
                last_error = error
            except Exception as exc:
                last_error = str(exc)

            # 和开源项目一致，把结构化错误反馈给模型，让它基于同一份当前 XML 重试
            task_message = self._build_task_message(request, error_feedback=last_error)

        raise ValueError(f"draw.io XML 优化失败: {last_error or '模型未返回可应用的工具调用'}")

    def _build_task_message(
        self,
        request: OptimizeDrawioDiagramRequest,
        error_feedback: Optional[str],
    ) -> str:
        """构建 draw.io XML 优化任务消息."""
        current_cells = extract_root_cells_xml(request.current_xml or "")
        parts = [
            f"仓库ID: {request.repo_id}",
            f"文档ID: {request.document_id}",
            f"图示块ID: {request.block_id}",
            f"标题: {request.title or 'draw.io 图示'}",
            "Current diagram XML（root 下 mxCell，按这些 id 精准编辑）:",
            current_cells,
        ]
        if request.prompt and request.prompt.strip():
            parts.append(f"用户本次调整要求:\n{request.prompt.strip()}")
        else:
            parts.append("用户本次调整要求:\n在保留当前图主体和用户编辑内容的前提下，优化图示表达、布局和可读性")

        surrounding_context = self._format_surrounding_blocks(request.surrounding_blocks)
        if surrounding_context:
            parts.append(f"邻近文档上下文:\n{surrounding_context}")
        if error_feedback:
            parts.append(
                "上一轮工具调用失败，必须修正后重新返回一个工具调用 JSON:\n"
                f"{error_feedback}"
            )
        return "\n\n".join(parts)

    def _execute_tool_call(self, current_xml: str, tool_call: Dict[str, Any]) -> tuple[str, str]:
        """执行模型返回的 display_diagram 或 edit_diagram 工具调用."""
        tool = self._resolve_tool_name(tool_call)
        if tool == "display_diagram":
            fragment = str(tool_call.get("xml") or tool_call.get("arguments", {}).get("xml") or "").strip()
            if not is_mxcell_xml_complete(fragment):
                return "", "display_diagram xml is incomplete or empty"
            next_xml = wrap_with_mxfile(fragment)
            validation_error = validate_drawio_xml(next_xml)
            return (next_xml, "") if not validation_error else ("", validation_error)

        if tool == "edit_diagram":
            operations = tool_call.get("operations") or tool_call.get("edits")
            if operations is None and isinstance(tool_call.get("arguments"), dict):
                operations = tool_call["arguments"].get("operations") or tool_call["arguments"].get("edits")
            if not isinstance(operations, list) or not operations:
                return "", "edit_diagram operations must be a non-empty array"
            result = apply_diagram_operations(current_xml, operations)
            if result.errors:
                error_lines = [
                    f'- {error.type} on cell_id="{error.cell_id}": {error.message}'
                    for error in result.errors
                ]
                return "", "Some operations failed:\n" + "\n".join(error_lines)
            return result.result, ""

        return "", "tool must be display_diagram or edit_diagram"

    @staticmethod
    def _resolve_tool_name(tool_call: Dict[str, Any]) -> str:
        """兼容不同模型可能返回的工具名称字段."""
        tool = tool_call.get("tool") or tool_call.get("toolName") or tool_call.get("name")
        if not tool and isinstance(tool_call.get("function"), dict):
            tool = tool_call["function"].get("name")
        return str(tool or "").strip()

    @classmethod
    def _normalize_tool_call(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """把模型返回的工具调用包装规整成后端可执行的参数对象."""
        tool_call = payload
        if isinstance(payload.get("tool_calls"), list) and payload["tool_calls"]:
            first_call = payload["tool_calls"][0]
            if isinstance(first_call, dict):
                tool_call = first_call

        function = tool_call.get("function")
        if isinstance(function, dict):
            arguments = function.get("arguments")
            parsed_arguments = cls._parse_arguments(arguments)
            return {
                "tool": function.get("name") or tool_call.get("name") or tool_call.get("tool"),
                **parsed_arguments,
            }

        arguments = tool_call.get("arguments")
        if isinstance(arguments, str):
            parsed_arguments = cls._parse_arguments(arguments)
            return {**tool_call, "arguments": parsed_arguments}
        return tool_call

    @staticmethod
    def _parse_arguments(arguments: Any) -> Dict[str, Any]:
        """解析工具调用 arguments 字段."""
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str) and arguments.strip():
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _format_surrounding_blocks(blocks: List[Dict[str, Any]]) -> str:
        """压缩邻近块上下文，避免把整份文档塞进提示词."""
        lines: List[str] = []
        for block in blocks[:12]:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("id") or "").strip()
            block_type = str(block.get("type") or block.get("kind") or block.get("blockType") or "").strip()
            text = str(block.get("plainText") or block.get("contentText") or block.get("markdown") or "").strip()
            if not text:
                continue
            compact_text = re.sub(r"\s+", " ", text)[:500]
            lines.append(f"- {block_type or 'block'} {block_id}: {compact_text}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json_object(raw_content: str) -> Dict[str, Any]:
        """从模型响应中提取 JSON 对象."""
        content = (raw_content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("模型未返回可解析的 JSON 对象")
            parsed = json.loads(content[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("模型返回内容不是 JSON 对象")
        return parsed
