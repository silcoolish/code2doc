"""大纲确认节点."""

import copy
import json
import uuid
from typing import Any, Dict, List, Optional

from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.content_generator import ContentGenerator
from app.domain.model import TemplateBlock
from app.domain.prompts import OUTLINE_CONFIRMATION_PROMPT
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class OutlineConfirmationNode(WorkflowNode):
    """大纲确认节点.

    将预处理后的 block 列表交给 LLM 进行大纲确认：
    1. 确认/优化标题内容
    2. 展开 isList=true 的模板 block 为具体列表项
    3. 返回确认后的完整 block 结构
    """

    def __init__(self, content_generator: ContentGenerator):
        self.agent = content_generator.agent

    @property
    def name(self) -> str:
        return "outline_confirmation"

    async def execute(self, state: AgentState) -> AgentState:
        """执行大纲确认.

        1. 预处理 block 列表
        2. 调用 LLM 确认大纲
        3. 解析响应并重建 blocks
        """
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        try:
            state["status"] = GenerationStatus.PARSING.value
            state["message"] = "正在确认文档大纲..."

            with log_timing("outline_confirmation", block_count=len(blocks)):
                outline_blocks = self._prepare_outline_blocks(blocks)
                task_message = self._build_task_message(
                    outline_blocks, state["repo_id"]
                )

                raw_content = await self.agent.generate_with_tools(
                    system_prompt=OUTLINE_CONFIRMATION_PROMPT,
                    task_message=task_message,
                    repo_id=state["repo_id"],
                    max_iterations=15,
                )

                new_blocks = self._parse_and_rebuild(raw_content, blocks)

                state["blocks"] = new_blocks
                state["total_blocks"] = len(new_blocks)
                state["message"] = f"大纲确认完成，共{len(new_blocks)}个内容块"

            logger.info(
                "outline_confirmation_success",
                original_count=len(blocks),
                new_count=len(new_blocks),
            )

        except Exception as e:
            logger.error(
                "outline_confirmation_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"大纲确认失败: {str(e)}"

        return state

    def _prepare_outline_blocks(
        self,
        blocks: List[TemplateBlock],
    ) -> List[Dict[str, Any]]:
        """预处理 block 列表用于大纲确认.

        Token 最小化策略：
        - 保留 id、heading_level
        - 去掉 block_type（heading_level 1-9 即标题，0 即非标题）
        - 去掉 template（静态/模板由是否含 prompt/isList 暗示）
        - 静态标题保留 content_text；模板标题去掉 content_text，保留 prompt
        - 非标题块仅保留 id + heading_level=0
        """
        sorted_blocks = sorted(blocks, key=lambda b: b.order_no)
        result = []
        for block in sorted_blocks:
            data: Dict[str, Any] = {"id": block.id}

            if block.heading_level and block.heading_level > 0:
                data["heading_level"] = block.heading_level
                if block.is_template:
                    if block.prompt:
                        data["prompt"] = block.prompt
                    data["isList"] = block.is_list
                    if block.example:
                        data["example"] = block.example
                else:
                    data["content_text"] = block.content_text
            else:
                data["heading_level"] = 99

            result.append(data)
        return result

    def _build_task_message(
        self,
        outline_blocks: List[Dict[str, Any]],
        repo_id: str,
    ) -> str:
        """构建任务消息."""
        blocks_json = json.dumps(outline_blocks, ensure_ascii=False, indent=2)

        return "\n".join([
            f"仓库ID: {repo_id}",
            "",
            "## 文档大纲内容块列表",
            "",
            "以下是需要你确认和优化的文档大纲结构。数组中的顺序即为文档中的顺序。",
            "",
            "```json",
            blocks_json,
            "```",
        ])

    def _parse_and_rebuild(
        self,
        raw_content: str,
        original_blocks: List[TemplateBlock],
    ) -> List[TemplateBlock]:
        """解析 LLM 响应并重建 block 列表.

        只根据 id/template_block_id 补全 block 属性，不新增节点。
        完全信任 LLM 返回的 block 顺序和结构。
        """
        json_content = self._extract_json_from_response(raw_content)
        if not json_content:
            logger.warning("outline_response_no_json_found")
            return original_blocks

        try:
            data = json.loads(json_content)
            if isinstance(data, list):
                returned_blocks = data
            else:
                returned_blocks = data.get("blocks", [])
        except json.JSONDecodeError as e:
            logger.error("outline_response_json_parse_failed", error=str(e))
            return original_blocks

        if not returned_blocks:
            logger.warning("outline_response_empty_blocks")
            return original_blocks

        original_map = {b.id: b for b in original_blocks}
        result: List[TemplateBlock] = []

        for ret in returned_blocks:
            # 兼容 id 和 template_block_id：若原始 block 是 isList=true，统一创建展开项
            ref_id = ret.get("id") or ret.get("template_block_id")
            if ref_id:
                original = original_map.get(ref_id)
                if original:
                    result.append(self._create_item_block(original, ret))
                else:
                    logger.warning("block_reference_unknown", id=ref_id)
                    result.append(self._create_new_block_from_response(ret))
            else:
                logger.warning("block_without_id_or_template_block_id")
                result.append(self._create_new_block_from_response(ret))

        for i, block in enumerate(result):
            block.order_no = i
            block.id = str(i)

        return result

    def _create_item_block(
        self,
        original: TemplateBlock,
        returned: Dict[str, Any],
    ) -> TemplateBlock:
        """基于原始 block 创建列表展开项."""
        new_block = copy.deepcopy(original)

        new_block.id = ""
        new_block.parent_block_id = original.parent_block_id

        if "content_text" in returned:
            new_block.content_text = returned["content_text"]

        # heading_level 强制保持与原始 block 一致
        new_block.heading_level = original.heading_level

        # 设置 attrs
        if new_block.block_type == "heading":
            new_block.attrs["templateType"] = "static"
            new_block.attrs.pop("prompt", None)
            new_block.attrs.pop("isList", None)
            new_block.attrs.pop("example", None)

        new_block.attrs["template_block_id"] = original.id

        return new_block

    def _create_new_block_from_response(
        self,
        returned: Dict[str, Any],
    ) -> TemplateBlock:
        """从 LLM 返回创建新 block（无对应原始 block 时）."""
        heading_level = returned.get("heading_level", 99)
        block_type = "heading" if (heading_level and heading_level > 0 and heading_level != 99) else "paragraph"

        content_text = returned.get("content_text", "")
        attrs: Dict[str, Any] = {}
        if "template_block_id" in returned:
            attrs["template_block_id"] = returned["template_block_id"]
        attrs["templateType"] = "static" if content_text else "template"

        return TemplateBlock(
            id=f"outline_new_{uuid.uuid4().hex[:8]}",
            parent_block_id=None,
            block_type=block_type,
            heading_level=heading_level,
            order_no=0,
            content_text=content_text,
            attrs=attrs,
        )

    def _extract_json_from_response(self, raw_content: str) -> Optional[str]:
        """从响应中提取 JSON.

        支持两种 LLM 输出格式：
        - 对象格式：{"blocks": [...]}
        - 数组格式：[{...}, ...]
        """
        raw_content = raw_content.strip()

        def _is_valid_blocks(candidate: str) -> bool:
            """判断是否包含有效的 block 数据."""
            return '"blocks"' in candidate or '"id"' in candidate or '"heading_level"' in candidate

        # 优先找 ```json 块
        if "```json" in raw_content:
            start = 0
            while True:
                start = raw_content.find("```json", start)
                if start == -1:
                    break
                start += 7
                end = raw_content.find("```", start)
                if end > start:
                    candidate = raw_content[start:end].strip()
                    if _is_valid_blocks(candidate):
                        return candidate
                start = end + 3 if end != -1 else len(raw_content)

        # 找 ``` 块
        if "```" in raw_content:
            last_candidate = None
            start = 0
            while True:
                start = raw_content.find("```", start)
                if start == -1:
                    break
                start += 3
                end = raw_content.find("```", start)
                if end > start:
                    candidate = raw_content[start:end].strip()
                    if _is_valid_blocks(candidate):
                        last_candidate = candidate
                start = end + 3 if end != -1 else len(raw_content)
            if last_candidate:
                return last_candidate

        # 找 JSON 数组（以 [ 开头）
        array_start = raw_content.find("[")
        if array_start >= 0:
            array_end = raw_content.rfind("]")
            if array_end > array_start:
                candidate = raw_content[array_start:array_end + 1]
                if _is_valid_blocks(candidate):
                    return candidate

        # 找 JSON 对象（以 { 开头）
        json_start = raw_content.find("{")
        while json_start >= 0:
            json_end = raw_content.rfind("}", json_start)
            if json_end > json_start:
                candidate = raw_content[json_start:json_end + 1]
                if _is_valid_blocks(candidate):
                    return candidate
            json_start = raw_content.find("{", json_start + 1)

        return None
