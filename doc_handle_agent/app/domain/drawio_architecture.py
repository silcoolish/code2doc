"""draw.io 架构图渲染工具."""

from __future__ import annotations

import html
import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_WIDTH = 1600
DEFAULT_HEIGHT = 900
DEFAULT_TITLE = "项目架构图"
SVG_FONT_FAMILY = "Inter, Microsoft YaHei, Arial, sans-serif"
DRAWIO_MODIFIED_AT = "2026-06-29T00:00:00.000Z"
DRAWIO_TITLE_STYLE = (
    "text;html=1;strokeColor=none;fillColor=none;fontSize=34;fontStyle=1;"
    "fontColor=#0f172a;align=center;verticalAlign=middle;"
)
DRAWIO_PIPELINE_STEP_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;strokeColor=none;fillColor=none;"
    "fontSize=14;fontColor=#111827;align=left;verticalAlign=middle;"
)

PALETTE = [
    {"name": "blue", "main": "#1769d6", "soft": "#eef6ff", "line": "#2f75d6", "icon": "#0d63ce"},
    {"name": "green", "main": "#14883f", "soft": "#f0fbf3", "line": "#1d8e45", "icon": "#13a05f"},
    {"name": "orange", "main": "#f97316", "soft": "#fff6e8", "line": "#f59e0b", "icon": "#f97316"},
    {"name": "teal", "main": "#0891b2", "soft": "#ecfeff", "line": "#06b6d4", "icon": "#0891b2"},
    {"name": "purple", "main": "#6d28d9", "soft": "#f5f0ff", "line": "#7c3aed", "icon": "#7c3aed"},
    {"name": "slate", "main": "#475569", "soft": "#f8fafc", "line": "#94a3b8", "icon": "#64748b"},
]


@dataclass
class DiagramArtifacts:
    title: str
    caption: str
    svg: str
    drawio_xml: str


@dataclass
class ElementRef:
    id: str
    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass(frozen=True)
class LayerLayout:
    left_x: int
    left_w: int
    content_x: int
    content_w: int
    top: int
    gap: int
    layer_h: int

    @property
    def item_x(self) -> int:
        return self.content_x + 520

    @property
    def item_w(self) -> int:
        return self.content_w - 550

    def layer_y(self, index: int) -> int:
        """计算指定层的顶部坐标."""
        return self.top + index * (self.layer_h + self.gap)

    def item_y(self, layer_y: int) -> int:
        """计算层内组件区的顶部坐标."""
        return layer_y + 22

    def item_h(self) -> int:
        """计算层内组件区高度."""
        return self.layer_h - 44


@dataclass(frozen=True)
class ItemGrid:
    columns: int
    rows: int
    gap: int
    item_w: int
    item_h: int


@dataclass(frozen=True)
class ConnectionLine:
    source: ElementRef
    target: ElementRef
    label: str
    color: str


def render_drawio_architecture(
    content: Any,
    fallback_title: str = DEFAULT_TITLE,
    include_svg: bool = False,
) -> DiagramArtifacts:
    """将结构化架构图规格渲染为 draw.io 产物."""
    spec = normalize_architecture_spec(content, fallback_title=fallback_title)
    layout = ArchitectureLayout(spec)
    return DiagramArtifacts(
        title=layout.title,
        caption=layout.title,
        svg=layout.render_svg() if include_svg else "",
        drawio_xml=layout.render_drawio_xml(),
    )


def normalize_architecture_spec(content: Any, fallback_title: str = DEFAULT_TITLE) -> Dict[str, Any]:
    """规整大模型输出为稳定的架构图规格."""
    parsed = _parse_content(content)
    if not isinstance(parsed, dict):
        parsed = {
            "title": fallback_title,
            "layers": [
                {"name": fallback_title, "items": _text_items(str(content or ""))}
            ],
        }

    title = str(parsed.get("title") or parsed.get("name") or fallback_title).strip() or fallback_title
    layers = _normalize_layers(parsed)
    if not layers:
        layers = [
            {
                "label": "L1",
                "name": "系统组成",
                "subtitle": "",
                "items": _text_items(str(parsed.get("summary") or "")),
            }
        ]

    pipeline = _normalize_pipeline(parsed.get("pipeline") or parsed.get("main_flow") or parsed.get("workflow"))
    connections = _normalize_connections(parsed.get("connections") or parsed.get("links") or parsed.get("edges"))

    return {
        "title": title,
        "layers": layers[:6],
        "connections": connections[:24],
        "pipeline": pipeline[:8],
    }


