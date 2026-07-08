"""draw.io 架构图渲染工具."""

from __future__ import annotations

import html
import hashlib
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
    {"name": "indigo", "main": "#4338ca", "soft": "#eef2ff", "line": "#6366f1", "icon": "#4f46e5"},
    {"name": "emerald", "main": "#047857", "soft": "#ecfdf5", "line": "#10b981", "icon": "#059669"},
    {"name": "amber", "main": "#b45309", "soft": "#fffbeb", "line": "#f59e0b", "icon": "#d97706"},
    {"name": "sky", "main": "#0369a1", "soft": "#f0f9ff", "line": "#38bdf8", "icon": "#0284c7"},
    {"name": "rose", "main": "#be123c", "soft": "#fff1f2", "line": "#fb7185", "icon": "#e11d48"},
    {"name": "violet", "main": "#5b21b6", "soft": "#f5f3ff", "line": "#8b5cf6", "icon": "#7c3aed"},
    {"name": "red", "main": "#b91c1c", "soft": "#fef2f2", "line": "#ef4444", "icon": "#dc2626"},
    {"name": "cyan", "main": "#0e7490", "soft": "#ecfeff", "line": "#22d3ee", "icon": "#0891b2"},
    {"name": "lime", "main": "#4d7c0f", "soft": "#f7fee7", "line": "#84cc16", "icon": "#65a30d"},
    {"name": "yellow", "main": "#a16207", "soft": "#fefce8", "line": "#eab308", "icon": "#ca8a04"},
    {"name": "pink", "main": "#be185d", "soft": "#fdf2f8", "line": "#ec4899", "icon": "#db2777"},
    {"name": "zinc", "main": "#3f3f46", "soft": "#f4f4f5", "line": "#71717a", "icon": "#52525b"},
]
PALETTE_BY_NAME = {item["name"]: item for item in PALETTE}

THEME_COLOR_SETS = {
    "classic": ["blue", "green", "orange", "teal", "purple", "slate"],
    "cool": ["cyan", "blue", "indigo", "teal", "emerald", "zinc"],
    "warm": ["orange", "red", "amber", "rose", "yellow", "purple"],
    "contrast": ["red", "cyan", "lime", "violet", "amber", "zinc"],
    "forest": ["emerald", "lime", "green", "teal", "amber", "slate"],
    "sunset": ["rose", "orange", "amber", "red", "pink", "violet"],
    "vivid": ["cyan", "pink", "lime", "orange", "blue", "rose"],
}
LAYER_COLOR_THEMES = list(THEME_COLOR_SETS.values())
SUPPORTED_LAYOUTS = {"layered", "domain_map", "pipeline"}


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
    visual = _normalize_visual(parsed, title, layers, pipeline)
    layers = _apply_dynamic_layer_colors(layers, title, visual)

    return {
        "title": title,
        "visual": visual,
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
                "color": _normalize_color_name(item.get("color")),
            }
        )
    return layers


def _normalize_visual(
    spec: Dict[str, Any],
    title: str,
    layers: List[Dict[str, Any]],
    pipeline: List[Dict[str, str]],
) -> Dict[str, str]:
    """规整模型返回的视觉意图，非法值统一回退到后端可渲染范围"""
    raw_visual = spec.get("visual") or spec.get("diagram_style") or spec.get("style") or {}
    if not isinstance(raw_visual, dict):
        raw_visual = {}
    theme = _normalize_theme_name(raw_visual.get("theme") or spec.get("theme"))
    if not theme:
        # 模型不返回主题时仍写入兜底主题，便于排查最终色板来源
        theme = _resolve_theme_name(title, layers)
    layout = _normalize_layout_name(raw_visual.get("layout") or spec.get("layout"))
    variant = str(raw_visual.get("variant") or raw_visual.get("density") or "").strip().lower()
    if not layout:
        candidates = ["layered", "domain_map"]
        if pipeline:
            candidates.append("pipeline")
        # 版式兜底必须稳定，避免同一份文档反复刷新时版式跳变
        layout_seed = "|".join([title, theme] + [str(layer.get("name") or "") for layer in layers])
        layout = candidates[_stable_index(layout_seed, len(candidates))]
    accent = _normalize_color_name(raw_visual.get("accent") or spec.get("accent"))
    if not accent:
        # 主链路强调色独立于首层颜色，避免流程条总是橙色或与层色重复
        accent = _resolve_accent_color(title, theme, layers)
    return {
        "layout": layout,
        "theme": theme,
        "accent": accent,
        "variant": variant if variant in {"compact", "balanced", "detailed"} else "balanced",
    }


