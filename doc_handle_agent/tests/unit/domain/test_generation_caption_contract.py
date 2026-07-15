from unittest.mock import MagicMock

from app.domain.generation_strategies import BatchedGenerationStrategy
from app.domain.model import TemplateBlock
from app.domain.prompts import BATCH_CONTEXT_STRATEGY_PROMPT, FULL_CONTEXT_STRATEGY_PROMPT


def test_generation_prompts_require_caption_without_number():
    for prompt in (FULL_CONTEXT_STRATEGY_PROMPT, BATCH_CONTEXT_STRATEGY_PROMPT):
        assert "同级 `caption`" in prompt
        assert "不包含图号或表号" in prompt
        assert "push_back函数设计表" in prompt
        assert "表格名称以“表”结尾" in prompt
        assert "仅作为 draw.io 文件元数据" in prompt
        assert "不会把该 `title` 渲染为图内标题" in prompt


def test_generation_strategy_serializes_and_parses_caption_contract():
    strategy = BatchedGenerationStrategy(MagicMock())
    block = TemplateBlock(
        id="function-table",
        parent_block_id=None,
        block_type="table",
        heading_level=0,
        order_no="a",
        content_text="函数设计表",
        attrs={"templateType": "template", "prompt": "生成函数设计表。"},
    )

    full_payload = strategy._serialize_blocks([block])
    batch_payload = strategy._serialize_batch_blocks([block])
    parsed = strategy._parse_blocks_from_response(
        '[{"id":"function-table","block_type":"table",'
        '"content_text":{"rows":[]},"caption":"push_back函数设计表"}]'
    )

    assert full_payload[0]["caption"] == ""
    assert batch_payload[0]["caption"] == ""
    assert parsed[0].caption == "push_back函数设计表"