def _parse_content(content: Any) -> Any:
    """解析 JSON 或被代码块包裹的 JSON 内容."""
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    raw = content.strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 模型偶尔会在 JSON 前后夹解释文本，这里截取首尾括号做一次宽容解析
        json_start = min((idx for idx in [raw.find("{"), raw.find("[")] if idx >= 0), default=-1)
        json_end = max(raw.rfind("}"), raw.rfind("]"))
        if json_start >= 0 and json_end > json_start:
            try:
                return json.loads(raw[json_start : json_end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _normalize_layers(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """规整分层结构，限制单层组件数量."""
    raw_layers = spec.get("layers") or spec.get("sections") or spec.get("groups")
    if not isinstance(raw_layers, list):
        raw_layers = []
    layers: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_layers):
        if not isinstance(item, dict):
            item = {"name": str(item)}
        palette = PALETTE[index % len(PALETTE)]
        name = str(item.get("name") or item.get("title") or item.get("label") or f"第{index + 1}层").strip()
        label = str(item.get("label") or f"L{index + 1}").strip()
        subtitle = str(item.get("subtitle") or item.get("description") or item.get("summary") or "").strip()
        components = _normalize_items(
            item.get("items")
            or item.get("components")
            or item.get("nodes")
            or item.get("services")
        )
        if not components and subtitle:
            components = _text_items(subtitle)
        notes = _normalize_notes(item.get("notes") or item.get("key_points") or item.get("highlights"))
        layers.append(
            {
                "id": str(item.get("id") or _slug(name) or f"layer-{index + 1}"),
                "label": label,
                "name": name,
                "subtitle": subtitle,
                "items": components[:8],
                "notes": notes[:6],
                "color": item.get("color") or palette["name"],
            }
        )
    return layers


def _normalize_items(raw_items: Any) -> List[Dict[str, str]]:
    """规整组件、流程节点等列表结构."""
    if isinstance(raw_items, str):
        return _text_items(raw_items)
    if not isinstance(raw_items, list):
        return []
    items: List[Dict[str, str]] = []
    for index, raw in enumerate(raw_items):
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("title") or raw.get("label") or f"组件{index + 1}").strip()
            description = str(raw.get("description") or raw.get("summary") or raw.get("desc") or "").strip()
            item_id = str(raw.get("id") or _slug(name) or f"node-{index + 1}")
        else:
            name = str(raw).strip()
            description = ""
            item_id = _slug(name) or f"node-{index + 1}"
        if name:
            items.append({"id": item_id, "name": name, "description": description})
    return items


def _normalize_notes(raw_notes: Any) -> List[str]:
    """规整说明要点列表."""
    if isinstance(raw_notes, str):
        return [part.strip() for part in re.split(r"[;；\n]", raw_notes) if part.strip()]
    if not isinstance(raw_notes, list):
        return []
    return [str(item).strip() for item in raw_notes if str(item).strip()]


def _normalize_pipeline(raw_pipeline: Any) -> List[Dict[str, str]]:
    """规整主链路流程."""
    return _normalize_items(raw_pipeline)


def _normalize_connections(raw_connections: Any) -> List[Dict[str, str]]:
    """规整节点连接关系."""
    if not isinstance(raw_connections, list):
        return []
    connections: List[Dict[str, str]] = []
    for raw in raw_connections:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or raw.get("source") or "").strip()
        target = str(raw.get("to") or raw.get("target") or "").strip()
        if not source or not target:
            continue
        connections.append(
            {
                "from": source,
                "to": target,
                "label": str(raw.get("label") or raw.get("name") or "").strip(),
            }
        )
    return connections