def _normalize_layout_name(value: Any) -> str:
    """只接受渲染器已实现的布局名"""
    layout = str(value or "").strip().lower().replace("-", "_")
    return layout if layout in SUPPORTED_LAYOUTS else ""


def _normalize_theme_name(value: Any) -> str:
    """只接受内置主题名，避免模型输出任意 CSS 值"""
    theme = str(value or "").strip().lower()
    return theme if theme in THEME_COLOR_SETS else ""


def _resolve_theme_name(title: str, layers: List[Dict[str, Any]]) -> str:
    """按内容稳定选择兜底主题"""
    seed = "|".join([title] + [str(layer.get("name") or "") for layer in layers])
    themes = list(THEME_COLOR_SETS.keys())
    return themes[_stable_index(seed, len(themes))]


def _resolve_accent_color(title: str, theme: str, layers: List[Dict[str, Any]]) -> str:
    """按主题和内容选择主链路强调色"""
    seed = "|".join([title, theme] + [str(layer.get("name") or "") for layer in layers])
    theme_colors = THEME_COLOR_SETS.get(theme) or PALETTE_BY_NAME.keys()
    return list(theme_colors)[_stable_index(seed + "|accent", len(theme_colors))]


def _normalize_color_name(value: Any) -> str:
    """只接受内置安全色名，防止模型输出不受控颜色"""
    color = str(value or "").strip().lower()
    return color if _is_palette_name(color) else ""


def _is_palette_name(value: str) -> bool:
    return value in PALETTE_BY_NAME


def _apply_dynamic_layer_colors(
    layers: List[Dict[str, Any]],
    title: str,
    visual: Dict[str, str],
) -> List[Dict[str, Any]]:
    """为未指定颜色的层补齐稳定配色"""
    seed = "|".join([title] + [str(layer.get("name") or "") for layer in layers])
    theme_name = visual.get("theme") or ""
    theme = THEME_COLOR_SETS.get(theme_name) or LAYER_COLOR_THEMES[_stable_index(seed, len(LAYER_COLOR_THEMES))]
    offset = _stable_index(seed + "|offset", len(theme))
    for index, layer in enumerate(layers):
        if layer.get("color"):
            continue
        # 保留模型合法配色，只为缺色层填补后端兜底色
        layer["color"] = theme[(index + offset) % len(theme)]
    return layers


