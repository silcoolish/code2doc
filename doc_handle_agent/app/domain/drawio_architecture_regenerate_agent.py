"""draw.io 架构图重生成Agent."""

import json
import re
from time import perf_counter
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.api.models.schemas import RegenerateDrawioArchitectureRequest
from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.drawio_architecture import normalize_architecture_spec
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """你是技术文档架构图生成助手。你的任务是根据项目上下文和用户要求，输出 draw.io 架构图 JSON 结构。

输出规则：
1. 只输出一个 JSON 对象，不要输出 Markdown、Mermaid、解释文字或代码围栏
2. JSON 必须包含 title、visual、layers、connections、pipeline
3. visual.layout 可选 layered、domain_map、pipeline，应根据上下文选择，不要固定一种结构
4. visual.theme 可选 classic、cool、warm、contrast、forest、sunset、vivid，应结合项目领域选择
5. visual.accent 和 layer.color 只能使用 blue、green、orange、teal、purple、slate、indigo、emerald、amber、sky、rose、violet、red、cyan、lime、yellow、pink、zinc
6. layers 应覆盖入口/交互层、业务编排层、核心功能模块层、接口/资源层、基础依赖层，但可以根据项目结构合并或改成领域分组
7. connections.from/to 必须引用 layer 或 item 的 id/name
8. 每个 item 名称要短，description 放职责说明
9. 避免照抄旧结构、旧配色或示例配色；用户要求不明确时，也要给出版式和配色上的合理变化
"""


class DrawioArchitectureRegenerateAgent:
    """重生成 draw.io 架构图 JSON 的轻量 Agent."""

    def __init__(
        self,
        mcp_client: Optional[MCPClient] = None,
        llm_client: Any = None,
    ):
        """初始化架构图重生成 Agent.

        Args:
            mcp_client: MCP 客户端占位，保持和通用生成器构造兼容
            llm_client: 可选的 LLM 客户端
        """
        self.agent = ContentGeneratorAgent(mcp_client or MCPClient(), llm_client)

    async def regenerate(self, request: RegenerateDrawioArchitectureRequest) -> Dict[str, Any]:
        """根据当前块上下文生成新的架构图 JSON."""
        started_at = perf_counter()
        task_message = self._build_task_message(request)
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=task_message),
        ]
        response = await self.agent.llm.ainvoke(messages)
        raw_content = response.content if hasattr(response, "content") else str(response)
        parsed = self._parse_json_object(raw_content)
        spec = normalize_architecture_spec(parsed, fallback_title=request.title or "项目总体架构图")
        logger.info(
            "drawio_architecture_regenerate_complete",
            repo_id=request.repo_id,
            block_id=request.block_id,
            duration_ms=round((perf_counter() - started_at) * 1000),
            layer_count=len(spec.get("layers", [])),
            layout=spec.get("visual", {}).get("layout"),
            theme=spec.get("visual", {}).get("theme"),
        )
        return spec

    def _build_task_message(self, request: RegenerateDrawioArchitectureRequest) -> str:
        """构建模型任务消息."""
        parts = [
            f"仓库ID: {request.repo_id}",
            f"文档ID: {request.document_id}",
            f"架构图块ID: {request.block_id}",
            f"标题: {request.title or '项目总体架构图'}",
        ]
        if request.block_text:
            parts.append(f"当前块展示文本:\n{request.block_text}")
        if request.prompt and request.prompt.strip():
            parts.append(f"用户本次调整要求:\n{request.prompt.strip()}")
        else:
            parts.append("用户本次调整要求:\n请重新组织架构图结构和配色，保留项目技术含义")

        current_spec = self._safe_json_dump(request.current_spec or request.attrs.get("architectureSpec"))
        if current_spec:
            parts.append(f"当前架构图 JSON，可参考但不要机械照抄:\n{current_spec}")

        surrounding_context = self._format_surrounding_blocks(request.surrounding_blocks)
        if surrounding_context:
            parts.append(f"邻近文档上下文:\n{surrounding_context}")

        parts.append(
            "输出要求:\n"
            "只输出 JSON 对象；需要让结构、layout、theme、accent、layer.color 和 connections 更贴合上下文；"
            "不要生成固定模板化的 L1/L2 两层示例"
        )
        return "\n\n".join(parts)

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
    def _safe_json_dump(value: Any) -> str:
        """把当前规格安全序列化进提示词."""
        if not value:
            return ""
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)[:12000]
        except (TypeError, ValueError):
            return str(value)[:12000]

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