def _text_items(text: str) -> List[Dict[str, str]]:
    """将纯文本拆成组件列表."""
    parts = [part.strip() for part in re.split(r"[、,，;；\n]", text or "") if part.strip()]
    if not parts:
        return [{"id": "overview", "name": "总体架构", "description": ""}]
    return [
        {"id": _slug(part) or f"item-{index + 1}", "name": part, "description": ""}
        for index, part in enumerate(parts[:6])
    ]


def _slug(value: str) -> str:
    """生成 draw.io 节点可用的短 ID."""
    slug = re.sub(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return slug[:48]


def _palette(color_name: str, index: int) -> Dict[str, str]:
    """按颜色名或序号选择配色."""
    for item in PALETTE:
        if item["name"] == color_name:
            return item
    return PALETTE[index % len(PALETTE)]


def _resolve_layer_layout(layer_count: int, has_pipeline: bool) -> LayerLayout:
    """计算左右栏与层级区域布局."""
    available_h = 650 if has_pipeline else 740
    gap = 16
    layer_h = max(110, int((available_h - gap * (layer_count - 1)) / max(layer_count, 1)))
    return LayerLayout(
        left_x=34,
        left_w=230,
        content_x=300,
        content_w=1264,
        top=90,
        gap=gap,
        layer_h=layer_h,
    )


def _resolve_item_grid(item_count: int, width: int, height: int) -> ItemGrid:
    """计算层内组件网格尺寸."""
    columns = min(4, max(1, item_count))
    rows = (item_count + columns - 1) // columns
    gap = 16
    item_w = int((width - gap * (columns - 1)) / columns)
    item_h = max(46, min(74, int((height - gap * (rows - 1)) / max(rows, 1))))
    return ItemGrid(columns=columns, rows=rows, gap=gap, item_w=item_w, item_h=item_h)


class ArchitectureLayout:
    def __init__(self, spec: Dict[str, Any]):
        """初始化架构图布局上下文."""
        self.spec = spec
        self.title = str(spec["title"])
        self.layers: List[Dict[str, Any]] = spec["layers"]
        self.connections: List[Dict[str, str]] = spec["connections"]
        self.pipeline: List[Dict[str, str]] = spec["pipeline"]
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.refs: Dict[str, ElementRef] = {}
        self.svg_parts: List[str] = []
        self.drawio_cells: List[str] = []
        self.cell_counter = 10

    def render_svg(self) -> str:
        """渲染兼容测试与兜底场景的 SVG."""
        self.refs = {}
        self.svg_parts = [
            (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{self.width}" height="{self.height}" '
                f'viewBox="0 0 {self.width} {self.height}">'
            ),
            "<defs>",
            (
                '<filter id="softShadow" x="-8%" y="-8%" width="116%" height="116%">'
                '<feDropShadow dx="0" dy="5" stdDeviation="8" '
                'flood-color="#0f172a" flood-opacity="0.10"/></filter>'
            ),
            (
                '<linearGradient id="pageBg" x1="0" x2="1" y1="0" y2="1">'
                '<stop offset="0" stop-color="#ffffff"/>'
                '<stop offset="1" stop-color="#f8fbff"/></linearGradient>'
            ),
            "</defs>",
            f'<rect width="{self.width}" height="{self.height}" rx="0" fill="url(#pageBg)"/>',
        ]
        self._svg_text(
            self.title,
            self.width // 2,
            48,
            size=42,
            weight=800,
            anchor="middle",
            fill="#0f172a",
        )
        self._render_layers_svg()
        self._render_pipeline_svg()
        self._render_connections_svg()
        self.svg_parts.append("</svg>")
        return "".join(self.svg_parts)

    def render_drawio_xml(self) -> str:
        """渲染可编辑 draw.io XML."""
        self.refs = {}
        self.drawio_cells = [
            '<mxCell id="0"/>',
            '<mxCell id="1" parent="0"/>',
        ]
        title_id = self._add_drawio_vertex(
            "title",
            self.title,
            340,
            16,
            920,
            58,
            DRAWIO_TITLE_STYLE,
        )
        self.refs["title"] = ElementRef(title_id, 340, 16, 920, 58)
        self._render_layers_drawio()
        self._render_pipeline_drawio()
        self._render_connections_drawio()
        cells = "".join(self.drawio_cells)
        return (
            f'<mxfile host="StarCodeDoc" modified="{DRAWIO_MODIFIED_AT}" '
            'agent="StarCodeDoc" version="24.0.0">'
            f'<diagram id="architecture" name="{html.escape(self.title)}">'
            f'<mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" '
            'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
            f'pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" '
            f'math="0" shadow="0"><root>{cells}</root></mxGraphModel>'
            "</diagram></mxfile>"
        )

    def _render_layers_svg(self) -> None:
        """渲染 SVG 分层区域."""
        layout = _resolve_layer_layout(len(self.layers), bool(self.pipeline))
        for index, layer in enumerate(self.layers):
            y = layout.layer_y(index)
            palette = _palette(str(layer.get("color") or ""), index)
            self._svg_round_rect(
                layout.left_x,
                y,
                layout.left_w,
                layout.layer_h,
                8,
                "#ffffff",
                palette["line"],
                opacity=0.72,
            )
            self._svg_icon(layout.left_x + 22, y + 28, palette["icon"], index)
            self._svg_text(
                layer["label"],
                layout.left_x + 92,
                y + 42,
                size=22,
                weight=800,
                fill=palette["main"],
            )
            self._svg_wrapped_text(
                layer["name"],
                layout.left_x + 92,
                y + 72,
                layout.left_w - 110,
                size=18,
                weight=700,
                fill="#0f172a",
            )

            self._svg_round_rect(
                layout.content_x,
                y,
                layout.content_w,
                layout.layer_h,
                8,
                palette["soft"],
                palette["line"],
                opacity=0.94,
                shadow=True,
            )
            band_ref = ElementRef(str(layer["id"]), layout.content_x, y, layout.content_w, layout.layer_h)
            self._register_ref(str(layer["id"]), band_ref, str(layer["name"]))
            self._svg_text(
                layer["name"],
                layout.content_x + 34,
                y + 42,
                size=28,
                weight=800,
                fill=palette["main"],
            )
            if layer.get("subtitle"):
                self._svg_wrapped_text(
                    str(layer["subtitle"]),
                    layout.content_x + 34,
                    y + 72,
                    460,
                    size=17,
                    fill="#1f2937",
                )
            self._render_layer_items_svg(
                layer,
                layout.item_x,
                layout.item_y(y),
                layout.item_w,
                layout.item_h(),
                palette,
            )

    def _render_layer_items_svg(
        self,
        layer: Dict[str, Any],
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Dict[str, str],
    ) -> None:
        """渲染 SVG 层内组件."""
        items = layer["items"] or [{"id": layer["id"], "name": layer["name"], "description": ""}]
        grid = _resolve_item_grid(len(items), width, height)
        for item_index, item in enumerate(items):
            col = item_index % grid.columns
            row = item_index // grid.columns
            item_x = x + col * (grid.item_w + grid.gap)
            item_y = y + row * (grid.item_h + grid.gap)
            self._svg_round_rect(
                item_x,
                item_y,
                grid.item_w,
                grid.item_h,
                7,
                "#ffffff",
                palette["line"],
                opacity=0.92,
            )
            self._svg_wrapped_text(
                item["name"],
                item_x + 16,
                item_y + 26,
                grid.item_w - 32,
                size=17,
                weight=700,
                fill="#0f172a",
            )
            if item.get("description") and grid.item_h >= 64:
                self._svg_wrapped_text(
                    item["description"],
                    item_x + 16,
                    item_y + 50,
                    grid.item_w - 32,
                    size=13,
                    fill="#475569",
                    max_lines=1,
                )
            ref = ElementRef(item["id"], item_x, item_y, grid.item_w, grid.item_h)
            self._register_ref(item["id"], ref, item["name"])

    def _render_pipeline_svg(self) -> None:
        """渲染 SVG 主链路."""
        if not self.pipeline:
            return
        y = 790
        x = 34
        w = 1530
        h = 76
        self._svg_round_rect(x, y, w, h, 8, "#fffaf0", "#f59e0b", opacity=0.98)
        count = len(self.pipeline)
        step_w = int((w - 60) / count)
        for index, step in enumerate(self.pipeline):
            sx = x + 28 + index * step_w
            self._svg_icon(sx, y + 18, PALETTE[index % len(PALETTE)]["icon"], index)
            self._svg_wrapped_text(
                step["name"],
                sx + 58,
                y + 30,
                step_w - 82,
                size=17,
                weight=800,
                fill="#111827",
                max_lines=1,
            )
            if step.get("description"):
                self._svg_wrapped_text(
                    step["description"],
                    sx + 58,
                    y + 54,
                    step_w - 82,
                    size=13,
                    fill="#334155",
                    max_lines=1,
                )
            if index < count - 1:
                ax = sx + step_w - 18
                self._svg_arrow(ax, y + 38, ax + 30, y + 38, "#f59e0b")

    def _render_connections_svg(self) -> None:
        """渲染 SVG 连接关系."""
        for line in self._resolve_connection_lines():
            self._svg_arrow(
                line.source.center_x,
                line.source.y + line.source.height,
                line.target.center_x,
                line.target.y,
                line.color,
                line.label,
            )

    def _render_layers_drawio(self) -> None:
        """渲染 draw.io 分层区域."""
        layout = _resolve_layer_layout(len(self.layers), bool(self.pipeline))
        for index, layer in enumerate(self.layers):
            y = layout.layer_y(index)
            palette = _palette(str(layer.get("color") or ""), index)
            self._add_drawio_vertex(
                f"legend-{index}",
                f"{layer['label']}<br><b>{html.escape(layer['name'])}</b>",
                layout.left_x,
                y,
                layout.left_w,
                layout.layer_h,
                self._drawio_box_style("#ffffff", palette["line"], palette["main"], font_size=18),
            )
            band_id = self._add_drawio_vertex(
                f"band-{index}",
                f"<b>{html.escape(layer['name'])}</b><br>{html.escape(str(layer.get('subtitle') or ''))}",
                layout.content_x,
                y,
                layout.content_w,
                layout.layer_h,
                self._drawio_box_style(palette["soft"], palette["line"], palette["main"], font_size=22),
            )
            band_ref = ElementRef(band_id, layout.content_x, y, layout.content_w, layout.layer_h)
            self._register_ref(str(layer["id"]), band_ref, str(layer["name"]))
            self._render_layer_items_drawio(
                layer,
                layout.item_x,
                layout.item_y(y),
                layout.item_w,
                layout.item_h(),
                palette,
            )

    def _render_layer_items_drawio(
        self,
        layer: Dict[str, Any],
        x: int,
        y: int,
        width: int,
        height: int,
        palette: Dict[str, str],
    ) -> None:
        """渲染 draw.io 层内组件."""
        items = layer["items"] or [{"id": layer["id"], "name": layer["name"], "description": ""}]
        grid = _resolve_item_grid(len(items), width, height)
        for item_index, item in enumerate(items):
            col = item_index % grid.columns
            row = item_index // grid.columns
            item_x = x + col * (grid.item_w + grid.gap)
            item_y = y + row * (grid.item_h + grid.gap)
            cell_id = self._add_drawio_vertex(
                item["id"],
                self._drawio_value(item["name"], item.get("description") or ""),
                item_x,
                item_y,
                grid.item_w,
                grid.item_h,
                self._drawio_box_style(
                    "#ffffff",
                    palette["line"],
                    "#0f172a",
                    font_size=15,
                ),
            )
            ref = ElementRef(cell_id, item_x, item_y, grid.item_w, grid.item_h)
            self._register_ref(item["id"], ref, item["name"])

    def _render_pipeline_drawio(self) -> None:
        """渲染 draw.io 主链路."""
        if not self.pipeline:
            return
        y = 790
        x = 34
        w = 1530
        h = 76
        self._add_drawio_vertex(
            "pipeline-bg",
            "",
            x,
            y,
            w,
            h,
            self._drawio_box_style("#fffaf0", "#f59e0b", "#111827"),
        )
        count = len(self.pipeline)
        step_w = int((w - 60) / count)
        previous_id: Optional[str] = None
        for index, step in enumerate(self.pipeline):
            sx = x + 28 + index * step_w
            cell_id = self._add_drawio_vertex(
                f"pipeline-{index}",
                self._drawio_value(step["name"], step.get("description") or ""),
                sx,
                y + 10,
                step_w - 44,
                56,
                DRAWIO_PIPELINE_STEP_STYLE,
            )
            if previous_id:
                self._add_drawio_edge(previous_id, cell_id, "", "#f59e0b")
            previous_id = cell_id

    def _render_connections_drawio(self) -> None:
        """渲染 draw.io 连接关系."""
        for line in self._resolve_connection_lines():
            self._add_drawio_edge(line.source.id, line.target.id, line.label, line.color)

    def _resolve_connection_lines(self) -> List[ConnectionLine]:
        """解析可渲染连接线."""
        lines: List[ConnectionLine] = []
        for connection in self.connections:
            source = self.refs.get(connection.get("from", ""))
            target = self.refs.get(connection.get("to", ""))
            if source and target:
                lines.append(
                    ConnectionLine(
                        source=source,
                        target=target,
                        label=connection.get("label") or "",
                        color="#1d4ed8",
                    )
                )
        return lines

    def _register_ref(self, key: str, ref: ElementRef, alias: Optional[str] = None) -> None:
        """登记节点引用，支持连接关系按 id 或名称寻址."""
        self.refs[key] = ref
        if alias:
            self.refs[alias] = ref

    def _svg_round_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        radius: int,
        fill: str,
        stroke: str,
        opacity: float = 1.0,
        shadow: bool = False,
    ) -> None:
        """追加 SVG 圆角矩形."""
        shadow_attr = ' filter="url(#softShadow)"' if shadow else ""
        self.svg_parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{radius}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="1.5" opacity="{opacity}"{shadow_attr}/>'
        )

    def _svg_icon(self, x: int, y: int, color: str, index: int) -> None:
        """追加 SVG 层级图标."""
        self.svg_parts.append(
            f'<g transform="translate({x},{y})" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
        )
        shape = index % 5
        if shape == 0:
            self.svg_parts.append('<rect x="2" y="4" width="40" height="28" rx="4"/><path d="M14 42h16M22 32v10"/>')
        elif shape == 1:
            self.svg_parts.append(
                '<rect x="8" y="3" width="32" height="36" rx="5"/>'
                '<path d="M15 13h18M15 23h18M15 33h18"/>'
            )
        elif shape == 2:
            self.svg_parts.append(
                '<path d="M22 4v12M22 32v12M6 22h12M26 22h12"/>'
                '<rect x="16" y="16" width="12" height="12" rx="3"/>'
                '<rect x="0" y="16" width="12" height="12" rx="3"/>'
                '<rect x="32" y="16" width="12" height="12" rx="3"/>'
            )
        elif shape == 3:
            self.svg_parts.append(
                '<path d="M8 36c8-24 20-24 28 0M12 30h20M16 22h12"/>'
                '<circle cx="22" cy="12" r="8"/>'
            )
        else:
            self.svg_parts.append(
                '<rect x="6" y="8" width="32" height="28" rx="3"/>'
                '<path d="M14 18h16M14 26h16"/>'
            )
        self.svg_parts.append("</g>")

    def _svg_text(
        self,
        text: str,
        x: int,
        y: int,
        size: int = 16,
        weight: int = 400,
        anchor: str = "start",
        fill: str = "#111827",
    ) -> None:
        """追加 SVG 单行文本."""
        self.svg_parts.append(
            f'<text x="{x}" y="{y}" font-family="{SVG_FONT_FAMILY}" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'fill="{fill}">{html.escape(text)}</text>'
        )

    def _svg_wrapped_text(
        self,
        text: str,
        x: int,
        y: int,
        width: int,
        size: int = 16,
        weight: int = 400,
        fill: str = "#111827",
        max_lines: int = 2,
    ) -> None:
        """追加 SVG 自动换行文本."""
        lines = self._wrap_text(text, max(4, width // max(size, 1)), max_lines)
        self.svg_parts.append(
            f'<text x="{x}" y="{y}" font-family="{SVG_FONT_FAMILY}" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}">'
        )
        for index, line in enumerate(lines):
            dy = 0 if index == 0 else int(size * 1.35)
            self.svg_parts.append(f'<tspan x="{x}" dy="{dy}">{html.escape(line)}</tspan>')
        self.svg_parts.append("</text>")

    def _svg_arrow(self, x1: int, y1: int, x2: int, y2: int, color: str, label: Optional[str] = None) -> None:
        """追加 SVG 贝塞尔连线."""
        marker_id = "arrow-" + color.strip("#")
        if f'id="{marker_id}"' not in "".join(self.svg_parts[:8]):
            self.svg_parts.insert(
                4,
                f'<marker id="{marker_id}" markerWidth="10" markerHeight="10" '
                f'refX="8" refY="3" orient="auto" markerUnits="strokeWidth">'
                f'<path d="M0,0 L0,6 L9,3 z" fill="{color}"/></marker>',
            )
        mid_y = (y1 + y2) // 2
        path = f"M{x1},{y1} C{x1},{mid_y} {x2},{mid_y} {x2},{y2}"
        self.svg_parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'marker-end="url(#{marker_id})"/>'
        )
        if label:
            self._svg_text(label, (x1 + x2) // 2 + 8, mid_y - 8, size=14, weight=700, fill=color)

    def _wrap_text(self, text: str, max_chars: int, max_lines: int) -> List[str]:
        """按估算字符数截断和换行."""
        if len(text) <= max_chars:
            return [text]
        lines = textwrap.wrap(text, width=max_chars, break_long_words=False, replace_whitespace=False)
        if not lines:
            return [text[:max_chars]]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip("，,。.;；") + "..."
        return lines

    def _add_drawio_vertex(
        self,
        cell_id: str,
        value: str,
        x: int,
        y: int,
        width: int,
        height: int,
        style: str,
    ) -> str:
        """追加 draw.io 顶点单元."""
        safe_id = self._next_cell_id(cell_id)
        self.drawio_cells.append(
            f'<mxCell id="{html.escape(safe_id)}" value="{html.escape(value)}" '
            f'style="{html.escape(style)}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry"/></mxCell>'
        )
        return safe_id

    def _add_drawio_edge(self, source: str, target: str, label: str, color: str) -> None:
        """追加 draw.io 边单元."""
        edge_id = self._next_cell_id("edge")
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
            f"jettySize=auto;html=1;endArrow=block;strokeWidth=2;strokeColor={color};"
            f"fontColor={color};"
        )
        self.drawio_cells.append(
            f'<mxCell id="{html.escape(edge_id)}" value="{html.escape(label)}" '
            f'style="{html.escape(style)}" edge="1" parent="1" '
            f'source="{html.escape(source)}" target="{html.escape(target)}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    def _next_cell_id(self, prefix: str) -> str:
        """生成 draw.io 单元 ID."""
        self.cell_counter += 1
        safe_prefix = re.sub(r"[^0-9a-zA-Z_\-]+", "-", prefix).strip("-") or "cell"
        return f"{safe_prefix}-{self.cell_counter}"

    def _drawio_box_style(self, fill: str, stroke: str, font_color: str, font_size: int = 16) -> str:
        """生成 draw.io 盒子样式."""
        return (
            "rounded=1;whiteSpace=wrap;html=1;arcSize=8;"
            f"fillColor={fill};strokeColor={stroke};fontColor={font_color};fontSize={font_size};"
            "spacing=12;align=center;verticalAlign=middle;"
        )

    def _drawio_value(self, name: str, description: str) -> str:
        """生成 draw.io 节点富文本."""
        if description:
            return f"<b>{html.escape(name)}</b><br><font style=\"font-size: 12px\">{html.escape(description)}</font>"
        return f"<b>{html.escape(name)}</b>"
