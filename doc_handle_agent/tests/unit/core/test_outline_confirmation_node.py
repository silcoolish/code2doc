from app.core.nodes.outline_confirmation_node import OutlineConfirmationNode
from app.domain.model import TemplateBlock


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
