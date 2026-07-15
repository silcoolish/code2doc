import re
from xml.etree import ElementTree

from app.domain.drawio_architecture import normalize_architecture_spec, render_drawio_architecture


def test_drawio_architecture_skips_edges_when_connections_are_invalid():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "layers": [
                {
                    "id": "frontend",
                    "label": "L1",
                    "name": "前端",
                    "items": [{"id": "desktop", "name": "桌面端"}],
                },
                {
                    "id": "backend",
                    "label": "L2",
                    "name": "后端",
                    "items": [{"id": "workspace", "name": "工作空间服务"}],
                },
            ],
            "connections": [{"from": "missing-source", "to": "missing-target"}],
        },
        include_svg=True,
    )

    assert 'edge="1"' not in artifacts.drawio_xml
    assert "marker-end" not in artifacts.svg


def test_drawio_architecture_renders_valid_connections():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "layers": [
                {
                    "id": "frontend",
                    "label": "L1",
                    "name": "前端",
                    "items": [{"id": "desktop", "name": "桌面端"}],
                },
                {
                    "id": "backend",
                    "label": "L2",
                    "name": "后端",
                    "items": [{"id": "workspace", "name": "工作空间服务"}],
                },
            ],
            "connections": [{"from": "desktop", "to": "workspace", "label": "调用"}],
        },
        include_svg=True,
    )

    assert 'edge="1"' in artifacts.drawio_xml
    assert "marker-end" in artifacts.svg


def test_drawio_architecture_keeps_title_as_external_caption_only():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "layers": [
                {
                    "id": "service",
                    "label": "L1",
                    "name": "服务层",
                    "items": [{"id": "handler", "name": "处理器"}],
                }
            ],
        },
        include_svg=True,
    )
    cells = ElementTree.fromstring(artifacts.drawio_xml).findall(".//mxCell")
    title_cells = [cell for cell in cells if cell.attrib.get("value") == "系统架构图"]
    vertex_y = [
        int(geometry.attrib["y"])
        for cell in cells
        if cell.attrib.get("vertex") == "1"
        for geometry in cell.findall("mxGeometry")
        if geometry.attrib.get("y", "").isdigit()
    ]

    assert artifacts.caption == "系统架构图"
    assert title_cells == []
    assert ">系统架构图</text>" not in artifacts.svg
    assert min(vertex_y) < 40


def test_drawio_architecture_does_not_reuse_title_as_fallback_layer_name():
    artifacts = render_drawio_architecture(
        "not valid architecture json",
        fallback_title="项目总体架构图",
    )
    cells = ElementTree.fromstring(artifacts.drawio_xml).findall(".//mxCell")
    values = [cell.attrib.get("value", "") for cell in cells]

    assert artifacts.caption == "项目总体架构图"
    assert artifacts.spec["layers"][0]["name"] == "系统组成"
    assert "项目总体架构图" not in values
    assert any("系统组成" in value for value in values)


def test_drawio_architecture_does_not_repeat_caption_as_single_layer_name():
    spec = normalize_architecture_spec(
        {
            "title": "系统架构图",
            "layers": [
                {
                    "id": "architecture",
                    "name": "系统架构图",
                    "items": [{"id": "service", "name": "服务组件"}],
                }
            ],
        }
    )

    assert spec["layers"][0]["name"] == "系统组成"


def test_drawio_architecture_uses_content_based_dynamic_colors():
    layers = [
        {
            "id": f"layer-{index}",
            "label": f"L{index}",
            "name": name,
            "items": [{"id": f"node-{index}", "name": f"{name}节点"}],
        }
        for index, name in enumerate(
            ["输入与事件层", "游戏控制逻辑层", "碰撞检测服务层", "数据与状态管理层", "基础依赖层"],
            start=1,
        )
    ]

    tetris = render_drawio_architecture(
        {
            "title": "俄罗斯方块游戏控制软件总体架构图",
            "visual": {"layout": "layered"},
            "layers": layers,
        }
    )
    delivery = render_drawio_architecture(
        {
            "title": "智能送药小车控制系统总体架构",
            "visual": {"layout": "layered"},
            "layers": layers,
        }
    )

    assert _legend_stroke_colors(tetris.drawio_xml) != _legend_stroke_colors(delivery.drawio_xml)


def test_drawio_architecture_keeps_layer_label_out_of_item_area():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "visual": {"layout": "layered"},
            "layers": [
                {
                    "id": "service",
                    "label": "L1",
                    "name": "业务处理层",
                    "subtitle": "调度、校验与状态管理",
                    "items": [{"id": "scheduler", "name": "调度模块"}],
                },
            ],
        }
    )
    cells = ElementTree.fromstring(artifacts.drawio_xml).findall(".//mxCell")
    band = next(cell for cell in cells if cell.attrib.get("id", "").startswith("band-0-"))
    label = next(cell for cell in cells if cell.attrib.get("id", "").startswith("band-label-0-"))
    accent = next(cell for cell in cells if cell.attrib.get("id", "").startswith("band-accent-0-"))
    geometry = label.find("mxGeometry")

    assert band.attrib.get("value") == ""
    assert "fillColor=" in accent.attrib.get("style", "")
    assert "align=left" in label.attrib.get("style", "")
    assert geometry is not None
    assert geometry.attrib.get("width") == "430"


