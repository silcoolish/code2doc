from app.core.nodes.generate_blocks_node import GenerateBlocksNode
from app.domain.model import DocumentBlock, TemplateBlock


def test_build_document_blocks_keeps_generated_source_refs():
    node = GenerateBlocksNode(content_generator=None)
    source_ref = {
        "sourceId": "method-main",
        "symbolName": "main",
        "filePath": "src/main.c",
        "lineStart": 10,
        "lineEnd": 18,
    }
    blocks = [
        TemplateBlock(
            id="flowchart-block",
            parent_block_id=None,
            block_type="image",
            heading_level=0,
            order_no="a",
            content_text="",
            attrs={"templateType": "template"},
        )
    ]
    results = [
        DocumentBlock(
            block_id="flowchart-block",
            block_type="image",
            text_content="main.flowchart.svg",
            source_refs=[source_ref],
        )
    ]

    doc_blocks = node._build_document_blocks(blocks, results)

    assert doc_blocks[0]["contentText"] == "main.flowchart.svg"
    assert doc_blocks[0]["sourceRefs"] == [source_ref]


def test_build_generated_table_preserves_falsy_cell_values():
    node = GenerateBlocksNode(content_generator=None)
    block = TemplateBlock(
        id="table-block",
        parent_block_id=None,
        block_type="table",
        heading_level=0,
        order_no="a",
        content_text="",
        attrs={
            "templateType": "template",
            "table": {
                "columns": [
                    {"id": "c1", "label": "数量"},
                    {"id": "c2", "label": "启用"},
                ],
                "rows": [],
                "headerRow": False,
                "headerColumn": False,
            },
        },
    )

    table = node._build_generated_table(
        block,
        {"rows": [{"cells": {"c1": 0, "c2": False}}]},
    )

    assert table["rows"][0]["cells"]["c1"]["text"] == "0"
    assert table["rows"][0]["cells"]["c2"]["text"] == "False"
