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