def test_drawio_architecture_prefers_model_visual_colors():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "visual": {"layout": "layered", "theme": "warm", "accent": "lime"},
            "layers": [
                {
                    "id": "frontend",
                    "label": "L1",
                    "name": "前端",
                    "color": "rose",
                    "items": [{"id": "desktop", "name": "桌面端"}],
                },
                {
                    "id": "backend",
                    "label": "L2",
                    "name": "后端",
                    "color": "not-a-color",
                    "items": [{"id": "workspace", "name": "工作空间服务"}],
                },
            ],
            "connections": [{"from": "desktop", "to": "workspace", "label": "调用", "color": "amber"}],
            "pipeline": [{"id": "input", "name": "输入"}, {"id": "output", "name": "输出"}],
        }
    )

    colors = _legend_stroke_colors(artifacts.drawio_xml)

    assert colors[0] == "#fb7185"
    assert "not-a-color" not in artifacts.drawio_xml
    assert "fillColor=#be123c" in artifacts.drawio_xml
    assert "strokeColor=#f59e0b" in artifacts.drawio_xml
    assert "fillColor=#f7fee7" in artifacts.drawio_xml
    assert "strokeColor=#84cc16" in artifacts.drawio_xml


def test_drawio_architecture_normalizes_invalid_visual_values():
    spec = normalize_architecture_spec(
        {
            "title": "系统架构图",
            "visual": {"layout": "unknown-layout", "theme": "not-a-theme"},
            "layers": [
                {
                    "id": "service",
                    "label": "L1",
                    "name": "服务层",
                    "items": [{"id": "handler", "name": "处理器"}],
                }
            ],
        }
    )

    assert spec["visual"]["layout"] in {"layered", "domain_map", "pipeline"}
    assert spec["visual"]["theme"] in {"classic", "cool", "warm", "contrast", "forest", "sunset", "vivid"}
    assert spec["visual"]["accent"]
    assert spec["layers"][0]["color"]


def test_drawio_architecture_renders_domain_map_layout():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "visual": {"layout": "domain_map", "theme": "cool"},
            "layers": [
                {
                    "id": "frontend",
                    "label": "L1",
                    "name": "前端域",
                    "items": [{"id": "desktop", "name": "桌面端"}],
                },
                {
                    "id": "backend",
                    "label": "L2",
                    "name": "服务域",
                    "items": [{"id": "api", "name": "接口服务"}],
                },
            ],
        }
    )

    ids = _cell_ids(artifacts.drawio_xml)

    assert any(cell_id.startswith("domain-card-0-") for cell_id in ids)
    assert any(cell_id.startswith("domain-accent-0-") for cell_id in ids)
    assert not any(cell_id.startswith("legend-0-") for cell_id in ids)


def test_drawio_architecture_renders_pipeline_layout():
    artifacts = render_drawio_architecture(
        {
            "title": "系统架构图",
            "visual": {"layout": "pipeline", "theme": "contrast", "accent": "pink"},
            "layers": [
                {
                    "id": "service",
                    "label": "L1",
                    "name": "服务层",
                    "items": [{"id": "handler", "name": "处理器"}],
                }
            ],
            "pipeline": [
                {"id": "input", "name": "输入"},
                {"id": "dispatch", "name": "调度"},
                {"id": "output", "name": "输出"},
            ],
        }
    )

    ids = _cell_ids(artifacts.drawio_xml)

    assert any(cell_id.startswith("main-flow-bg-") for cell_id in ids)
    assert any(cell_id.startswith("main-flow-accent-") for cell_id in ids)
    assert any(cell_id.startswith("support-card-0-") for cell_id in ids)
    assert any(cell_id.startswith("support-accent-0-") for cell_id in ids)
    assert not any(cell_id.startswith("pipeline-bg-") for cell_id in ids)
    assert "fillColor=#be185d" in artifacts.drawio_xml
    assert "fillColor=#fdf2f8" in artifacts.drawio_xml
    assert "strokeColor=#ec4899" in artifacts.drawio_xml


def _legend_stroke_colors(drawio_xml: str) -> list[str]:
    cells = ElementTree.fromstring(drawio_xml).findall(".//mxCell")
    colors = []
    for cell in cells:
        if not cell.attrib.get("id", "").startswith("legend-"):
            continue
        match = re.search(r"strokeColor=([^;]+);", cell.attrib.get("style", ""))
        if match:
            colors.append(match.group(1))
    return colors


def _cell_ids(drawio_xml: str) -> list[str]:
    cells = ElementTree.fromstring(drawio_xml).findall(".//mxCell")
    return [cell.attrib.get("id", "") for cell in cells]
