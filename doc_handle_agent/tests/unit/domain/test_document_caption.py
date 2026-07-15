from app.domain.document_caption import (
    fill_missing_document_block_captions,
    normalize_document_caption,
)


def test_normalize_document_caption_removes_agent_generated_number():
    assert normalize_document_caption("图1  push_back函数流程图", "image") == "push_back函数流程图"
    assert normalize_document_caption("表 2-1：push_back函数设计", "table") == "push_back函数设计表"
    assert normalize_document_caption("表 2-1：函数设计", "table") == ""
    assert normalize_document_caption("图一 系统架构图", "image") == "系统架构图"
    for separator in ("-", "－", "—", "–", "‑"):
        assert normalize_document_caption(f"图 2{separator}1 系统架构图", "image") == "系统架构图"
    assert normalize_document_caption("图1系统架构图", "image") == "系统架构图"
    assert normalize_document_caption("表2函数设计表", "table") == ""
    assert normalize_document_caption("图2.0系统图", "image") == "系统图"
    assert normalize_document_caption("图2D架构", "image") == "图2D架构图"
    assert normalize_document_caption("图2.0D架构", "image") == "图2.0D架构图"
    assert normalize_document_caption("图2-1D架构", "image") == "图2-1D架构图"
    assert normalize_document_caption("图一体化架构", "image") == "图一体化架构图"
    assert normalize_document_caption("表一致性检查", "table") == "表一致性检查表"
    assert normalize_document_caption("系统设计概述", "table") == "系统设计概述表"
    assert normalize_document_caption("系统功能表格", "table") == "系统功能表"
    assert normalize_document_caption("系统架构图示", "image") == "系统架构示意图"
    assert normalize_document_caption("系统功能表。", "table") == "系统功能表"
    assert normalize_document_caption("系统架构图。", "image") == "系统架构图"
    assert normalize_document_caption("系统架构图片", "image") == "系统架构图"
    assert normalize_document_caption("图1", "image") == ""
    assert normalize_document_caption("图示", "image") == ""
    assert normalize_document_caption("图示。", "image") == ""
    assert normalize_document_caption("函数设计表格", "table") == ""
    assert normalize_document_caption("函数流程图片", "image") == ""
    assert normalize_document_caption("模块图") == "模块图"


def test_fill_missing_captions_preserves_agent_or_template_caption():
    blocks = [
        _block("table", "table", attrs={"caption": "  模型生成名称  "}),
        _block("drawio", "image", attrs={"caption": "项目总体架构图"}),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "table") == "  模型生成名称  "
    assert _caption(result, "drawio") == "项目总体架构图"


def test_fill_missing_function_table_caption_uses_heading_source_ref():
    blocks = [
        _heading(
            "function",
            3,
            "push_back（TinySTL/Vector.impl.h）",
            source_refs=[
                {
                    "sourceId": "method_repo_push_back",
                    "symbolName": "push_back",
                    "nodeType": "Method",
                }
            ],
        ),
        _block("function-table", "table", prompt="基于真实源码生成函数设计表。"),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "function-table") == "push_back函数设计表"


def test_fill_missing_function_flowchart_caption_uses_function_context():
    blocks = [
        _heading(
            "function",
            3,
            "System_Init（src/system.c）",
            source_refs=[
                {
                    "sourceId": "method_repo_system_init",
                    "symbolName": "System_Init",
                }
            ],
        ),
        _block(
            "function-image",
            "image",
            attrs={"format": "flowchart"},
            content="system-init.svg",
        ),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "function-image") == "System_Init函数流程图"


def test_fill_missing_function_captions_preserve_operator_symbol_name():
    for symbol_name in ("operator!", "operator,"):
        function_source_refs = [
            {
                "sourceId": f"method_repo_{symbol_name}",
                "symbolName": symbol_name,
                "nodeType": "Method",
            }
        ]
        for source_refs in ([], function_source_refs):
            blocks = [
                _heading("function", 3, symbol_name, source_refs=source_refs),
                _block("function-table", "table", prompt="生成函数设计表。"),
                _block(
                    "function-image",
                    "image",
                    attrs={"format": "flowchart"},
                    prompt="生成目标函数流程图。",
                ),
            ]

            result = fill_missing_document_block_captions(blocks)

            assert _caption(result, "function-table") == f"{symbol_name}函数设计表"
            assert _caption(result, "function-image") == f"{symbol_name}函数流程图"


def test_fill_missing_captions_does_not_treat_module_flowchart_as_function():
    blocks = [
        _heading("module", 2, "订单处理模块"),
        _block(
            "module-flow",
            "image",
            attrs={"format": "flowchart"},
            prompt="为当前模块函数或主流程生成流程图。",
            source_refs=[
                {
                    "sourceId": "workflow_order",
                    "symbolName": "order_flow",
                    "nodeType": "Workflow",
                }
            ],
            content="order-flow.svg",
        ),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "module-flow") == "订单处理模块图"


def test_fill_missing_captions_does_not_use_typed_non_function_symbol():
    blocks = [
        _block(
            "function-table",
            "table",
            prompt="生成函数设计表。",
            source_refs=[
                {
                    "sourceId": "workflow_order",
                    "symbolName": "order_flow",
                    "nodeType": "Workflow",
                }
            ],
        ),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "function-table") == "函数设计表"


def test_fill_missing_captions_uses_document_context_for_generic_blocks():
    blocks = [
        _heading("overview", 2, "系统概述"),
        _block("overview-table", "table", prompt="生成系统设计概述表。"),
        _heading("architecture", 2, "功能架构"),
        _block("mermaid", "mermaid", content="flowchart LR\nA --> B"),
        {"id": "module-label", "blockType": "paragraph", "contentText": "功能入口设计模块："},
        _block("module-table", "table", prompt="为当前模块生成一张主要函数表。"),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "overview-table") == "系统概述表"
    assert _caption(result, "mermaid") == "功能架构图"
    assert _caption(result, "module-table") == "功能入口设计模块主要函数表"


def test_fill_missing_captions_normalizes_context_suffixes():
    blocks = [
        _heading("feature-table-heading", 2, "系统功能表格"),
        _block("feature-table", "table"),
        _heading("architecture-heading", 2, "系统架构图示"),
        _block("architecture-image", "image"),
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "feature-table") == "系统功能表"
    assert _caption(result, "architecture-image") == "系统架构示意图"


def test_fill_missing_image_caption_normalizes_numbered_alt_text():
    blocks = [
        _block(
            "architecture-image",
            "image",
            attrs={"alt": "图1 系统架构图"},
        )
    ]

    result = fill_missing_document_block_captions(blocks)

    assert _caption(result, "architecture-image") == "系统架构图"


def _heading(block_id, level, content, source_refs=None):
    return {
        "id": block_id,
        "blockType": "heading",
        "headingLevel": level,
        "contentText": content,
        "attrs": {},
        "sourceRefs": list(source_refs or []),
    }


def _block(block_id, block_type, *, attrs=None, prompt="", source_refs=None, content=""):
    next_attrs = dict(attrs or {})
    if prompt:
        next_attrs["prompt"] = prompt
    return {
        "id": block_id,
        "blockType": block_type,
        "contentText": content,
        "attrs": next_attrs,
        "sourceRefs": list(source_refs or []),
    }


def _caption(blocks, block_id):
    block = next(item for item in blocks if item["id"] == block_id)
    return block["attrs"]["caption"]
