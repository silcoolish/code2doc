"""docx文档处理器."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from docx import Document
from docx.shared import Pt
from docx.text.paragraph import Paragraph

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ParagraphInfo:
    """段落信息."""

    def __init__(
        self,
        index: int,
        text: str,
        style_name: str,
        is_heading: bool,
        has_template: bool,
        template_content: Optional[str] = None,
    ):
        self.index = index
        self.text = text
        self.style_name = style_name
        self.is_heading = is_heading
        self.has_template = has_template
        self.template_content = template_content


class DocxHandler:
    """docx文档处理器."""

    def __init__(self):
        """初始化docx处理器."""
        self.block_pattern = re.compile(r'\{\{(.*?)\}\}')

    def read_paragraphs(self, doc_path: str) -> List[str]:
        """读取文档所有段落文本.

        Args:
            doc_path: 文档路径

        Returns:
            段落文本列表
        """
        doc = Document(doc_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

        logger.info(
            "read_paragraphs",
            doc_path=doc_path,
            paragraph_count=len(paragraphs),
        )

        return paragraphs

    def extract_blocks_with_positions(
        self,
        doc_path: str,
    ) -> List[Tuple[int, str, str, bool]]:
        """提取内容块及其位置信息和段落样式类型.

        Args:
            doc_path: 文档路径

        Returns:
            [(段落索引, 原始文本, 块内容, 是否为标题), ...]
            是否为标题: 根据段落样式判断（Heading开头为标题，其他为正文）
        """
        doc = Document(doc_path)
        blocks = []

        for idx, paragraph in enumerate(doc.paragraphs):
            text = paragraph.text.strip()
            if not text:
                continue

            matches = self.block_pattern.findall(text)
            if matches:
                # 判断段落样式：Heading 开头表示标题，其他为正文
                style_name = paragraph.style.name if paragraph.style else ""
                is_heading = style_name.startswith("Heading")

                for match in matches:
                    blocks.append((idx, text, match.strip(), is_heading))

        logger.info(
            "extract_blocks",
            doc_path=doc_path,
            block_count=len(blocks),
        )

        return blocks

    def extract_paragraphs_info(self, doc_path: str) -> List[ParagraphInfo]:
        """提取所有段落信息.

        Args:
            doc_path: 文档路径

        Returns:
            段落信息列表
        """
        doc = Document(doc_path)
        paragraphs_info = []

        for idx, paragraph in enumerate(doc.paragraphs):
            text = paragraph.text.strip()
            style_name = paragraph.style.name if paragraph.style else ""
            is_heading = style_name.startswith("Heading")

            matches = self.block_pattern.findall(text)
            has_template = len(matches) > 0
            template_content = matches[0].strip() if matches else None

            paragraphs_info.append(ParagraphInfo(
                index=idx,
                text=text,
                style_name=style_name,
                is_heading=is_heading,
                has_template=has_template,
                template_content=template_content,
            ))

        return paragraphs_info

    def replace_blocks(
        self,
        template_path: str,
        output_path: str,
        block_contents: Dict[str, Union[str, "ListBlockResult"]],
    ) -> str:
        """替换模板中的内容块.

        支持的内容类型：
        - str: 普通内容，直接替换
        - ListBlockResult: 列表块结果，包含列表项及其子段落

        Args:
            template_path: 模板文件路径
            output_path: 输出文件路径
            block_contents: {段落索引: 生成内容}

        Returns:
            输出文件路径
        """
        from app.core.state import ListBlockResult

        logger.info(
            "replace_blocks_start",
            template_path=template_path,
            output_path=output_path,
            block_count=len(block_contents),
        )

        try:
            doc = Document(template_path)
            paragraphs_info = self.extract_paragraphs_info(template_path)

            # 按段落索引降序排序，避免插入新段落后索引错乱
            sorted_items = sorted(
                block_contents.items(),
                key=lambda x: int(x[0]),
                reverse=True,
            )

            for para_idx_str, content in sorted_items:
                para_idx = int(para_idx_str)

                if para_idx >= len(doc.paragraphs):
                    logger.warning(
                        "paragraph_index_out_of_range",
                        index=para_idx,
                        total=len(doc.paragraphs),
                    )
                    continue

                # 判断内容类型
                if isinstance(content, ListBlockResult):
                    # 列表块：需要处理子段落结构
                    self._replace_with_list_block_result(
                        doc, para_idx, paragraphs_info, content
                    )
                else:
                    # 字符串内容：直接替换
                    paragraph = doc.paragraphs[para_idx]
                    self._replace_with_text(paragraph, str(content))

            # 确保输出目录存在
            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)

            # 保存文档
            doc.save(output_path)

            logger.info(
                "replace_blocks_success",
                output_path=output_path,
            )

            return output_path

        except Exception as e:
            logger.error(
                "replace_blocks_failed",
                template_path=template_path,
                output_path=output_path,
                error=str(e),
            )
            raise

    def _replace_with_text(self, paragraph: Paragraph, content: str) -> None:
        """用文本替换段落中的内容块.

        Args:
            paragraph: 段落对象
            content: 替换内容
        """
        # 替换内容块为生成内容
        original_text = paragraph.text
        new_text = self.block_pattern.sub(content, original_text, count=1)

        # 清除段落并重新添加文本
        paragraph.clear()
        run = paragraph.add_run(new_text)

        # 保留原始字体大小，如果没有则设置默认
        if run.font.size is None:
            run.font.size = Pt(12)

    def _replace_with_list_block_result(
        self,
        doc: Document,
        para_idx: int,
        paragraphs_info: List[ParagraphInfo],
        list_result: "ListBlockResult",
    ) -> None:
        """将列表模板段落替换为生成的列表内容.

        为每个生成的列表项复制子段落结构，并填充生成的内容。

        Args:
            doc: 文档对象
            para_idx: 列表模板段落索引
            paragraphs_info: 所有段落信息
            list_result: 列表块生成结果
        """
        from app.core.state import ListTemplateChild

        if not list_result.items:
            # 空列表，清空原段落
            paragraph = doc.paragraphs[para_idx]
            paragraph.clear()
            return

        # 获取原段落样式
        original_paragraph = doc.paragraphs[para_idx]
        original_style = original_paragraph.style

        # 获取列表模板的子段落定义
        list_children = list_result.list_children_template

        # 找到列表模板段落后的原始子段落数量（用于删除）
        original_child_count = self._count_list_children(
            paragraphs_info, para_idx
        )

        # 删除原始子段落（从后向前删除）
        for i in range(original_child_count):
            try:
                para_to_remove = doc.paragraphs[para_idx + 1]
                para_to_remove._element.getparent().remove(para_to_remove._element)
            except Exception:
                break

        # 处理第一个列表项：使用原段落
        first_item = list_result.items[0]
        original_paragraph.clear()
        run = original_paragraph.add_run(f"1. {first_item.headline}")
        if run.font.size is None:
            run.font.size = Pt(12)

        # 为第一个列表项添加子段落
        current_paragraph = original_paragraph
        for child_template in list_children:
            child_content = first_item.child_contents.get(child_template.id, "")
            if child_content:
                # 子段落：静态前缀 + 生成内容
                text = f"    {child_template.static_prefix} {child_content}"
            else:
                # 纯静态段落
                text = f"    {child_template.static_prefix}"

            current_paragraph = self._insert_paragraph_after(
                doc, current_paragraph, text
            )
            try:
                current_paragraph.style = original_style
            except Exception:
                pass

        # 处理剩余的列表项
        for i, item in enumerate(list_result.items[1:], start=2):
            # 添加列表项标题
            current_paragraph = self._insert_paragraph_after(
                doc, current_paragraph, f"{i}. {item.headline}"
            )
            try:
                current_paragraph.style = original_style
            except Exception:
                pass

            # 为列表项添加子段落
            for child_template in list_children:
                child_content = item.child_contents.get(child_template.id, "")
                if child_content:
                    text = f"    {child_template.static_prefix} {child_content}"
                else:
                    text = f"    {child_template.static_prefix}"

                current_paragraph = self._insert_paragraph_after(
                    doc, current_paragraph, text
                )
                try:
                    current_paragraph.style = original_style
                except Exception:
                    pass

    def _count_list_children(
        self,
        paragraphs_info: List[ParagraphInfo],
        list_para_idx: int,
    ) -> int:
        """计算列表模板段落后的子段落数量.

        子段落是指位于列表模板之后、下一个同层级或更高层级模板之前的段落。

        Args:
            paragraphs_info: 所有段落信息
            list_para_idx: 列表模板段落索引

        Returns:
            子段落数量
        """
        count = 0
        list_para_info = None

        # 找到列表模板段落
        for info in paragraphs_info:
            if info.index == list_para_idx:
                list_para_info = info
                break

        if not list_para_info:
            return 0

        # 检查后续段落
        for info in paragraphs_info:
            if info.index <= list_para_idx:
                continue

            # 如果遇到同层级或更高层级的标题，停止计数
            if info.is_heading:
                # 判断层级（通过标题级别数字）
                list_level = self._get_heading_level(list_para_info.style_name)
                current_level = self._get_heading_level(info.style_name)

                if current_level <= list_level:
                    break

            # 遇到下一个列表模板（Heading + 有模板），停止
            if info.is_heading and info.has_template:
                break

            count += 1

        return count

    def _get_heading_level(self, style_name: str) -> int:
        """获取标题级别.

        Args:
            style_name: 样式名称

        Returns:
            标题级别（非标题返回99）
        """
        if not style_name.startswith("Heading"):
            return 99

        try:
            # 提取数字，如 "Heading 1" -> 1
            level = int(style_name.replace("Heading", "").strip())
            return level
        except ValueError:
            return 99

    def _insert_paragraph_after(
        self,
        doc: Document,
        paragraph: Paragraph,
        text: str,
    ) -> Paragraph:
        """在指定段落后插入新段落.

        Args:
            doc: 文档对象
            paragraph: 参考段落
            text: 新段落文本

        Returns:
            新段落对象
        """
        from docx.oxml import OxmlElement

        # 创建新段落元素
        new_p = OxmlElement('w:p')
        paragraph._element.addnext(new_p)

        # 创建段落对象
        new_paragraph = Paragraph(new_p, paragraph._parent)

        # 添加文本
        run = new_paragraph.add_run(text)
        if run.font.size is None:
            run.font.size = Pt(12)

        return new_paragraph

    def get_document_info(self, doc_path: str) -> Dict[str, any]:
        """获取文档基本信息.

        Args:
            doc_path: 文档路径

        Returns:
            文档信息字典
        """
        doc = Document(doc_path)

        # 统计段落数和内容块数
        paragraph_count = len(doc.paragraphs)
        block_count = 0

        for paragraph in doc.paragraphs:
            matches = self.block_pattern.findall(paragraph.text)
            block_count += len(matches)

        return {
            "path": doc_path,
            "paragraph_count": paragraph_count,
            "block_count": block_count,
        }

    def validate_template(self, doc_path: str) -> Tuple[bool, Optional[str]]:
        """验证模板文件是否有效.

        Args:
            doc_path: 文档路径

        Returns:
            (是否有效, 错误信息)
        """
        try:
            path = Path(doc_path)

            if not path.exists():
                return False, f"Template file not found: {doc_path}"

            if not path.suffix.lower() in ['.docx', '.doc']:
                return False, f"Invalid file format: {path.suffix}"

            # 尝试打开文档
            doc = Document(doc_path)

            # 检查是否包含内容块
            has_blocks = False
            for paragraph in doc.paragraphs:
                if self.block_pattern.search(paragraph.text):
                    has_blocks = True
                    break

            if not has_blocks:
                logger.warning(
                    "template_no_blocks",
                    doc_path=doc_path,
                )

            return True, None

        except Exception as e:
            return False, f"Failed to validate template: {str(e)}"
