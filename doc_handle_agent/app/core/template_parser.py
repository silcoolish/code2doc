"""模板文档解析器."""

import json
import re
from typing import Dict, List, Optional, Tuple

from app.core.state import ContentBlock, ContentBlockType
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

        Args:
            template_path: 模板文件路径

        Returns:
            内容块列表

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 解析失败
        """
        logger.info(
            "parse_template_start",
            template_path=template_path,
        )

        try:
            # 提取带位置信息的内容块
            blocks_with_positions = self.docx_handler.extract_blocks_with_positions(
                template_path
            )

            content_blocks = []
            for para_idx, original_text, block_content in blocks_with_positions:
                try:
                    block = self._parse_block_content(
                        block_id=str(para_idx),
                        block_content=block_content,
                        original_text=original_text,
                    )
                    content_blocks.append(block)
                except Exception as e:
                    logger.warning(
                        "parse_block_failed",
                        paragraph_index=para_idx,
                        block_content=block_content,
                        error=str(e),
                    )
                    # 继续解析其他块
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

    def _parse_block_content(
        self,
        block_id: str,
        block_content: str,
        original_text: str,
    ) -> ContentBlock:
        """解析单个内容块.

        Args:
            block_id: 块ID
            block_content: 块内容（去掉外层大括号）
            original_text: 原始完整文本

        Returns:
            解析后的内容块

        Raises:
            ValueError: 解析失败
        """
        try:
            # 尝试作为JSON解析
            data = json.loads(block_content)
        except json.JSONDecodeError as e:
            logger.error(
                "json_decode_failed",
                block_content=block_content,
                error=str(e),
            )
            raise ValueError(f"Invalid JSON format in block: {block_content}")

        # 验证必填字段
        if "type" not in data:
            raise ValueError("Missing 'type' field in block")
        if "prompt" not in data:
            raise ValueError("Missing 'prompt' field in block")

        # 解析类型
        block_type_str = data.get("type", "text").lower()
        try:
            block_type = ContentBlockType(block_type_str)
        except ValueError:
            logger.warning(
                "unknown_block_type",
                type=block_type_str,
                defaulting_to="text",
            )
            block_type = ContentBlockType.TEXT

        # 解析列表选项
        is_list = str(data.get("list", "false")).lower() == "true"

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
            original_text=original_text,
        )

    def _parse_int_field(self, value: Optional[str]) -> Optional[int]:
        """解析整数字段.

        Args:
            value: 字符串值

        Returns:
            整数或None
        """
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def preview_blocks(self, template_path: str) -> List[Dict]:
        """预览模板中的内容块（不解析）.

        Args:
            template_path: 模板文件路径

        Returns:
            内容块预览列表
        """
        blocks = self.parse(template_path)
        return [block.to_dict() for block in blocks]

    def validate_template(self, template_path: str) -> Tuple[bool, Optional[str]]:
        """验证模板文件.

        Args:
            template_path: 模板文件路径

        Returns:
            (是否有效, 错误信息)
        """
        # 基本文件验证
        is_valid, error = self.docx_handler.validate_template(template_path)
        if not is_valid:
            return False, error

        try:
            # 尝试解析
            blocks = self.parse(template_path)

            if not blocks:
                return True, "Warning: No content blocks found in template"

            # 验证每个块
            for block in blocks:
                if not block.prompt.strip():
                    return False, f"Empty prompt in block {block.id}"

            return True, None

        except Exception as e:
            return False, f"Failed to parse template: {str(e)}"


def create_example_template(output_path: str) -> str:
    """创建示例模板文件.

    Args:
        output_path: 输出路径

    Returns:
        创建的模板路径
    """
    from docx import Document
    from docx.shared import Pt

    doc = Document()

    # 添加标题
    title = doc.add_heading("系统设计文档", level=1)

    # 添加各章节
    doc.add_heading("1. 系统概述", level=2)
    doc.add_paragraph('{{"type":"text", "prompt":"系统的整体功能概述，包括主要业务目标和技术目标"}}')

    doc.add_heading("2. 系统架构", level=2)
    doc.add_paragraph('{{"type":"text", "prompt":"系统的整体架构设计，包括技术栈、部署架构等"}}')

    doc.add_heading("3. 功能模块", level=2)
    doc.add_paragraph('{{"type":"headline", "prompt":"系统的主要功能模块", "list":"true", "min_length":"3", "max_length":"10"}}')

    doc.add_heading("4. 核心流程", level=2)
    doc.add_paragraph('{{"type":"text", "prompt":"系统的核心业务处理流程说明"}}')

    doc.add_heading("5. 数据模型", level=2)
    doc.add_paragraph('{{"type":"text", "prompt":"系统的主要数据模型和数据库设计说明"}}')

    # 保存
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)

    logger.info(
        "example_template_created",
        output_path=output_path,
    )

    return output_path
