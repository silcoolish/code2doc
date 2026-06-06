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
