"""文档图表名称的清洗与确定性兜底规则."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.domain.source_refs import is_function_source_ref


_CAPTIONABLE_BLOCK_TYPES = {"table", "image", "mermaid"}
_GENERIC_CAPTIONS = {
    "图",
    "表",
    "图示",
    "图片",
    "数据表",
    "表格",
    "函数流程图",
    "函数设计表",
    "主要函数表",
}
_TRAILING_PUNCTUATION = re.compile(r"[\s:：;；,，。.!！?？、]+$")
_OUTLINE_PREFIX = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千0-9]+[章节篇]\s*|[0-9]+(?:\.[0-9]+)*(?:[.、\s]+))"
)
_NUMBERED_CAPTION_PREFIX = re.compile(
    r"^\s*[图表]\s*"
    r"(?:"
    r"[0-9]+(?:\s*[-.．—–－‑]\s*[0-9]+)*"
    r"(?!(?:\s*[-.．—–－‑]\s*[0-9]))"
    r"(?=$|\s|[:：、.．—–－‑-]|[\u3400-\u9fff])"
    r"|[一二三四五六七八九十百]+(?=$|\s|[:：、.．—–－‑-])"
    r")\s*(?:[:：、.．—–－‑-]\s*)?"
)
_MODULE_LABEL = re.compile(r"^[^\r\n]{1,48}模块\s*[：:]\s*$")
_IMAGE_ID_SUFFIXES = (
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".drawio",
)
_SOURCE_ID_KEYS = ("sourceId", "source_id", "nodeId", "node_id")
_SOURCE_TYPE_KEYS = (
    "symbolType",
    "symbol_type",
    "refType",
    "role",
    "nodeType",
    "node_type",
    "type",
)


def normalize_document_caption(value: Any, block_type: str = "") -> str:
    """清洗 Agent 返回的图表名称并移除模型误带的编号."""

    if not isinstance(value, str):
        return ""
    caption = " ".join(value.split())
    caption = _NUMBERED_CAPTION_PREFIX.sub("", caption).strip()
    caption = _TRAILING_PUNCTUATION.sub("", caption).strip()
    if not caption or caption in _GENERIC_CAPTIONS:
        return ""
    caption = _normalize_caption_suffix(caption, block_type)
    return "" if caption in _GENERIC_CAPTIONS else caption


def _normalize_caption_suffix(caption: str, block_type: str) -> str:
    """按图表类型统一名称后缀."""

    if block_type == "table":
        if caption.endswith("表格"):
            return caption[:-1]
        if not caption.endswith("表"):
            return f"{caption}表"
    if block_type in {"image", "mermaid"}:
        if caption.endswith("图示"):
            return f"{caption[:-2]}示意图"
        if caption.endswith("图片"):
            return f"{caption[:-2]}图"
        if not caption.endswith("图"):
            return f"{caption}图"
    return caption


def fill_missing_document_block_captions(
    blocks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """为缺少模型题注的最终图表块补充确定性名称.

    本层只保存不带图号、表号的名称，展示层按文档顺序计算编号。已有名称
    始终优先，避免覆盖 Agent、模板或用户命名。
    """

    headings: Dict[int, str] = {}
    heading_function_names: Dict[int, str] = {}
    recent_module_name: Optional[str] = None
    next_blocks: List[Dict[str, Any]] = []

    for block in blocks:
        block_type = _read_block_type(block)
        content_text = _read_text(block.get("contentText"))

        if block_type == "heading":
            heading_level = _read_heading_level(block)
            if heading_level is not None:
                for level in tuple(headings):
                    if level >= heading_level:
                        headings.pop(level, None)
                        heading_function_names.pop(level, None)
                if content_text:
                    headings[heading_level] = content_text
                function_name = _unique_function_symbol_name(block)
                if function_name:
                    heading_function_names[heading_level] = function_name
                if heading_level <= 2:
                    recent_module_name = None
        elif block_type == "paragraph" and _is_module_label(content_text):
            recent_module_name = _clean_context_name(content_text)

        attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
        if block_type not in _CAPTIONABLE_BLOCK_TYPES or _has_caption(attrs):
            next_blocks.append(block)
            continue

        caption = infer_document_block_caption(
            block,
            headings=headings,
            current_function_name=heading_function_names.get(3, ""),
            recent_module_name=recent_module_name,
        )
        if not caption:
            next_blocks.append(block)
            continue

        next_attrs = {**attrs, "caption": caption}
        if block_type == "image" and not _read_text(next_attrs.get("alt")):
            next_attrs["alt"] = caption
        next_blocks.append({**block, "attrs": next_attrs})

    return next_blocks


def infer_document_block_caption(
    block: Mapping[str, Any],
    *,
    headings: Mapping[int, str],
    current_function_name: str = "",
    recent_module_name: Optional[str] = None,
) -> str:
    """根据源码引用和标题上下文推导缺失的图表名称."""

    block_type = _read_block_type(block)
    attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
    prompt = _read_text(attrs.get("prompt"))
    nearest_heading = _nearest_heading(headings)
    source_function_name = _unique_function_symbol_name(block) or current_function_name
    function_name = source_function_name or _clean_function_name(headings.get(3, ""))

    if block_type == "table":
        if _is_function_design_table(prompt):
            return _join_caption_name(function_name, "函数设计表") if function_name else "函数设计表"
        if _is_module_function_table(prompt):
            context = recent_module_name or _clean_context_name(headings.get(2, ""))
            return _join_caption_name(context, "主要函数表") if context else "主要函数表"

        known_name = _known_table_name(prompt, nearest_heading)
        if known_name:
            return known_name
        return _join_caption_name(nearest_heading, "表") if nearest_heading else "数据表"

    if block_type in {"image", "mermaid"}:
        if _is_function_flowchart(block, attrs, prompt, bool(source_function_name)):
            return _join_caption_name(function_name, "函数流程图") if function_name else "函数流程图"

        explicit_name = _read_meaningful_image_name(attrs.get("alt"))
        if explicit_name:
            return _join_caption_name(explicit_name, "图")
        return _join_caption_name(nearest_heading, "图") if nearest_heading else "图示"

    return ""


def _read_block_type(block: Mapping[str, Any]) -> str:
    return _read_text(block.get("blockType") or block.get("block_type")).lower()


def _read_heading_level(block: Mapping[str, Any]) -> Optional[int]:
    value = block.get("headingLevel", block.get("heading_level"))
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _read_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _has_caption(attrs: Mapping[str, Any]) -> bool:
    return bool(_read_text(attrs.get("caption")))


def _clean_context_name(value: Any) -> str:
    text = _read_text(value)
    if not text:
        return ""
    text = _OUTLINE_PREFIX.sub("", text)
    return _TRAILING_PUNCTUATION.sub("", text).strip()


def _clean_function_name(value: Any) -> str:
    """清理标题编号并保留源码函数名中的运算符."""

    text = _read_text(value)
    text = _OUTLINE_PREFIX.sub("", text).strip()
    if text.startswith("operator"):
        return text
    return _TRAILING_PUNCTUATION.sub("", text).strip()


def _nearest_heading(headings: Mapping[int, str]) -> str:
    if not headings:
        return ""
    return _clean_context_name(headings[max(headings)])


def _is_module_label(value: Any) -> bool:
    return bool(_MODULE_LABEL.fullmatch(_read_text(value)))


def _unique_function_symbol_name(block: Mapping[str, Any]) -> str:
    refs = block.get("sourceRefs") or block.get("source_refs") or []
    if not isinstance(refs, list):
        return ""

    function_names = {
        _read_text(ref.get("symbolName") or ref.get("symbol_name"))
        for ref in refs
        if isinstance(ref, dict) and is_function_source_ref(ref)
    }
    function_names.discard("")
    if function_names:
        return next(iter(function_names)) if len(function_names) == 1 else ""

    legacy_names = {
        _read_text(ref.get("symbolName") or ref.get("symbol_name"))
        for ref in refs
        if isinstance(ref, dict) and _is_untyped_legacy_source_ref(ref)
    }
    legacy_names.discard("")
    return next(iter(legacy_names)) if len(legacy_names) == 1 else ""


def _is_untyped_legacy_source_ref(source_ref: Mapping[str, Any]) -> bool:
    has_identity = any(_read_text(source_ref.get(key)) for key in _SOURCE_ID_KEYS)
    has_type = any(_read_text(source_ref.get(key)) for key in _SOURCE_TYPE_KEYS)
    return not has_identity and not has_type


def _is_function_design_table(prompt: str) -> bool:
    return "函数设计表" in prompt


def _is_module_function_table(prompt: str) -> bool:
    return "主要函数表" in prompt


def _known_table_name(prompt: str, nearest_heading: str) -> str:
    context = f"{nearest_heading} {prompt}"
    if "缩略语" in context:
        return "缩略语表"
    if "术语" in context:
        return "术语定义表"
    if "系统" in context and "概述" in context:
        return "系统概述表"
    return ""


def _is_function_flowchart(
    block: Mapping[str, Any],
    attrs: Mapping[str, Any],
    prompt: str,
    has_function_context: bool,
) -> bool:
    if _is_drawio_architecture(attrs):
        return False

    value = _read_text(
        attrs.get("format") or attrs.get("diagramKind") or attrs.get("diagram_kind")
    ).lower()
    explicit_function_prompt = any(
        keyword in prompt for keyword in ("函数流程图", "当前函数", "目标函数", "该函数")
    )
    if value == "flowchart":
        return has_function_context or explicit_function_prompt
    return "流程图" in prompt and (has_function_context or explicit_function_prompt)


def _is_drawio_architecture(attrs: Mapping[str, Any]) -> bool:
    value = _read_text(
        attrs.get("format")
        or attrs.get("outputFormat")
        or attrs.get("diagramKind")
        or attrs.get("diagram_kind")
        or attrs.get("renderKind")
        or attrs.get("render_kind")
    )
    return value.lower() in {"drawio_architecture", "drawio"}


def _read_meaningful_image_name(value: Any) -> str:
    text = _read_text(value)
    if not text or len(text) > 80:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")) or lowered.endswith(_IMAGE_ID_SUFFIXES):
        return ""
    if text in {"图示", "图片", "函数流程图", "draw.io 文本绘图", "模板正文"}:
        return ""
    if text[0] in "[{":
        return ""
    if "flowchart " in lowered or "graph " in lowered:
        return ""
    return normalize_document_caption(text, "image")


def _join_caption_name(base: Any, suffix: str) -> str:
    clean_base = _read_text(base)
    if not clean_base:
        return suffix
    if suffix == "表":
        return _normalize_caption_suffix(clean_base, "table")
    if suffix == "图":
        return _normalize_caption_suffix(clean_base, "image")
    for overlap in range(min(len(clean_base), len(suffix)), 0, -1):
        if clean_base.endswith(suffix[:overlap]):
            return f"{clean_base}{suffix[overlap:]}"
    return f"{clean_base}{suffix}"
