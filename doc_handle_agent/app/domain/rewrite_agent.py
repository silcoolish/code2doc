"""文档条目改写Agent."""

from pathlib import Path
from time import perf_counter
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.api.models.schemas import RewriteBlockRequest, RewriteBlockResponse
from app.domain.content_generator_agent import ContentGeneratorAgent
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "rewrite_block.md"

_DEFAULT_REWRITE_INSTRUCTION = (
    "请在不改变原始技术含义的前提下改写当前内容，"
    "优先提升准确性、可读性、结构完整度和上下文连贯性。"
)
_SELECTION_REWRITE_RULE = (
    "当前是选中文本改写。当前条目内容只作为上下文参考，"
    "只改写选中文本本身，最终只输出可替换选中文本的内容，不要输出整块内容。"
)
_SHORT_SELECTION_REWRITE_RULE = (
    "选中文本很短时，把它当成词语或短语处理。"
    "最终输出也必须是词语或短语，不要扩写成句子、段落或说明。"
)
_PRESET_LABELS = {
    "polish": "润色",
    "expand": "扩写",
    "shorten": "缩写",
    "professional": "更专业",
    "academic": "更学术",
    "formal": "更正式",
    "readable": "更易读",
}
_PRESET_INSTRUCTIONS = {
    "polish": "请润色当前内容，保留原意并提升表达准确度与可读性。",
    "expand": "请在不虚构信息的前提下扩写当前内容，补充必要细节、背景或衔接。",
    "shorten": "请缩写当前内容，保留核心信息并让表达更紧凑清晰。",
    "professional": "请将当前内容改写得更专业，保持术语准确、表达克制。",
    "academic": "请将当前内容改写得更学术，语言严谨、论述完整。",
    "formal": "请将当前内容改写得更正式，适合技术文档或汇报场景。",
    "readable": "请将当前内容改写得更易读，表达更顺、更容易理解，但不要损失关键信息。",
}


def _strip_markdown_code_blocks(content: str) -> str:
    """去除 markdown 代码块标记.

    Args:
        content: 原始文本

    Returns:
        去除代码块标记后的文本
    """
    content = content.strip()
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    content = "\n".join(lines)
    return content.strip()

class RewriteAgent:
    """文档条目改写Agent.

    只做当前块的纯文本改写，不连接 MCP，不执行写入操作。
    """

    def __init__(
        self,
        mcp_client: Optional[MCPClient] = None,
        llm_client: Any = None,
    ):
        """初始化改写Agent.

        Args:
            mcp_client: MCP客户端实例，仅用于复用通用生成器，不会在改写流程中连接
            llm_client: 可选的LLM客户端
        """
        self.agent = ContentGeneratorAgent(mcp_client or MCPClient(), llm_client)
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
                "最终只输出可直接应用到文档里的正文，不要输出JSON或解释说明。"
            )

    def _resolve_preset(self, preset: Optional[str]) -> Optional[str]:
        if not preset or not preset.strip():
            return None
        normalized_preset = preset.strip()
        return normalized_preset if normalized_preset in _PRESET_INSTRUCTIONS else None

    def _build_effective_prompt(self, request: RewriteBlockRequest) -> str:
        preset = self._resolve_preset(request.preset)
        base_instruction = _PRESET_INSTRUCTIONS.get(preset, _DEFAULT_REWRITE_INSTRUCTION)
        if request.target_type == "selection" and request.selected_text:
            base_instruction = f"{base_instruction}\n\n{_SELECTION_REWRITE_RULE}"
            if len(request.selected_text.strip()) <= 8:
                base_instruction = f"{base_instruction}\n\n{_SHORT_SELECTION_REWRITE_RULE}"
        extra_instruction = request.prompt.strip() if request.prompt else ""
        if not extra_instruction:
            return base_instruction
        return f"{base_instruction}\n\n补充要求:\n{extra_instruction}"

    def _resolve_apply_modes(self, request: RewriteBlockRequest) -> List[str]:
        if request.action == "continue":
            return ["insert-after"]
        if request.target_type == "selection" and request.selected_text:
            return ["replace-selection", "replace-block", "insert-after"]
        return ["replace-block", "insert-after"]

    def _build_task_message(
        self, request: RewriteBlockRequest, effective_prompt: str
    ) -> str:
        """构建改写任务消息."""
        parts = [
            f"仓库ID: {request.repo_id}",
            f"目标键: {request.target_key}",
            f"目标类型: {request.target_type}",
            f"条目ID: {request.block_id}",
        ]

        is_selection_rewrite = request.target_type == "selection" and bool(request.selected_text)
        if request.block_text:
            block_label = "当前条目上下文" if is_selection_rewrite else "当前条目内容"
            parts.append(f"{block_label}:\n{request.block_text}")

        if request.selected_text:
            selected_label = "需要改写的选中文本" if is_selection_rewrite else "选中文本"
            parts.append(f"{selected_label}:\n{request.selected_text}")
            if request.selection_start is not None and request.selection_end is not None:
                parts.append(f"选区范围: {request.selection_start}-{request.selection_end}")

        if is_selection_rewrite:
            parts.append("输出范围: 只输出选中文本改写后的替换内容")
            if len(request.selected_text.strip()) <= 8:
                parts.append("短选区限制: 只输出一个词语或短语，不要输出完整句子")

        preset = self._resolve_preset(request.preset)
        if preset:
            parts.append(f"快捷改写模式: {_PRESET_LABELS[preset]}")

        if request.prompt and request.prompt.strip():
            parts.append(f"补充要求: {request.prompt.strip()}")

        parts.append(f"执行要求:\n{effective_prompt}")

        if request.action:
            parts.append(f"改写动作: {request.action}")

        if request.deep_think:
            parts.append("深度思考: 是")

        if request.document_id:
            parts.append(f"文档ID: {request.document_id}")

        return "\n\n".join(parts)

    async def _generate_text_only(self, task_message: str) -> str:
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(content=task_message),
        ]
        started_at = perf_counter()
        response = await self.agent.llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        logger.info(
            "rewrite_llm_complete",
            duration_ms=round((perf_counter() - started_at) * 1000),
            result_length=len(content),
        )
        return content

    def _parse_response(
        self, raw_content: str, request: RewriteBlockRequest
    ) -> RewriteBlockResponse:
        """把模型正文放进接口响应."""
        apply_modes = self._resolve_apply_modes(request)
        content = _strip_markdown_code_blocks(raw_content)

        return RewriteBlockResponse(
            result_text=content,
            result_markdown=content,
            candidates=[],
            apply_modes=apply_modes,
        )

    async def rewrite(self, request: RewriteBlockRequest) -> RewriteBlockResponse:
        """执行改写."""
        started_at = perf_counter()
        effective_prompt = self._build_effective_prompt(request)
        preset = self._resolve_preset(request.preset)
        custom_prompt = request.prompt.strip() if request.prompt else ""

        logger.info(
            "rewrite_start",
            repo_id=request.repo_id,
            block_id=request.block_id,
            action=request.action,
            preset=preset,
            has_custom_prompt=bool(custom_prompt),
            deep_think=request.deep_think,
        )

        task_message = self._build_task_message(request, effective_prompt)
        raw_content = await self._generate_text_only(task_message)
        response = self._parse_response(raw_content, request)

        logger.info(
            "rewrite_complete",
            repo_id=request.repo_id,
            block_id=request.block_id,
            preset=preset,
            result_length=len(response.result_text),
            candidate_count=len(response.candidates),
            duration_ms=round((perf_counter() - started_at) * 1000),
        )
        return response
