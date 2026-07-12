import asyncio

import pytest

from app.core.nodes.outline_confirmation_node import OutlineConfirmationNode
from app.core.state import create_initial_state
from app.domain.model import TemplateBlock
from app.domain.static_list_provider import ListItem


METHOD_SOURCE_REF = {
    "sourceId": "method-vector-push-back",
    "symbolName": "push_back",
    "filePath": "TinySTL/Vector.impl.h",
    "symbolType": "Method",
    "lineStart": 12,
    "lineEnd": 28,
}

CLASS_SOURCE_REF = {
    "sourceId": "class-vector",
    "symbolName": "Vector",
    "filePath": "TinySTL/Vector.h",
    "symbolType": "Class",
}


class _StaticListProvider:
    async def get_list_items(self, list_tool, repo_id):
        return [
            ListItem(
                name="push_back（TinySTL/Vector.impl.h）",
                source_refs=[METHOD_SOURCE_REF],
            )
        ]


class _ContentGenerator:
    agent = None
    static_list_provider = _StaticListProvider()


class _EmptyStaticListProvider:
    async def get_list_items(self, list_tool, repo_id):
        return []


class _EmptyContentGenerator:
    agent = None
    static_list_provider = _EmptyStaticListProvider()


class _ProgressReporter:
    def __init__(self):
        self.messages = []

    async def report_percent(self, percent, message=None):
        self.messages.append((percent, message))


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
    assert expanded.source_refs == [METHOD_SOURCE_REF]


@pytest.mark.asyncio
async def test_outline_confirmation_inherits_method_source_refs_to_child_image_blocks():
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
            id="method-flowchart",
            parent_block_id=None,
            block_type="image",
            heading_level=0,
            order_no="b",
            content_text="函数流程图",
            attrs={"templateType": "template"},
        ),
        TemplateBlock(
            id="method-body",
            parent_block_id=None,
            block_type="paragraph",
            heading_level=0,
            order_no="c",
            content_text="函数说明模板",
            attrs={"templateType": "template"},
        ),
    ]

    result = await node.execute(state)

    flowchart_block = result["blocks"][1]
    paragraph_block = result["blocks"][2]
    assert flowchart_block.block_type == "image"
    assert flowchart_block.source_refs == [METHOD_SOURCE_REF]
    assert paragraph_block.block_type == "paragraph"
    assert paragraph_block.source_refs == []


def test_outline_confirmation_does_not_inherit_class_source_refs_to_child_image_blocks():
    block = TemplateBlock(
        id="class-diagram",
        parent_block_id=None,
        block_type="image",
        heading_level=0,
        order_no="a",
        content_text="类图",
        attrs={"templateType": "template"},
    )

    OutlineConfirmationNode._inherit_source_refs_to_image_block(
        block,
        [CLASS_SOURCE_REF],
    )

    assert block.source_refs == []


@pytest.mark.asyncio
async def test_outline_confirmation_reports_static_list_expand_progress():
    node = OutlineConfirmationNode(_ContentGenerator())
    reporter = _ProgressReporter()
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["__progress_reporter"] = reporter
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
    ]

    await node.execute(state)

    assert (35, "已获取1个函数列表条目，正在展开文档大纲...") in reporter.messages


@pytest.mark.asyncio
async def test_outline_confirmation_fails_when_static_method_list_empty():
    node = OutlineConfirmationNode(_EmptyContentGenerator())
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
    ]

    result = await node.execute(state)

    assert result["error"] == "函数列表为空，请先完成知识库初始化后再生成文档"
    assert result["message"] == "大纲确认失败: 函数列表为空，请先完成知识库初始化后再生成文档"


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

class _ConcurrentPromptDrivenAgent:
    def __init__(self):
        self.active_calls = 0
        self.max_active_calls = 0

    async def generate_with_tools(self, **kwargs):
        task_message = kwargs["task_message"]
        if "当前上下文：" not in task_message:
            return str([f"模块{index}" for index in range(10)]).replace("'", '"')

        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        await asyncio.sleep(0.01)
        self.active_calls -= 1
        module_name = task_message.split("当前上下文：", 1)[1].splitlines()[0]
        return f'["{module_name}_func"]'


class _ConcurrentPromptDrivenContentGenerator:
    agent = _ConcurrentPromptDrivenAgent()
    static_list_provider = _StaticListProvider()


@pytest.mark.asyncio
async def test_outline_confirmation_expands_nested_lists_with_bounded_parallelism():
    agent = _ConcurrentPromptDrivenContentGenerator.agent
    agent.active_calls = 0
    agent.max_active_calls = 0
    node = OutlineConfirmationNode(_ConcurrentPromptDrivenContentGenerator())
    node.list_parallelism = 3
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [
        TemplateBlock(
            id="module-heading",
            parent_block_id=None,
            block_type="heading",
            heading_level=2,
            order_no="a",
            content_text="模块标题",
            attrs={"templateType": "template", "isList": True, "prompt": "生成模块"},
        ),
        TemplateBlock(
            id="function-heading",
            parent_block_id=None,
            block_type="heading",
            heading_level=3,
            order_no="b",
            content_text="函数标题",
            attrs={"templateType": "template", "isList": True, "prompt": "生成函数"},
        ),
        TemplateBlock(
            id="function-body",
            parent_block_id=None,
            block_type="paragraph",
            heading_level=0,
            order_no="c",
            content_text="函数正文",
            attrs={"templateType": "template", "prompt": "描述函数"},
        ),
    ]

    result = await node.execute(state)

    headings = [
        block.content_text
        for block in result["blocks"]
        if block.block_type == "heading"
    ]
    expected_headings = []
    for index in range(10):
        expected_headings.extend([f"模块{index}", f"模块{index}_func"])
    assert result["error"] is None
    assert agent.max_active_calls == 3
    assert headings == expected_headings
