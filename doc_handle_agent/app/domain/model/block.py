"""Block domain models - 文档块领域模型."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class BlockType(str, Enum):
    """Block类型."""

    HEADING = "heading"  # 标题
    PARAGRAPH = "paragraph"  # 正文


class TemplateType(str, Enum):
    """模板类型."""

    STATIC = "static"  # 静态内容
    TEMPLATE = "template"  # 模板内容


class GenerationStatus(str, Enum):
    """生成状态."""

    PENDING = "pending"
    PARSING = "parsing"
    GENERATING = "generating"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TemplateBlock:
    """模板条目（Block）数据类.

    对应workspace_service返回的block结构，用于文档生成流程。
    """

    id: str  # 唯一标识
    parent_block_id: Optional[str]  # 父block ID
    block_type: str  # "heading" | "paragraph"
    block_title: str  # block标题
    heading_level: int  # 标题层级
    order_no: int  # 排序号
    markdown_content: str  # Markdown内容
    text_content: str  # 纯文本内容
    template: str  # "static" | "template"
    attrs: Dict[str, Any] = field(default_factory=dict)  # 模板属性
    source_refs: List[str] = field(default_factory=list)  # 内容生成依据节点ID
    children: List["TemplateBlock"] = field(default_factory=list)  # 子block列表

    @property
    def is_template(self) -> bool:
        """是否为模板内容块."""
        return self.template == "template"

    @property
    def is_heading(self) -> bool:
        """是否为标题."""
        return self.block_type == "heading"

    @property
    def is_list(self) -> bool:
        """是否生成列表."""
        return self.attrs.get("list", False)

    @property
    def prompt(self) -> Optional[str]:
        """获取生成提示词."""
        return self.attrs.get("prompt")

    @property
    def min_length(self) -> Optional[int]:
        """获取最小长度限制."""
        value = self.attrs.get("min_length")
        return int(value) if value is not None else None

    @property
    def max_length(self) -> Optional[int]:
        """获取最大长度限制."""
        value = self.attrs.get("max_length")
        return int(value) if value is not None else None

    @property
    def example(self) -> Optional[str]:
        """获取参考示例."""
        return self.attrs.get("example")

    @property
    def img(self) -> Optional[str]:
        """获取图片搜索提示词."""
        return self.attrs.get("img")

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "parent_block_id": self.parent_block_id,
            "block_type": self.block_type,
            "block_title": self.block_title,
            "heading_level": self.heading_level,
            "order_no": self.order_no,
            "markdown_content": self.markdown_content,
            "text_content": self.text_content,
            "template": self.template,
            "attrs": self.attrs,
            "source_refs": self.source_refs,
        }
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def __repr__(self) -> str:
        return f"TemplateBlock(id={self.id}, type={self.block_type}, template={self.is_template}, title={self.block_title[:30]}...)"


@dataclass
class ImageInfo:
    """图片信息.

    存储下载的图片文件路径信息（图片保存在临时目录）。
    """

    image_id: str  # 图片唯一标识
    image_path: Optional[str] = None  # 图片文件路径（临时目录）
    image_format: str = "png"  # 图片格式（如 png, jpg）
    method_id: Optional[str] = None  # 关联的方法节点ID
    method_name: Optional[str] = None  # 方法名称

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "image_id": self.image_id,
            "image_path": self.image_path,
            "image_format": self.image_format,
            "method_id": self.method_id,
            "method_name": self.method_name,
        }


@dataclass
class DocumentBlock:
    """文档块模型.

    表示文档中的一个内容块，可以是标题或正文。
    用于存储生成后的文档内容。
    """

    block_type: str  # "heading" | "paragraph"
    text_content: str  # 文本内容
    heading_level: int = 0  # 标题层级
    source_refs: List[str] = field(default_factory=list)  # 内容生成依据节点ID
    imgs: List[str] = field(default_factory=list)  # 包含的图片id

    def __post_init__(self):
        """验证block_type的合法性."""
        if self.block_type not in ("heading", "paragraph"):
            raise ValueError(f"Invalid block_type: {self.block_type}. Must be 'heading' or 'paragraph'")

    @property
    def is_heading(self) -> bool:
        """是否为标题块."""
        return self.block_type == "heading"

    @property
    def is_paragraph(self) -> bool:
        """是否为正文块."""
        return self.block_type == "paragraph"

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "block_type": self.block_type,
            "text_content": self.text_content,
            "heading_level": self.heading_level,
            "source_refs": self.source_refs,
            "imgs": self.imgs,
        }
