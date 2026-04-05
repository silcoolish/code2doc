"""模板解析器单元测试."""

import json
import tempfile
from pathlib import Path

import pytest
from docx import Document

from app.core.state import ContentBlockType
from app.core.template_parser import TemplateParser, create_example_template


class TestTemplateParser:
    """模板解析器测试类."""

    @pytest.fixture
    def parser(self):
        """创建解析器实例."""
        return TemplateParser()

    @pytest.fixture
    def sample_template(self, tmp_path):
        """创建示例模板文件."""
        doc = Document()

        # 添加标题
        doc.add_heading("系统设计文档", level=1)

        # 添加内容块
        doc.add_heading("1. 系统概述", level=2)
        doc.add_paragraph('{{"type":"text", "prompt":"系统的整体功能概述"}}')

        doc.add_heading("2. 功能模块", level=2)
        doc.add_paragraph('{{"type":"headline", "prompt":"系统的主要功能模块", "list":"true", "min_length":"3", "max_length":"5"}}')

        # 添加普通段落
        doc.add_paragraph("这是一段普通文本，不包含内容块。")

        # 保存
        template_path = tmp_path / "test_template.docx"
        doc.save(template_path)

        return str(template_path)

    def test_parse_valid_template(self, parser, sample_template):
        """测试解析有效模板."""
        blocks = parser.parse(sample_template)

        assert len(blocks) == 2

        # 第一个块
        assert blocks[0].id == "1"  # 第2个段落
        assert blocks[0].type == ContentBlockType.TEXT
        assert blocks[0].prompt == "系统的整体功能概述"
        assert blocks[0].is_list is False

        # 第二个块
        assert blocks[1].id == "3"  # 第4个段落
        assert blocks[1].type == ContentBlockType.HEADLINE
        assert blocks[1].prompt == "系统的主要功能模块"
        assert blocks[1].is_list is True
        assert blocks[1].min_length == 3
        assert blocks[1].max_length == 5

    def test_parse_empty_template(self, parser, tmp_path):
        """测试解析空模板."""
        doc = Document()
        doc.add_paragraph("没有内容块的普通文档。")

        template_path = tmp_path / "empty_template.docx"
        doc.save(template_path)

        blocks = parser.parse(str(template_path))
        assert len(blocks) == 0

    def test_parse_invalid_json(self, parser, tmp_path):
        """测试解析无效JSON."""
        doc = Document()
        doc.add_paragraph('{{invalid json}}')

        template_path = tmp_path / "invalid_template.docx"
        doc.save(template_path)

        with pytest.raises(ValueError):
            parser.parse(str(template_path))

    def test_validate_template(self, parser, sample_template):
        """测试模板验证."""
        is_valid, message = parser.validate_template(sample_template)

        assert is_valid is True
        assert message is None or "Warning" in message

    def test_validate_nonexistent_file(self, parser):
        """测试验证不存在的文件."""
        is_valid, message = parser.validate_template("/nonexistent/file.docx")

        assert is_valid is False
        assert "not found" in message.lower()

    def test_preview_blocks(self, parser, sample_template):
        """测试预览内容块."""
        previews = parser.preview_blocks(sample_template)

        assert len(previews) == 2
        assert previews[0]["type"] == "text"
        assert previews[1]["type"] == "headline"


class TestExampleTemplate:
    """示例模板测试类."""

    def test_create_example_template(self, tmp_path):
        """测试创建示例模板."""
        output_path = str(tmp_path / "example.docx")
        result_path = create_example_template(output_path)

        assert Path(result_path).exists()

        # 验证可以解析
        parser = TemplateParser()
        blocks = parser.parse(result_path)

        assert len(blocks) > 0
