"""docx文档处理器."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document
from docx.shared import Pt
from docx.text.paragraph import Paragraph

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
    ) -> List[Tuple[int, str, str]]:
        """提取内容块及其位置信息.

        Args:
            doc_path: 文档路径

        Returns:
            [(段落索引, 原始文本, 块内容), ...]
        """
        doc = Document(doc_path)
        blocks = []

        for idx, paragraph in enumerate(doc.paragraphs):
            text = paragraph.text.strip()
            if not text:
                continue

            matches = self.block_pattern.findall(text)
            for match in matches:
                blocks.append((idx, text, match.strip()))

        logger.info(
            "extract_blocks",
            doc_path=doc_path,
            block_count=len(blocks),
        )

        return blocks

    def replace_blocks(
        self,
        template_path: str,
        output_path: str,
        block_contents: Dict[str, str],
    ) -> str:
        """替换模板中的内容块.

        Args:
            template_path: 模板文件路径
            output_path: 输出文件路径
            block_contents: {段落索引: 生成内容}

        Returns:
            输出文件路径
        """
        logger.info(
            "replace_blocks_start",
            template_path=template_path,
            output_path=output_path,
            block_count=len(block_contents),
        )

        try:
            doc = Document(template_path)

            for para_idx_str, content in block_contents.items():
                para_idx = int(para_idx_str)

                if para_idx >= len(doc.paragraphs):
                    logger.warning(
                        "paragraph_index_out_of_range",
                        index=para_idx,
                        total=len(doc.paragraphs),
                    )
                    continue

                paragraph = doc.paragraphs[para_idx]

                # 替换内容块为生成内容
                original_text = paragraph.text
                new_text = self.block_pattern.sub(content, original_text, count=1)

                # 清除段落并重新添加文本
                paragraph.clear()
                run = paragraph.add_run(new_text)

                # 保留原始字体大小，如果没有则设置默认
                if run.font.size is None:
                    run.font.size = Pt(12)

                logger.debug(
                    "replace_block",
                    paragraph_index=para_idx,
                    original_length=len(original_text),
                    new_length=len(new_text),
                )

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