def _stable_index(seed: str, modulo: int) -> int:
    """生成可复现的主题索引"""
    if modulo <= 0:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


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
                "color": _normalize_color_name(raw.get("color")),
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
    if color_name in PALETTE_BY_NAME:
        return PALETTE_BY_NAME[color_name]
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
        self.visual: Dict[str, str] = spec.get("visual") or {}
        self.layout_kind = self.visual.get("layout") or "layered"
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
        self._render_layout_drawio()
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

    def _render_layout_drawio(self) -> None:
        """按视觉布局渲染 draw.io 主体，并在无法满足条件时回退到分层图"""
        if self.layout_kind == "domain_map":
            self._render_domain_map_drawio()
            self._render_pipeline_drawio()
            return
        if self.layout_kind == "pipeline" and self.pipeline:
            self._render_pipeline_layout_drawio()
            return
        # pipeline 布局没有主链路时无法成立，回退到通用分层图
        self._render_layers_drawio()
        self._render_pipeline_drawio()

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
        accent = self._accent_palette()
        theme_colors = self._theme_color_names()
        self._svg_round_rect(x, y, w, h, 8, accent["soft"], accent["line"], opacity=0.98)
        count = len(self.pipeline)
        step_w = int((w - 60) / count)
        for index, step in enumerate(self.pipeline):
            sx = x + 28 + index * step_w
            step_palette = _palette(theme_colors[index % len(theme_colors)], index)
            self._svg_icon(sx, y + 18, step_palette["icon"], index)
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
                self._svg_arrow(ax, y + 38, ax + 30, y + 38, accent["line"])

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
        """渲染 draw.io 分层泳道布局"""
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
            self._add_drawio_accent_bar(f"legend-accent-{index}", palette["main"], layout.left_x, y, 10, layout.layer_h)
            band_id = self._add_drawio_vertex(
                f"band-{index}",
                "",
                layout.content_x,
                y,
                layout.content_w,
                layout.layer_h,
                self._drawio_box_style(palette["soft"], palette["line"], palette["main"], font_size=22),
            )
            self._add_drawio_accent_bar(f"band-accent-{index}", palette["main"], layout.content_x, y, 12, layout.layer_h)
            band_ref = ElementRef(band_id, layout.content_x, y, layout.content_w, layout.layer_h)
            self._register_ref(str(layer["id"]), band_ref, str(layer["name"]))
            # 层标题单独放在左侧说明区，避免被右侧组件节点覆盖
            self._add_drawio_vertex(
                f"band-label-{index}",
                self._drawio_value(layer["name"], str(layer.get("subtitle") or "")),
                layout.content_x + 28,
                y + 22,
                430,
                layout.layer_h - 44,
                self._drawio_box_style(
                    "none",
                    "none",
                    palette["main"],
                    font_size=20,
                    align="left",
                ),
            )
            self._render_layer_items_drawio(
                layer,
                layout.item_x,
                layout.item_y(y),
                layout.item_w,
                layout.item_h(),
                palette,
            )

    def _render_domain_map_drawio(self) -> None:
        """渲染 draw.io 领域分组布局，用于模块边界比上下游层级更重要的项目"""
        if not self.layers:
            return
        x = 64
        y = 102
        w = 1472
        h = 640 if not self.pipeline else 632
        columns = min(3, max(1, len(self.layers)))
        rows = (len(self.layers) + columns - 1) // columns
        gap = 22
        card_w = int((w - gap * (columns - 1)) / columns)
        card_h = int((h - gap * (rows - 1)) / rows)
        for index, layer in enumerate(self.layers):
            palette = _palette(str(layer.get("color") or ""), index)
            col = index % columns
            row = index // columns
            card_x = x + col * (card_w + gap)
            card_y = y + row * (card_h + gap)
            card_id = self._add_drawio_vertex(
                f"domain-card-{index}",
                "",
                card_x,
                card_y,
                card_w,
                card_h,
                self._drawio_box_style(palette["soft"], palette["line"], palette["main"], font_size=18),
            )
            self._add_drawio_accent_bar(f"domain-accent-{index}", palette["main"], card_x, card_y, card_w, 10)
            # 分组卡片自身也作为连接锚点，支持连接到 layer id/name
            self._register_ref(str(layer["id"]), ElementRef(card_id, card_x, card_y, card_w, card_h), str(layer["name"]))
            self._add_drawio_vertex(
                f"domain-label-{index}",
                self._drawio_value(layer["name"], str(layer.get("subtitle") or "")),
                card_x + 18,
                card_y + 18,
                card_w - 36,
                54,
                self._drawio_box_style("none", "none", palette["main"], font_size=18, align="left"),
            )
            self._render_layer_items_drawio(
                layer,
                card_x + 20,
                card_y + 88,
                card_w - 40,
                max(56, card_h - 108),
                palette,
            )

    def _render_pipeline_layout_drawio(self) -> None:
        """渲染 draw.io 主链路布局，用于流程顺序比模块分层更重要的项目"""
        self._render_pipeline_drawio(x=70, y=112, w=1460, h=104, prefix="main-flow")
        x = 70
        y = 270
        w = 1460
        h = 455
        columns = min(3, max(1, len(self.layers)))
        rows = (len(self.layers) + columns - 1) // columns
        gap = 18
        card_w = int((w - gap * (columns - 1)) / columns)
        card_h = int((h - gap * (rows - 1)) / max(rows, 1))
        for index, layer in enumerate(self.layers):
            palette = _palette(str(layer.get("color") or ""), index)
            col = index % columns
            row = index // columns
            card_x = x + col * (card_w + gap)
            card_y = y + row * (card_h + gap)
            card_id = self._add_drawio_vertex(
                f"support-card-{index}",
                "",
                card_x,
                card_y,
                card_w,
                card_h,
                self._drawio_box_style(palette["soft"], palette["line"], palette["main"], font_size=17),
            )
            self._add_drawio_accent_bar(f"support-accent-{index}", palette["main"], card_x, card_y, card_w, 10)
            # 支撑模块卡片作为连接锚点，主流程节点由 _render_pipeline_drawio 注册
            self._register_ref(str(layer["id"]), ElementRef(card_id, card_x, card_y, card_w, card_h), str(layer["name"]))
            self._add_drawio_vertex(
                f"support-label-{index}",
                f"{layer['label']}<br><b>{html.escape(layer['name'])}</b>",
                card_x + 16,
                card_y + 14,
                card_w - 32,
                46,
                self._drawio_box_style("none", "none", palette["main"], font_size=16, align="left"),
            )
            self._render_layer_items_drawio(
                layer,
                card_x + 18,
                card_y + 76,
                card_w - 36,
                max(52, card_h - 94),
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

    def _render_pipeline_drawio(
        self,
        x: int = 34,
        y: int = 790,
        w: int = 1530,
        h: int = 76,
        prefix: str = "pipeline",
    ) -> None:
        """渲染 draw.io 主链路，可作为底部流程或主版式流程复用"""
        if not self.pipeline:
            return
        accent = self._accent_palette()
        self._add_drawio_vertex(
            f"{prefix}-bg",
            "",
            x,
            y,
            w,
            h,
            self._drawio_box_style(accent["soft"], accent["line"], "#111827"),
        )
        self._add_drawio_accent_bar(f"{prefix}-accent", accent["main"], x, y, 12, h)
        count = len(self.pipeline)
        step_w = int((w - 60) / count)
        previous_id: Optional[str] = None
        for index, step in enumerate(self.pipeline):
            sx = x + 28 + index * step_w
            cell_id = self._add_drawio_vertex(
                f"{prefix}-{index}",
                self._drawio_value(step["name"], step.get("description") or ""),
                sx,
                y + 10,
                step_w - 44,
                max(56, h - 20),
                DRAWIO_PIPELINE_STEP_STYLE,
            )
            # 主链路节点也允许被 connections 按 id/name 引用
            self._register_ref(step["id"], ElementRef(cell_id, sx, y + 10, step_w - 44, max(56, h - 20)), step["name"])
            if previous_id:
                self._add_drawio_edge(previous_id, cell_id, "", accent["line"])
            previous_id = cell_id

    def _render_connections_drawio(self) -> None:
        """渲染 draw.io 连接关系."""
        for line in self._resolve_connection_lines():
            self._add_drawio_edge(line.source.id, line.target.id, line.label, line.color)

    def _resolve_connection_lines(self) -> List[ConnectionLine]:
        """解析可渲染连接线，跳过模型输出中无法定位的端点"""
        lines: List[ConnectionLine] = []
        for index, connection in enumerate(self.connections):
            source = self.refs.get(connection.get("from", ""))
            target = self.refs.get(connection.get("to", ""))
            if source and target:
                lines.append(
                    ConnectionLine(
                        source=source,
                        target=target,
                        label=connection.get("label") or "",
                        color=self._resolve_connection_color(connection, index),
                    )
                )
        return lines

    def _resolve_connection_color(self, connection: Dict[str, str], index: int) -> str:
        """解析连接线颜色，非法颜色按当前主题轮换兜底"""
        color = connection.get("color") or ""
        if _is_palette_name(color):
            return _palette(color, 0)["line"]
        theme_colors = self._theme_color_names()
        return _palette(theme_colors[index % len(theme_colors)], index)["line"]

    def _accent_palette(self) -> Dict[str, str]:
        """读取主链路强调色，缺失时使用当前主题的稳定兜底色"""
        accent = str(self.visual.get("accent") or "")
        return _palette(accent, 2)

    def _theme_color_names(self) -> List[str]:
        """读取当前主题色序列，非法主题回退到经典色序列"""
        return THEME_COLOR_SETS.get(str(self.visual.get("theme") or "")) or THEME_COLOR_SETS["classic"]

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

    def _add_drawio_accent_bar(self, cell_id: str, color: str, x: int, y: int, width: int, height: int) -> str:
        """追加 draw.io 实色强调条，让浅底主题在缩略图里也能区分"""
        return self._add_drawio_vertex(
            cell_id,
            "",
            x,
            y,
            width,
            height,
            self._drawio_accent_style(color),
        )

    def _next_cell_id(self, prefix: str) -> str:
        """生成 draw.io 单元 ID."""
        self.cell_counter += 1
        safe_prefix = re.sub(r"[^0-9a-zA-Z_\-]+", "-", prefix).strip("-") or "cell"
        return f"{safe_prefix}-{self.cell_counter}"

    def _drawio_box_style(
        self,
        fill: str,
        stroke: str,
        font_color: str,
        font_size: int = 16,
        align: str = "center",
    ) -> str:
        """生成 draw.io 盒子样式."""
        return (
            "rounded=1;whiteSpace=wrap;html=1;arcSize=8;"
            f"fillColor={fill};strokeColor={stroke};fontColor={font_color};fontSize={font_size};"
            f"spacing=12;align={align};verticalAlign=middle;"
        )

    def _drawio_accent_style(self, fill: str) -> str:
        """生成无文字强调条样式"""
        return (
            "rounded=1;whiteSpace=wrap;html=1;arcSize=8;"
            f"fillColor={fill};strokeColor=none;fontColor={fill};fontSize=1;"
            "spacing=0;align=center;verticalAlign=middle;"
        )

    def _drawio_value(self, name: str, description: str) -> str:
        """生成 draw.io 节点富文本."""
        if description:
            return f"<b>{html.escape(name)}</b><br><font style=\"font-size: 12px\">{html.escape(description)}</font>"
        return f"<b>{html.escape(name)}</b>"
