import pytest

from app.core.nodes.store_block_list import StoreBlockListNode
from app.core.state import create_initial_state
from app.infrastructure.workspace import SaveDocumentResponse


class _WorkspaceAdapter:
    def __init__(self):
        self.request = None

    async def save_document(self, request):
        self.request = request
        return SaveDocumentResponse(success=True, document_id="doc-1")


@pytest.mark.asyncio
async def test_store_block_list_fills_missing_caption_after_image_processing():
    adapter = _WorkspaceAdapter()
    node = StoreBlockListNode(adapter)
    state = create_initial_state(repo_id="repo-1", template_id="template-1")
    state["title"] = "设计说明"
    state["total_blocks"] = 2
    state["doc_blocks"] = [
        {
            "id": "heading-1",
            "blockType": "heading",
            "headingLevel": 3,
            "contentText": "push_back（TinySTL/Vector.impl.h）",
            "attrs": {},
            "sourceRefs": [
                {
                    "sourceId": "method_repo_push_back",
                    "symbolName": "push_back",
                }
            ],
        },
        {
            "id": "table-1",
            "blockType": "table",
            "headingLevel": 0,
            "contentText": {"rows": []},
            "attrs": {"prompt": "生成函数设计表。"},
            "sourceRefs": [],
        },
    ]

    result = await node.execute(state)

    saved_table = next(
        block for block in adapter.request.blocks if block["blockType"] == "table"
    )
    assert result["error"] is None
    assert saved_table["attrs"]["caption"] == "push_back函数设计表"
