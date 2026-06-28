import pytest
import asyncio
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


@pytest.mark.asyncio
async def test_batched_strategy_splits_batch_when_context_overflows():
    agent = MagicMock()
    call_count = 0

    async def generate_with_tools(**kwargs):
        nonlocal call_count
        call_count += 1
        task_message = kwargs["task_message"]
        if call_count == 1:
            raise RuntimeError(
                "This model's maximum context length is 1048565 tokens. "
                "However, you requested 1485401 tokens. Please reduce the length of the messages."
            )
        if "本次只生成以下模板块: b1" in task_message:
            return '[{"id": "b1", "block_type": "paragraph", "content_text": "one"}]'
        if "本次只生成以下模板块: b2" in task_message:
            return '[{"id": "b2", "block_type": "paragraph", "content_text": "two"}]'
        return "[]"

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=2, function_batch_parallelism=1)

    blocks = [
        TemplateBlock(
            id="b1", block_type="paragraph", content_text="t1",
            order_no="a", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="b2", block_type="paragraph", content_text="t2",
            order_no="b", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    results = await strategy.execute(blocks, repo_id="r1")

    assert call_count == 3
    result_map = {result.block_id: result.text_content for result in results}
    assert result_map == {"b1": "one", "b2": "two"}


@pytest.mark.asyncio
async def test_batched_strategy_raises_batch_error_without_skipping_blocks():
    agent = MagicMock()
    agent.generate_with_tools = AsyncMock(side_effect=RuntimeError("temporary model error"))
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=1)

    blocks = [
        TemplateBlock(
            id="b1", block_type="paragraph", content_text="t1",
            order_no="a", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="b2", block_type="paragraph", content_text="t2",
            order_no="b", parent_block_id=None, heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    with pytest.raises(RuntimeError, match="temporary model error"):
        await strategy.execute(blocks, repo_id="r1")


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


def test_batched_strategy_reports_function_parallel_blocker():
    strategy = BatchedGenerationStrategy(MagicMock(), function_batch_parallelism=2)

    batch = [
        TemplateBlock(
            id="method-heading",
            block_type="heading",
            content_text="ADC_Init（src/adc.c）",
            order_no="a",
            parent_block_id=None,
            heading_level=3,
            attrs={"templateType": "static"},
        ),
        TemplateBlock(
            id="method-body",
            block_type="paragraph",
            content_text="函数说明模板",
            order_no="b",
            parent_block_id=None,
            heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    reason = strategy._get_function_batch_parallel_blocker(batch, [batch[1]])

    assert reason == "missing_function_anchor"


def _method_heading(block_id: str, name: str) -> TemplateBlock:
    return TemplateBlock(
        id=block_id,
        block_type="heading",
        content_text=name,
        order_no=block_id,
        parent_block_id=None,
        heading_level=3,
        attrs={"templateType": "static", "template_block_id": "method-list"},
        source_refs=[{
            "sourceId": f"method-{block_id}",
            "symbolName": name,
            "symbolType": "Method",
        }],
    )


def _method_template(block_id: str, order_no: str) -> TemplateBlock:
    return TemplateBlock(
        id=block_id,
        block_type="paragraph",
        content_text="函数说明模板",
        order_no=order_no,
        parent_block_id=None,
        heading_level=0,
        attrs={"templateType": "template"},
    )


def _method_template_with_prompt(block_id: str, order_no: str, prompt: str) -> TemplateBlock:
    block = _method_template(block_id, order_no)
    block.attrs["prompt"] = prompt
    return block


@pytest.mark.asyncio
async def test_batched_strategy_processes_method_batches_concurrently():
    agent = MagicMock()
    active_calls = 0
    max_active_calls = 0

    async def generate_with_tools(**kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        task_message = kwargs["task_message"]
        for index in range(10):
            block_id = f"m{index}-body"
            if f'"id": "{block_id}"' in task_message:
                return f'[{{"id": "{block_id}", "block_type": "paragraph", "content_text": "m{index}"}}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=10)

    blocks = []
    for index in range(10):
        blocks.extend([
            _method_heading(f"m{index}", f"func_{index}"),
            _method_template(f"m{index}-body", f"m{index}-body"),
        ])

    results = await strategy.execute(blocks, repo_id="repo-1")

    assert max_active_calls == 10
    result_map = {result.block_id: result.text_content for result in results}
    for index in range(10):
        assert result_map[f"m{index}-body"] == f"m{index}"


@pytest.mark.asyncio
async def test_batched_strategy_allows_method_section_prompt_parallelism():
    agent = MagicMock()
    active_calls = 0
    max_active_calls = 0

    async def generate_with_tools(**kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        task_message = kwargs["task_message"]
        if '"id": "m0-body"' in task_message:
            return '[{"id": "m0-body", "block_type": "paragraph", "content_text": "m0"}]'
        if '"id": "m1-body"' in task_message:
            return '[{"id": "m1-body", "block_type": "paragraph", "content_text": "m1"}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=2)

    blocks = [
        _method_heading("m0", "func_0"),
        _method_template_with_prompt("m0-body", "m0-body", "生成当前函数章节说明"),
        _method_heading("m1", "func_1"),
        _method_template_with_prompt("m1-body", "m1-body", "生成当前函数章节说明"),
    ]

    await strategy.execute(blocks, repo_id="repo-1")

    assert max_active_calls == 2


@pytest.mark.asyncio
async def test_batched_strategy_allows_function_detail_prompt_parallelism():
    agent = MagicMock()
    active_calls = 0
    max_active_calls = 0

    async def generate_with_tools(**kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        task_message = kwargs["task_message"]
        if '"id": "m0-body"' in task_message:
            return '[{"id": "m0-body", "block_type": "paragraph", "content_text": "m0"}]'
        if '"id": "m1-body"' in task_message:
            return '[{"id": "m1-body", "block_type": "paragraph", "content_text": "m1"}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=2)

    prompt = (
        "围绕当前三级标题对应的函数生成函数级详细设计说明。"
        "说明内容覆盖函数作用、所在文件或所属模块、关键调用关系。"
    )
    blocks = [
        _method_heading("m0", "func_0"),
        _method_template_with_prompt("m0-body", "m0-body", prompt),
        _method_heading("m1", "func_1"),
        _method_template_with_prompt("m1-body", "m1-body", prompt),
    ]

    await strategy.execute(blocks, repo_id="repo-1")

    assert max_active_calls == 2


@pytest.mark.asyncio
async def test_batched_strategy_retries_failed_parallel_method_batch():
    agent = MagicMock()
    failed_once = False

    async def generate_with_tools(**kwargs):
        nonlocal failed_once
        task_message = kwargs["task_message"]
        if '"id": "m1-body"' in task_message and not failed_once:
            failed_once = True
            raise RuntimeError("temporary model error")
        for index in range(3):
            block_id = f"m{index}-body"
            if f'"id": "{block_id}"' in task_message:
                return f'[{{"id": "{block_id}", "block_type": "paragraph", "content_text": "m{index}"}}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=3)

    blocks = []
    for index in range(3):
        blocks.extend([
            _method_heading(f"m{index}", f"func_{index}"),
            _method_template(f"m{index}-body", f"m{index}-body"),
        ])

    results = await strategy.execute(blocks, repo_id="repo-1")

    result_map = {result.block_id: result.text_content for result in results}
    assert result_map["m0-body"] == "m0"
    assert result_map["m1-body"] == "m1"
    assert result_map["m2-body"] == "m2"


@pytest.mark.asyncio
async def test_batched_strategy_keeps_blocks_after_method_scope_sequential():
    agent = MagicMock()
    active_calls = 0
    max_active_calls = 0

    async def generate_with_tools(**kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        task_message = kwargs["task_message"]
        if '"id": "m0-body"' in task_message:
            return '[{"id": "m0-body", "block_type": "paragraph", "content_text": "m0"}]'
        if '"id": "summary-body"' in task_message:
            return '[{"id": "summary-body", "block_type": "paragraph", "content_text": "summary"}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=2)

    blocks = [
        _method_heading("m0", "func_0"),
        _method_template("m0-body", "m0-body"),
        TemplateBlock(
            id="summary-heading",
            block_type="heading",
            content_text="普通说明",
            order_no="summary-heading",
            parent_block_id=None,
            heading_level=3,
            attrs={"templateType": "static"},
        ),
        TemplateBlock(
            id="summary-body",
            block_type="paragraph",
            content_text="普通说明模板",
            order_no="summary-body",
            parent_block_id=None,
            heading_level=0,
            attrs={"templateType": "template"},
        ),
    ]

    await strategy.execute(blocks, repo_id="repo-1")

    assert max_active_calls == 1


@pytest.mark.asyncio
async def test_batched_strategy_keeps_narrative_batches_sequential():
    agent = MagicMock()
    active_calls = 0
    max_active_calls = 0

    async def generate_with_tools(**kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        task_message = kwargs["task_message"]
        if '"id": "overview-1"' in task_message:
            return '[{"id": "overview-1", "block_type": "paragraph", "content_text": "overview"}]'
        if '"id": "architecture-1"' in task_message:
            return '[{"id": "architecture-1", "block_type": "paragraph", "content_text": "architecture"}]'
        return '[]'

    agent.generate_with_tools = generate_with_tools
    strategy = BatchedGenerationStrategy(agent, max_batch_size=1, function_batch_parallelism=2)

    blocks = [
        TemplateBlock(
            id="overview-1",
            block_type="paragraph",
            content_text="项目总体说明",
            order_no="a",
            parent_block_id=None,
            heading_level=0,
            attrs={"templateType": "template", "prompt": "生成项目总体说明"},
        ),
        TemplateBlock(
            id="architecture-1",
            block_type="paragraph",
            content_text="架构说明",
            order_no="b",
            parent_block_id=None,
            heading_level=0,
            attrs={"templateType": "template", "prompt": "生成架构说明"},
        ),
    ]

    await strategy.execute(blocks, repo_id="repo-1")

    assert max_active_calls == 1
