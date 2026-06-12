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

    对应 workspace DocumentBlockPayload 结构，用于文档生成流程。
    保留 template/children/source_node_ids 等内部专用字段。
    """

    id: str  # 唯一标识
    parent_block_id: Optional[str]  # 父block ID
    block_type: str  # "heading" | "paragraph" | "list" | "table" | "code" | "image" | "diagram"
    heading_level: int  # 标题层级
    order_no: str  # 排序号（workspace 已改为 VARCHAR fractional indexing）
    content_text: str  # 纯文本内容（对应 workspace contentText）
    attrs: Dict[str, Any] = field(default_factory=dict)  # 模板属性
    source_refs: List[Dict[str, Any]] = field(default_factory=list)  # 源码来源引用（对应 workspace sourceRefs）
    source_node_ids: List[str] = field(default_factory=list)  # 内容生成依据节点ID（内部使用）
    block_style: Dict[str, Any] = field(default_factory=dict)  # 块级样式（对应 workspace blockStyle）
    inline_styles: List[Dict[str, Any]] = field(default_factory=list)  # 行内样式列表（对应 workspace inlineStyles）
    children: List["TemplateBlock"] = field(default_factory=list)  # 子block列表（内部使用，保存时不传递）

    @property
    def is_template(self) -> bool:
        """是否为模板内容块.

        由 attrs 中的 templateType 决定，值为 "template" 表示模板内容。
        """
        return self.attrs.get("templateType") == "template"

    @property
    def is_heading(self) -> bool:
        """是否为标题."""
        return self.block_type == "heading"

    @property
    def is_list(self) -> bool:
        """是否生成列表."""
        return self.attrs.get("isList", False)

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
    def is_table(self) -> bool:
        """是否为表格类型内容块."""
        return self.block_type == "table"

    @property
    def table_schema(self) -> Optional[Dict[str, Any]]:
        """获取表格结构定义.

        从 attrs.table_schema 读取，用于向 LLM 传递列定义、表头配置等预设结构。
        """
        return self.attrs.get("table_schema")

    @property
    def is_image_block(self) -> bool:
        """是否为图片类型内容块.

        由 block_type 决定，不再依赖 attrs.type。
        """
        return self.block_type == "image"

    @property
    def image_id(self) -> Optional[str]:
        """获取图片 ID.

        当 type=img 时使用，存储需要获取 URL 的图片 ID。
        """
        return self.attrs.get("image_id")

    @property
    def list_tool(self) -> Optional[str]:
        """获取静态列表工具名称.

        当 list=true 时有效，指定直接调用的 MCP 工具名称（如 get_all_nodes）。
        若为空，则交由 LLM 判断生成列表项。
        """
        return self.attrs.get("list_tool")

    @property
    def img(self) -> Optional[str]:
        """获取图片搜索提示词 (已废弃，保留用于兼容).

        现在使用 type 和 image_ids 属性替代。
        """
        return self.attrs.get("img")

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "parent_block_id": self.parent_block_id,
            "block_type": self.block_type,
            "heading_level": self.heading_level,
            "order_no": self.order_no,
            "content_text": self.content_text,
            "attrs": self.attrs,
            "source_refs": self.source_refs,
            "source_node_ids": self.source_node_ids,
            "block_style": self.block_style,
            "inline_styles": self.inline_styles,
        }
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def __repr__(self) -> str:
        snippet = self.content_text[:30] if self.content_text else ""
        return f"TemplateBlock(id={self.id}, type={self.block_type}, template={self.is_template}, content={snippet}...)"


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

    表示LLM返回的文档内容块，只承载生成结果中的核心字段。
    其他元数据（如source_refs、source_node_ids）在内容生成节点中
    通过与TemplateBlock合并后写入doc_blocks。
    """

    block_type: str  # "heading" | "paragraph" | "image" | 其他扩展类型
    text_content: Any  # 文本内容，表格块在落库前阶段也可能暂存 rows 对象
    heading_level: int = 0  # 标题层级
    block_id: Optional[str] = None  # 关联的模板block ID
    source_refs: List[Dict[str, Any]] = field(default_factory=list)  # 生成结果携带的源码引用

    @property
    def is_heading(self) -> bool:
        """是否为标题块."""
        return self.block_type == "heading"

    @property
    def is_paragraph(self) -> bool:
        """是否为正文块（非标题即正文）."""
        return self.block_type != "heading"

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "block_type": self.block_type,
            "text_content": self.text_content,
            "heading_level": self.heading_level,
            "block_id": self.block_id,
            "source_refs": self.source_refs,
        }
