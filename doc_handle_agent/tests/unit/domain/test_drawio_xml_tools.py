import json

import pytest

from app.api.models.schemas import OptimizeDrawioDiagramRequest
from app.domain.drawio_diagram_optimize_agent import DrawioDiagramOptimizeAgent
from app.domain.drawio_xml_tools import (
    apply_diagram_operations,
    validate_drawio_xml,
    wrap_with_mxfile,
)


def test_wrap_with_mxfile_adds_root_cells_for_mxcell_fragment():
    xml = wrap_with_mxfile(
        '<mxCell id="2" value="入口" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="80" y="80" width="120" height="60" as="geometry" />'
        "</mxCell>"
    )

    assert "<mxfile" in xml
    assert 'id="0"' in xml
    assert 'id="1"' in xml
    assert validate_drawio_xml(xml) is None


def test_apply_diagram_operations_updates_adds_and_cascade_deletes():
    current_xml = wrap_with_mxfile(
        '<mxCell id="container" value="容器" style="swimlane;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="260" height="180" as="geometry" />'
        "</mxCell>"
        '<mxCell id="child" value="旧节点" style="rounded=1;" vertex="1" parent="container">'
        '<mxGeometry x="20" y="50" width="120" height="50" as="geometry" />'
        "</mxCell>"
        '<mxCell id="other" value="外部节点" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="360" y="90" width="120" height="50" as="geometry" />'
        "</mxCell>"
        '<mxCell id="edge1" style="edgeStyle=orthogonalEdgeStyle;endArrow=classic;" edge="1" parent="1" source="child" target="other">'
        '<mxGeometry relative="1" as="geometry" />'
        "</mxCell>"
    )

    result = apply_diagram_operations(
        current_xml,
        [
            {
                "operation": "update",
                "cell_id": "other",
                "new_xml": (
                    '<mxCell id="other" value="外部服务" style="rounded=1;" vertex="1" parent="1">'
                    '<mxGeometry x="360" y="90" width="120" height="50" as="geometry" />'
                    "</mxCell>"
                ),
            },
            {
                "operation": "add",
                "cell_id": "cache",
                "new_xml": (
                    '<mxCell id="cache" value="Redis" style="shape=cylinder3d;" vertex="1" parent="1">'
                    '<mxGeometry x="540" y="90" width="100" height="60" as="geometry" />'
                    "</mxCell>"
                ),
            },
            {"operation": "delete", "cell_id": "container"},
        ],
    )

    assert result.errors == []
    assert "外部服务" in result.result
    assert "Redis" in result.result
    assert "container" not in result.result
    assert "child" not in result.result
    assert "edge1" not in result.result
    assert validate_drawio_xml(result.result) is None


@pytest.mark.asyncio
async def test_optimize_xml_uses_edit_diagram_tool_call():
    current_xml = wrap_with_mxfile(
        '<mxCell id="gateway" value="API Gateway" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="80" y="80" width="140" height="60" as="geometry" />'
        "</mxCell>"
        '<mxCell id="redisManual" value="Redis" style="shape=cylinder3d;" vertex="1" parent="1">'
        '<mxGeometry x="300" y="80" width="100" height="60" as="geometry" />'
        "</mxCell>"
    )
    fake_llm = _FakeLLM(
        {
            "tool": "edit_diagram",
            "operations": [
                {
                    "operation": "update",
                    "cell_id": "gateway",
                    "new_xml": (
                        '<mxCell id="gateway" value="统一接入网关" style="rounded=1;" vertex="1" parent="1">'
                        '<mxGeometry x="80" y="80" width="140" height="60" as="geometry" />'
                        "</mxCell>"
                    ),
                },
                {
                    "operation": "add",
                    "cell_id": "bizService",
                    "new_xml": (
                        '<mxCell id="bizService" value="业务服务" style="rounded=1;" vertex="1" parent="1">'
                        '<mxGeometry x="80" y="190" width="140" height="60" as="geometry" />'
                        "</mxCell>"
                    ),
                },
            ],
        }
    )
    agent = DrawioDiagramOptimizeAgent(llm_client=fake_llm)

    result = await agent.optimize_xml(
        OptimizeDrawioDiagramRequest(
            repo_id="repo-1",
            document_id="doc-1",
            block_id="block-1",
            title="总体架构图",
            prompt="保留 Redis，网关改名并新增业务服务",
            current_xml=current_xml,
        )
    )

    assert "统一接入网关" in result
    assert "业务服务" in result
    assert "Redis" in result
    assert validate_drawio_xml(result) is None


@pytest.mark.asyncio
async def test_optimize_xml_prompt_protects_svg_source_location():
    current_xml = wrap_with_mxfile(
        '<mxCell id="func-parseOrder" value="parseOrder" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="80" y="80" width="140" height="60" as="geometry" />'
        "</mxCell>"
    )
    fake_llm = _FakeLLM(
        {
            "tool": "edit_diagram",
            "operations": [
                {
                    "operation": "update",
                    "cell_id": "func-parseOrder",
                    "new_xml": (
                        '<mxCell id="func-parseOrder" value="parseOrder" style="rounded=1;fillColor=#e0f2fe;" vertex="1" parent="1">'
                        '<mxGeometry x="80" y="80" width="140" height="60" as="geometry" />'
                        "</mxCell>"
                    ),
                },
            ],
        }
    )
    agent = DrawioDiagramOptimizeAgent(llm_client=fake_llm)

    await agent.optimize_xml(
        OptimizeDrawioDiagramRequest(
            repo_id="repo-1",
            document_id="doc-1",
            block_id="block-1",
            title="函数流程图",
            prompt="美化一下颜色",
            current_xml=current_xml,
        )
    )

    joined_prompt = "\n".join(message.content for message in fake_llm.messages)
    assert "源码定位保护要求" in joined_prompt
    assert "代码行定位" in joined_prompt
    assert "不要 delete 后重新 add" in joined_prompt


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.messages = []

    async def ainvoke(self, messages):
        self.messages = messages
        return _FakeResponse(json.dumps(self.payload, ensure_ascii=False))
