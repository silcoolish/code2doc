import pytest

from app.core.nodes.outline_confirmation_node import OutlineConfirmationNode
from app.core.state import create_initial_state
from app.domain.model import TemplateBlock
from app.domain.static_list_provider import ListItem


class _StaticListProvider:
    async def get_list_items(self, list_tool, repo_id):
        return [
            ListItem(
                name="push_back（TinySTL/Vector.impl.h）",
                source_refs=[{
                    "sourceId": "method-vector-push-back",
                    "symbolName": "push_back",
                    "filePath": "TinySTL/Vector.impl.h",
                }],
            )
        ]


class _ContentGenerator:
    agent = None
    static_list_provider = _StaticListProvider()


@pytest.mark.asyncio
async def test_outline_confirmation_expands_static_method_list_with_source_refs():
    node = OutlineConfirmationNode(_ContentGenerator())
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [
        TemplateBlock(
            id="method-list",
            parent_block_id=None,
            block_type="heading",
            heading_level=3,
            order_no="a",
            content_text="函数详细设计项",
            attrs={
                "templateType": "template",
                "isList": True,
                "list_tool": "get_all_methods",
            },
        ),
        TemplateBlock(
            id="method-body",
            parent_block_id=None,
            block_type="paragraph",
            heading_level=0,
            order_no="b",
            content_text="函数说明模板",
            attrs={"templateType": "template"},
        ),
    ]

    result = await node.execute(state)

    expanded = result["blocks"][0]
    assert expanded.content_text == "push_back（TinySTL/Vector.impl.h）"
    assert expanded.attrs["templateType"] == "static"
    assert expanded.attrs["template_block_id"] == "method-list"
    assert expanded.source_refs == [{
        "sourceId": "method-vector-push-back",
        "symbolName": "push_back",
        "filePath": "TinySTL/Vector.impl.h",
    }]


def test_outline_confirmation_assigns_order_no_incrementally():
    blocks = [
        TemplateBlock(
            id=f"old-{index}",
            parent_block_id=None,
            block_type="paragraph",
            heading_level=0,
            order_no="",
            content_text=f"block-{index}",
            attrs={},
        )
        for index in range(120)
    ]

    OutlineConfirmationNode._assign_block_identity(blocks)

    order_numbers = [block.order_no for block in blocks]
    assert [block.id for block in blocks] == [str(index) for index in range(120)]
    assert order_numbers == sorted(order_numbers)
    assert len(order_numbers) == len(set(order_numbers))
