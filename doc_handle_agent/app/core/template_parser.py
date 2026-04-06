"""模板文档解析器."""

import json
import re
from typing import Dict, List, Optional, Tuple

from app.core.state import ContentBlock, ContentBlockType, ListTemplateChild
from app.infrastructure.docx_handler import DocxHandler
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TemplateParser:
    """模板文档解析器."""

    def __init__(self):
        """初始化模板解析器."""
        self.block_pattern = re.compile(r'\{\{(.*?)\}\}')
        self.docx_handler = DocxHandler()

    def parse(self, template_path: str) -> List[ContentBlock]:
        """解析模板文件，提取所有内容块.

        支持两种模板格式：
        1. 简单模板: {{"prompt":"..."}}
        2. 列表模板: {{"prompt":"...", "list":"true"}} + 子段落

        type 从段落样式自动判断（Heading开头为headline，其他为text）。
        子段落通过段落层级关系识别。

        Args:
            template_path: 模板文件路径

        Returns:
            内容块列表
        """
        logger.info(
            "parse_template_start",
            template_path=template_path,
        )

        try:
            # 提取所有段落信息
            paragraphs_info = self.docx_handler.extract_paragraphs_info(template_path)

            # 提取带位置信息的内容块
            blocks_with_info = self._extract_blocks_with_hierarchy(paragraphs_info)

            content_blocks = []
            for block_info in blocks_with_info:
                para_idx = block_info["index"]
                original_text = block_info["text"]
                block_content = block_info["template_content"]
                is_heading = block_info["is_heading"]
                child_paragraphs = block_info.get("child_paragraphs", [])

                # 验证是否为有效的模板格式
                validation_result = self._validate_template_block(
                    block_content, is_heading
                )
                if not validation_result["valid"]:
                    logger.info(
                        "skip_static_paragraph",
                        paragraph_index=para_idx,
                        reason=validation_result["reason"],
                    )
                    continue

                try:
                    block = self._parse_block_content(
                        block_id=str(para_idx),
                        block_content=block_content,
                        original_text=original_text,
                        is_heading=is_heading,
                        child_paragraphs=child_paragraphs,
                    )
                    content_blocks.append(block)
                except Exception as e:
                    logger.warning(
                        "parse_block_failed",
                        paragraph_index=para_idx,
                        block_content=block_content,
                        error=str(e),
                    )
                    continue

            logger.info(
                "parse_template_success",
                template_path=template_path,
                block_count=len(content_blocks),
            )

            return content_blocks

        except Exception as e:
            logger.error(
                "parse_template_failed",
                template_path=template_path,
                error=str(e),
            )
            raise

    def _extract_blocks_with_hierarchy(
        self,
        paragraphs_info: List,
    ) -> List[Dict]:
        """提取内容块及其层级关系.

        识别每个模板段落及其子段落（属于该列表模板的段落）。

        Args:
            paragraphs_info: 段落信息列表

        Returns:
            内容块信息列表，包含子段落信息
        """
        blocks = []

        i = 0
        while i < len(paragraphs_info):
            para_info = paragraphs_info[i]

            if not para_info.has_template:
                i += 1
                continue

            # 这是一个模板段落
            block_info = {
                "index": para_info.index,
                "text": para_info.text,
                "template_content": para_info.template_content,
                "is_heading": para_info.is_heading,
                "child_paragraphs": [],
            }

            # 检查是否是列表模板（Heading + 可能有子段落）
            if para_info.is_heading:
                # 尝试解析模板内容，检查 list 属性
                try:
                    data = json.loads(para_info.template_content)
                    is_list = str(data.get("list", "false")).lower() == "true"

                    if is_list:
                        # 收集子段落
                        child_paragraphs = self._collect_child_paragraphs(
                            paragraphs_info, i
                        )
                        block_info["child_paragraphs"] = child_paragraphs
                except json.JSONDecodeError:
                    pass

            blocks.append(block_info)
            i += 1

        return blocks

    def _collect_child_paragraphs(
        self,
        paragraphs_info: List,
        list_template_index: int,
    ) -> List[Dict]:
        """收集列表模板下的子段落.

        子段落是指位于列表模板之后、下一个同层级或更高层级模板之前的段落。

        Args:
            paragraphs_info: 段落信息列表
            list_template_index: 列表模板在列表中的索引

        Returns:
            子段落信息列表
        """
        child_paragraphs = []
        list_para_info = paragraphs_info[list_template_index]

        # 获取列表模板的标题级别
        list_level = self._get_heading_level(list_para_info.style_name)

        # 检查后续段落
        for j in range(list_template_index + 1, len(paragraphs_info)):
            para_info = paragraphs_info[j]

            # 如果遇到同层级或更高层级的标题，停止
            if para_info.is_heading:
                current_level = self._get_heading_level(para_info.style_name)
                if current_level <= list_level:
                    break

            # 如果遇到另一个列表模板（Heading + 有模板），停止
            if para_info.is_heading and para_info.has_template:
                break

            # 这是子段落
            child_info = {
                "index": para_info.index,
                "text": para_info.text,
                "has_template": para_info.has_template,
                "template_content": para_info.template_content,
                "is_heading": para_info.is_heading,
            }
            child_paragraphs.append(child_info)

        return child_paragraphs

    def _get_heading_level(self, style_name: str) -> int:
        """获取标题级别."""
        if not style_name.startswith("Heading"):
            return 99

        try:
            level = int(style_name.replace("Heading", "").strip())
            return level
        except ValueError:
            return 99

    def _parse_block_content(
        self,
        block_id: str,
        block_content: str,
        original_text: str,
        is_heading: bool,
        child_paragraphs: List[Dict],
    ) -> ContentBlock:
        """解析单个内容块.

        Args:
            block_id: 块ID
            block_content: 块内容（去掉外层大括号）
            original_text: 原始完整文本
            is_heading: 是否为标题段落
            child_paragraphs: 子段落列表

        Returns:
            解析后的内容块
        """
        data = json.loads(block_content)

        # 从段落样式判断类型
        block_type = ContentBlockType.HEADLINE if is_heading else ContentBlockType.TEXT

        # 解析列表选项
        is_list = str(data.get("list", "false")).lower() == "true"

        # 解析长度限制
        min_length = self._parse_int_field(data.get("min_length"))
        max_length = self._parse_int_field(data.get("max_length"))

        # 解析子模板（当 is_list=true 时）
        list_children = None
        if is_list and child_paragraphs:
            list_children = self._parse_list_children(
                child_paragraphs, block_id
            )

        return ContentBlock(
            id=block_id,
            type=block_type,
            prompt=data["prompt"],
            is_list=is_list,
            min_length=min_length,
            max_length=max_length,
            original_text=original_text,
            list_children=list_children,
        )

    def _parse_list_children(
        self,
        child_paragraphs: List[Dict],
        parent_id: str,
    ) -> Optional[List[ListTemplateChild]]:
        """解析列表模板的子段落.

        每个子段落可以是：
        - 纯静态：没有模板标记
        - 动态：有模板标记，需要生成内容

        Args:
            child_paragraphs: 子段落信息列表
            parent_id: 父列表ID

        Returns:
            子模板列表
        """
        list_children = []

        for i, child_info in enumerate(child_paragraphs):
            child_id = f"{parent_id}_child_{i}"

            # 提取静态前缀（模板前的文本）
            text = child_info["text"]
            static_prefix = self._extract_static_prefix(text)

            # 检查是否有模板
            template_block = None
            if child_info["has_template"] and child_info["template_content"]:
                template_block = self._parse_child_template_block(
                    child_info["template_content"],
                    child_id,
                    child_info["is_heading"],
                    parent_id,
                    i,
                )

            list_children.append(ListTemplateChild(
                id=child_id,
                static_prefix=static_prefix,
                template_block=template_block,
            ))

        return list_children if list_children else None

    def _extract_static_prefix(self, text: str) -> str:
        """提取静态前缀.

        从段落文本中提取模板前的静态文本（如 "1.1 标识"）。

        Args:
            text: 段落文本

        Returns:
            静态前缀
        """
        # 查找模板标记的位置
        match = self.block_pattern.search(text)
        if match:
            # 提取模板前的文本
            prefix = text[:match.start()].strip()
            return prefix
        return text.strip()

    def _parse_child_template_block(
        self,
        template_content: str,
        block_id: str,
        is_heading: bool,
        parent_list_id: str,
        list_index: int,
    ) -> Optional[ContentBlock]:
        """解析子段落中的模板.

        Args:
            template_content: 模板内容
            block_id: 块ID
            is_heading: 是否为标题
            parent_list_id: 所属列表ID
            list_index: 在列表中的索引

        Returns:
            内容块或None
        """
        try:
            data = json.loads(template_content)
        except json.JSONDecodeError:
            return None

        if "prompt" not in data:
            return None

        # 从段落样式判断类型
        block_type = ContentBlockType.HEADLINE if is_heading else ContentBlockType.TEXT

        # 子段落不支持 list 属性
        is_list = False

        # 解析长度限制
        min_length = self._parse_int_field(data.get("min_length"))
        max_length = self._parse_int_field(data.get("max_length"))

        return ContentBlock(
            id=block_id,
            type=block_type,
            prompt=data["prompt"],
            is_list=is_list,
            min_length=min_length,
            max_length=max_length,
            original_text=template_content,
            parent_list_id=parent_list_id,
            list_index=list_index,
        )

    def _validate_template_block(
        self,
        block_content: str,
        is_heading: bool,
    ) -> Dict[str, any]:
        """验证内容块是否为有效的模板格式."""
        try:
            data = json.loads(block_content)
        except json.JSONDecodeError:
            return {"valid": False, "reason": "not_valid_json"}

        if not isinstance(data, dict):
            return {"valid": False, "reason": "not_a_dict"}

        if "prompt" not in data:
            return {"valid": False, "reason": "missing_prompt_field"}

        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return {"valid": False, "reason": "empty_prompt"}

        # 验证 list 约束
        is_list = str(data.get("list", "false")).lower() == "true"
        if is_list and not is_heading:
            logger.warning(
                "list_only_allowed_for_heading_paragraph",
                is_heading=is_heading,
            )
            return {"valid": False, "reason": "list_only_allowed_for_heading_paragraph"}

        return {"valid": True, "reason": ""}

    def _parse_int_field(self, value: Optional[str]) -> Optional[int]:
        """解析整数字段."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def preview_blocks(self, template_path: str) -> List[Dict]:
        """预览模板中的内容块."""
        blocks = self.parse(template_path)
        return [block.to_dict() for block in blocks]

    def validate_template(self, template_path: str) -> Tuple[bool, Optional[str]]:
        """验证模板文件."""
        is_valid, error = self.docx_handler.validate_template(template_path)
        if not is_valid:
            return False, error

        try:
            blocks = self.parse(template_path)

            if not blocks:
                return True, "Warning: No content blocks found in template"

            for block in blocks:
                if not block.prompt.strip():
                    return False, f"Empty prompt in block {block.id}"

                if block.is_list and block.type != ContentBlockType.HEADLINE:
                    return False, f"Block {block.id}: list=true is only allowed for headline type"

            return True, None

        except Exception as e:
            return False, f"Failed to parse template: {str(e)}"


def create_example_template(output_path: str) -> str:
    """创建示例模板文件."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()

    # 添加标题
    title = doc.add_heading("系统设计文档", level=1)

    # 1. 系统概述 - 普通正文模板
    doc.add_heading("1. 系统概述", level=2)
    doc.add_paragraph('{{"prompt":"系统的整体功能概述，包括主要业务目标和技术目标"}}')

    # 2. 功能模块 - 列表模板 + 子段落
    doc.add_heading("2. 功能模块", level=2)
    doc.add_paragraph('{{"prompt":"系统的主要功能模块", "list":"true"}}')
    # 子段落：1.1 标识（静态）+ 模板（动态）
    doc.add_paragraph('    2.1 标识 {{"prompt":"随机10位英文字母序列"}}', style='List Paragraph')
    # 子段落：1.2 概要（静态）+ 模板（动态）
    doc.add_paragraph('    2.2 概要 {{"prompt":"功能模块的功能概要"}}', style='List Paragraph')

    # 3. 核心流程 - 普通正文模板
    doc.add_heading("3. 核心流程", level=2)
    doc.add_paragraph('{{"prompt":"系统的核心业务处理流程说明"}}')

    # 保存
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)

    logger.info(
        "example_template_created",
        output_path=output_path,
    )

    return output_path
