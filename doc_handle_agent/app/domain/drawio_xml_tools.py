"""draw.io XML 工具调用辅助能力."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT_CELLS = '<mxCell id="0" /><mxCell id="1" parent="0" />'
EMPTY_MXFILE = (
    '<mxfile><diagram name="Page-1" id="page-1"><mxGraphModel><root>'
    f'{ROOT_CELLS}</root></mxGraphModel></diagram></mxfile>'
)


@dataclass
class OperationError:
    """单个 draw.io XML 编辑操作的失败原因."""

    type: str
    cell_id: str
    message: str


@dataclass
class ApplyOperationsResult:
    """批量编辑操作的执行结果."""

    result: str
    errors: List[OperationError]


def is_mxcell_xml_complete(xml: Optional[str]) -> bool:
    """判断模型返回的 mxCell 片段是否已经完整闭合."""
    trimmed = (xml or "").strip()
    if not trimmed:
        return False

    last_self_close = trimmed.rfind("/>")
    last_mxcell_close = trimmed.rfind("</mxCell>")
    last_valid_end = max(last_self_close, last_mxcell_close)
    if last_valid_end < 0:
        return False

    end_offset = 9 if last_mxcell_close > last_self_close else 2
    suffix = trimmed[last_valid_end + end_offset :]
    return bool(re.fullmatch(r"(\s*</[^>]+>)*\s*", suffix))


def wrap_with_mxfile(xml: str) -> str:
    """把模型返回的 mxCell 片段包装成 draw.io 可打开的 mxfile."""
    if not xml or not xml.strip():
        return EMPTY_MXFILE

    raw = xml.strip()
    if "<mxfile" in raw:
        return ensure_drawio_root_cells(raw)
    if "<mxGraphModel" in raw:
        return ensure_drawio_root_cells(
            f'<mxfile><diagram name="Page-1" id="page-1">{raw}</diagram></mxfile>'
        )

    content = _strip_outer_root(raw)
    content = _strip_trailing_wrapper_tags(content)
    content = _strip_root_cells(content)
    return (
        '<mxfile><diagram name="Page-1" id="page-1"><mxGraphModel><root>'
        f'{ROOT_CELLS}{content}</root></mxGraphModel></diagram></mxfile>'
    )


def ensure_drawio_root_cells(xml: str) -> str:
    """确保完整 draw.io XML 内包含 id=0 和 id=1 两个基础 root cell."""
    document, root = _parse_document_and_root(xml)
    ids = {cell.attrib.get("id") for cell in root.findall("mxCell")}

    # draw.io 画布基础 cell 缺失时必须补齐，否则编辑器导入会失败
    if "0" not in ids:
        root.insert(0, ElementTree.Element("mxCell", {"id": "0"}))
    if "1" not in ids:
        insert_index = 1 if root.findall("mxCell") else 0
        root.insert(insert_index, ElementTree.Element("mxCell", {"id": "1", "parent": "0"}))
    return _serialize(document)


def validate_drawio_xml(xml: str) -> Optional[str]:
    """校验 draw.io XML 结构，返回 None 代表可用于编辑器渲染."""
    try:
        document, root = _parse_document_and_root(xml)
    except ValueError as exc:
        return str(exc)

    parent_map = {child: parent for parent in document.iter() for child in parent}
    for cell in document.iter("mxCell"):
        parent = parent_map.get(cell)
        if parent is not None and parent.tag == "mxCell":
            cell_id = cell.attrib.get("id") or "unknown"
            return f'Invalid XML: Found nested mxCell id="{cell_id}"'

    ids: Dict[str, int] = {}
    for cell in root.findall("mxCell"):
        cell_id = (cell.attrib.get("id") or "").strip()
        if not cell_id:
            return "Invalid XML: Found mxCell without id"
        ids[cell_id] = ids.get(cell_id, 0) + 1
    duplicates = [cell_id for cell_id, count in ids.items() if count > 1]
    if duplicates:
        return f"Invalid XML: Found duplicate id(s): {', '.join(duplicates[:5])}"
    if "0" not in ids or "1" not in ids:
        return 'Invalid XML: Missing draw.io root cells id="0" or id="1"'

    for cell in root.findall("mxCell"):
        cell_id = cell.attrib.get("id") or ""
        parent = cell.attrib.get("parent")
        if cell_id not in {"0", "1"} and parent and parent not in ids:
            return f'Invalid XML: Cell "{cell_id}" references missing parent "{parent}"'
        if cell.attrib.get("edge") == "1":
            for attr_name in ("source", "target"):
                ref = cell.attrib.get(attr_name)
                if ref and ref not in ids:
                    return f'Invalid XML: Edge "{cell_id}" references missing {attr_name} "{ref}"'

    return None


def apply_diagram_operations(xml_content: str, operations: List[Dict[str, Any]]) -> ApplyOperationsResult:
    """按开源项目的 ID 操作协议执行 update/add/delete."""
    try:
        normalized_xml = ensure_drawio_root_cells(xml_content)
        document, root = _parse_document_and_root(normalized_xml)
    except ValueError as exc:
        return ApplyOperationsResult(result=xml_content, errors=[OperationError("update", "", str(exc))])

    errors: List[OperationError] = []
    cell_map = _build_cell_map(root)

    for operation in operations:
        op_type = str(operation.get("operation") or "").strip().lower()
        cell_id = str(operation.get("cell_id") or operation.get("cellId") or "").strip()
        if op_type not in {"update", "add", "delete"}:
            errors.append(OperationError(op_type or "unknown", cell_id, "operation must be update/add/delete"))
            continue
        if not cell_id:
            errors.append(OperationError(op_type, "", "cell_id is required"))
            continue

        if op_type == "update":
            _apply_update(root, cell_map, cell_id, _get_new_xml(operation), errors)
        elif op_type == "add":
            _apply_add(root, cell_map, cell_id, _get_new_xml(operation), errors)
        else:
            _apply_delete(root, cell_map, cell_id, errors)

    result = _serialize(document)
    validation_error = validate_drawio_xml(result)
    if validation_error:
        errors.append(OperationError("validate", "", validation_error))
    return ApplyOperationsResult(result=result if not errors else xml_content, errors=errors)


def extract_root_cells_xml(xml: str, limit: int = 50000) -> str:
    """提取当前画布 root 下的 mxCell，供模型按 ID 精准编辑."""
    try:
        _, root = _parse_document_and_root(ensure_drawio_root_cells(xml))
    except ValueError:
        return (xml or "")[:limit]
    cells = [_serialize(cell) for cell in root.findall("mxCell") if cell.attrib.get("id") not in {"0", "1"}]
    return "\n".join(cells)[:limit]


def _apply_update(
    root: ElementTree.Element,
    cell_map: Dict[str, ElementTree.Element],
    cell_id: str,
    new_xml: Any,
    errors: List[OperationError],
) -> None:
    """替换现有 mxCell，要求 new_xml 内的 id 与 cell_id 完全一致."""
    existing_cell = cell_map.get(cell_id)
    if existing_cell is None:
        errors.append(OperationError("update", cell_id, f'Cell with id="{cell_id}" not found'))
        return
    if cell_id in {"0", "1"}:
        errors.append(OperationError("update", cell_id, "Cannot update draw.io root cell"))
        return

    new_cell, error = _parse_single_mxcell(new_xml)
    if error:
        errors.append(OperationError("update", cell_id, error))
        return
    if new_cell is None or new_cell.attrib.get("id") != cell_id:
        errors.append(OperationError("update", cell_id, "new_xml id must match cell_id"))
        return

    index = list(root).index(existing_cell)
    root.remove(existing_cell)
    root.insert(index, new_cell)
    cell_map[cell_id] = new_cell


def _apply_add(
    root: ElementTree.Element,
    cell_map: Dict[str, ElementTree.Element],
    cell_id: str,
    new_xml: Any,
    errors: List[OperationError],
) -> None:
    """新增 mxCell，要求 id 不与当前画布冲突."""
    if cell_id in cell_map:
        errors.append(OperationError("add", cell_id, f'Cell with id="{cell_id}" already exists'))
        return
    if cell_id in {"0", "1"}:
        errors.append(OperationError("add", cell_id, "Cannot add draw.io root cell"))
        return

    new_cell, error = _parse_single_mxcell(new_xml)
    if error:
        errors.append(OperationError("add", cell_id, error))
        return
    if new_cell is None or new_cell.attrib.get("id") != cell_id:
        errors.append(OperationError("add", cell_id, "new_xml id must match cell_id"))
        return

    root.append(new_cell)
    cell_map[cell_id] = new_cell


def _apply_delete(
    root: ElementTree.Element,
    cell_map: Dict[str, ElementTree.Element],
    cell_id: str,
    errors: List[OperationError],
) -> None:
    """删除目标 cell，并级联删除子节点和引用它的连线."""
    if cell_id in {"0", "1"}:
        errors.append(OperationError("delete", cell_id, "Cannot delete draw.io root cell"))
        return
    if cell_id not in cell_map:
        return

    to_delete = _collect_delete_ids(root.findall("mxCell"), cell_id)
    for delete_id in to_delete:
        cell = cell_map.get(delete_id)
        if cell is not None:
            root.remove(cell)
            cell_map.pop(delete_id, None)


def _collect_delete_ids(cells: Iterable[ElementTree.Element], target_id: str) -> List[str]:
    """按 parent/source/target 关系计算级联删除范围."""
    cell_list = list(cells)
    to_delete = {target_id}
    changed = True
    while changed:
        changed = False
        for cell in cell_list:
            cell_id = cell.attrib.get("id")
            if not cell_id or cell_id in {"0", "1"} or cell_id in to_delete:
                continue
            if (
                cell.attrib.get("parent") in to_delete
                or cell.attrib.get("source") in to_delete
                or cell.attrib.get("target") in to_delete
            ):
                to_delete.add(cell_id)
                changed = True
    return [cell.attrib["id"] for cell in cell_list if cell.attrib.get("id") in to_delete]


def _parse_single_mxcell(xml: Any) -> Tuple[Optional[ElementTree.Element], Optional[str]]:
    """解析操作里的完整 mxCell 元素."""
    if not isinstance(xml, str) or not xml.strip():
        return None, "new_xml is required"
    try:
        wrapper = ElementTree.fromstring(f"<wrapper>{xml.strip()}</wrapper>")
    except ElementTree.ParseError as exc:
        return None, f"new_xml parse error: {exc}"
    cells = [child for child in list(wrapper) if child.tag == "mxCell"]
    if len(cells) != 1:
        return None, "new_xml must contain exactly one mxCell"
    return cells[0], None


def _get_new_xml(operation: Dict[str, Any]) -> Any:
    """兼容模型返回的 snake_case 或 camelCase XML 字段."""
    return operation.get("new_xml") if "new_xml" in operation else operation.get("newXml")


def _parse_document_and_root(xml: str) -> Tuple[ElementTree.Element, ElementTree.Element]:
    """解析完整 draw.io XML，并定位 mxGraphModel/root."""
    try:
        document = ElementTree.fromstring((xml or "").strip())
    except ElementTree.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    root = next(document.iter("root"), None)
    if root is None:
        raise ValueError("Invalid XML: Could not find <root> element")
    return document, root


def _build_cell_map(root: ElementTree.Element) -> Dict[str, ElementTree.Element]:
    """构建 root 下 mxCell 的 ID 索引."""
    return {
        str(cell.attrib.get("id")): cell
        for cell in root.findall("mxCell")
        if cell.attrib.get("id")
    }


def _strip_outer_root(xml: str) -> str:
    """移除模型多余返回的 root 外壳."""
    text = xml.strip()
    if text.startswith("<root"):
        try:
            root = ElementTree.fromstring(text)
            return "".join(_serialize(child) for child in list(root))
        except ElementTree.ParseError:
            return re.sub(r"</?root[^>]*>", "", text).strip()
    return text


def _strip_trailing_wrapper_tags(xml: str) -> str:
    """去掉片段末尾多余的闭合包装标签."""
    last_self_close = xml.rfind("/>")
    last_mxcell_close = xml.rfind("</mxCell>")
    last_valid_end = max(last_self_close, last_mxcell_close)
    if last_valid_end < 0:
        return xml
    end_offset = 9 if last_mxcell_close > last_self_close else 2
    suffix = xml[last_valid_end + end_offset :]
    if re.fullmatch(r"(\s*</[^>]+>)*\s*", suffix):
        return xml[: last_valid_end + end_offset]
    return xml


def _strip_root_cells(xml: str) -> str:
    """避免模型返回 id=0/id=1 后与平台包装的 root cell 冲突."""
    return re.sub(
        r'<mxCell\b[^>]*\bid=["\'](?:0|1)["\'][^>]*(?:/>|>\s*</mxCell>)',
        "",
        xml,
        flags=re.IGNORECASE,
    ).strip()


def _serialize(element: ElementTree.Element) -> str:
    """序列化 XML 元素，统一短标签格式."""
    return ElementTree.tostring(element, encoding="unicode", short_empty_elements=True)
