"""源码引用判断工具"""

from typing import Any, Dict


def is_function_source_ref(source_ref: Dict[str, Any]) -> bool:
    """判断源码引用是否明确指向函数或方法

    优先识别当前知识库的 Method/Function 节点 ID，同时保留结构化类型字段，
    供大纲展开、批量生成和图片处理使用同一套判定规则

    Args:
        source_ref: 文档块中的单条源码引用

    Returns:
        引用是否指向函数或方法节点
    """
    source_id = str(
        source_ref.get("sourceId")
        or source_ref.get("source_id")
        or source_ref.get("nodeId")
        or source_ref.get("node_id")
        or ""
    ).strip().lower()
    source_types = (
        source_ref.get("symbolType"),
        source_ref.get("symbol_type"),
        source_ref.get("refType"),
        source_ref.get("role"),
        source_ref.get("nodeType"),
        source_ref.get("node_type"),
        source_ref.get("type"),
    )
    # 真实 Method 引用不保证携带 symbolType，节点 ID 是必要判定依据
    return source_id.startswith(("method_", "function_")) or any(
        str(source_type or "").strip().lower() in {"method", "function"}
        for source_type in source_types
    )
