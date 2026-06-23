import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.generation_strategies import BatchedGenerationStrategy
from app.domain.model import TemplateBlock, DocumentBlock


@pytest.mark.asyncio
async def test_batched_strategy_triggers_on_progress():
    agent = MagicMock()
    agent.generate_with_tools = AsyncMock(return_value='[\n  {"id": "1", "block_type": "paragraph", "content_text": "hello"}\n]')

    strategy = BatchedGenerationStrategy(agent)

    blocks = [
        TemplateBlock(
            id="1", block_type="paragraph", content_text="t1",
            order_no="a", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="2", block_type="paragraph", content_text="t2",
            order_no="b", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    progress_calls = []

    def on_progress(current, total):
        progress_calls.append((current, total))

    results = await strategy.execute(blocks, repo_id="r1", on_progress=on_progress)

    assert len(progress_calls) > 0
    assert progress_calls[-1][0] == 2
    assert progress_calls[-1][1] == 2


def test_batched_strategy_ignores_generated_template_context_when_checking_missing():
    strategy = BatchedGenerationStrategy(MagicMock())

    batch = [
        TemplateBlock(
            id="h1", block_type="heading", content_text="动态标题",
            order_no="a", parent_block_id=None, heading_level=1,
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="p2", block_type="paragraph", content_text="正文",
            order_no="b", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]
    results = [
        DocumentBlock(
            block_id="p2",
            block_type="paragraph",
            text_content="生成完成",
        )
    ]

    missing_blocks = strategy._get_missing_template_blocks(
        batch,
        results,
        generated_ids={"h1"},
    )
    filled_results = strategy._fill_missing_template_results(
        batch,
        results,
        generated_ids={"h1"},
    )

    assert missing_blocks == []
    assert [result.block_id for result in filled_results] == ["p2"]


def test_batched_strategy_parse_response_ignores_generated_template_context():
    strategy = BatchedGenerationStrategy(MagicMock())

    batch = [
        TemplateBlock(
            id="h1", block_type="heading", content_text="动态标题",
            order_no="a", parent_block_id=None, heading_level=1,
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="p2", block_type="paragraph", content_text="正文",
            order_no="b", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    raw_content = """
    [
      {"id": "h1", "block_type": "heading", "content_text": "被错误回传的祖先标题"},
      {"id": "p2", "block_type": "paragraph", "content_text": "本轮真正生成的正文"}
    ]
    """

    results = strategy._parse_response(
        raw_content,
        batch,
        generated_ids={"h1"},
        fill_missing_placeholders=False,
    )

    assert [result.block_id for result in results] == ["p2"]
