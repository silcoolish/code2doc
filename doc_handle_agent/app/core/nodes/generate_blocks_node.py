"""内容生成节点."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from json_repair import repair_json

from app.domain.content_generator import ContentGenerator
from app.core.nodes.base import WorkflowNode
from app.core.state import AgentState, GenerationStatus
from app.domain.document_caption import normalize_document_caption
from app.domain.model import TemplateBlock, DocumentBlock
from app.utils.logger import get_logger
from app.utils.timing import log_timing

logger = get_logger(__name__)


class GenerateBlocksNode(WorkflowNode):
    """生成内容块节点.

    根据state中选定的策略，执行内容生成，
    更新block内容并构建doc_blocks。
    """

    def __init__(self, content_generator: ContentGenerator):
        self.content_generator = content_generator

    @property
    def name(self) -> str:
        return "generate_blocks"

    async def execute(self, state: AgentState) -> AgentState:
        """生成所有block的内容.

        1. 从state读取选中的策略和blocks
        2. 执行策略生成内容
        3. 更新block的content_text和source信息
        4. 构建doc_blocks
        """
        if state.get("error"):
            return state

        blocks: List[TemplateBlock] = state.get("blocks", [])
        if not blocks:
            return state

        strategy_name = state.get("selected_strategy") or "batched_generation"

        try:
            state["status"] = GenerationStatus.GENERATING.value

            reporter = state.get("__progress_reporter")
            if reporter:
                await reporter.report_percent(
                    0, f"正在使用 {strategy_name} 策略生成内容..."
                )

                def on_progress(current: int, total: int):
                    asyncio.create_task(
                        reporter.report_step(
                            current,
                            total,
                            f"正在生成第 {current}/{total} 个内容块...",
                        )
                    )

                with log_timing(
                    "generate_blocks", strategy=strategy_name, total_blocks=len(blocks)
                ):
                    results = await self.content_generator.execute_strategy(
                        strategy_name=strategy_name,
                        blocks=blocks,
                        repo_id=state["repo_id"],
                        on_progress=on_progress,
                    )

                await reporter.report_percent(100, "内容生成完成")
            else:
                state["message"] = f"正在使用 {strategy_name} 策略生成内容..."

                with log_timing(
                    "generate_blocks", strategy=strategy_name, total_blocks=len(blocks)
                ):
                    results = await self.content_generator.execute_strategy(
                        strategy_name=strategy_name,
                        blocks=blocks,
                        repo_id=state["repo_id"],
                    )

            # 构建文档blocks
            doc_blocks = self._build_document_blocks(blocks, results)
            state["doc_blocks"] = doc_blocks

            logger.info(
                "generate_blocks_complete",
                strategy=strategy_name,
                total_blocks=len(blocks),
                result_count=len(results),
            )

        except Exception as e:
            logger.error(
                "generate_blocks_failed",
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            state["error"] = str(e)
            state["status"] = GenerationStatus.FAILED.value
            state["message"] = f"内容生成失败: {str(e)}"

        return state

    def _build_document_blocks(
        self,
        blocks: List[TemplateBlock],
        results: List[DocumentBlock],
    ) -> List[dict]:
        """构建文档blocks.

        用生成结果更新block内容后，整合到block结构中，字段对齐 workspace DocumentBlockPayload。
        """
        # 用生成结果更新block内容
        for result in results:
            if not result.block_id:
                continue
            block = next((b for b in blocks if b.id == result.block_id), None)
            if block:
                if result.source_refs:
                    block.source_refs = result.source_refs
                generated_caption = normalize_document_caption(
                    result.caption,
                    self._resolve_output_block_type(block),
                )
                existing_caption = block.attrs.get("caption")
                if (
                    generated_caption
                    and not (isinstance(existing_caption, str) and existing_caption.strip())
                    and (
                        block.is_table
                        or block.is_image_block
                        or block.is_mermaid
                        or block.is_drawio_architecture
                    )
                ):
                    block.attrs["caption"] = generated_caption
                if block.is_table:
                    # 静态表格已经有结构化 attrs.table，这里只保留展示文本，避免把摘要文案再当 JSON 解析
                    if not block.is_template and isinstance(block.attrs.get("table"), dict):
                        block.content_text = str(result.text_content or block.content_text or "")
                        continue
                    table_data = self._build_generated_table(block, result.text_content)
                    if table_data:
                        block.attrs["table"] = table_data
                        block.content_text = json.dumps(table_data, ensure_ascii=False)
                    else:
                        block.content_text = str(result.text_content or "")
                        logger.warning(
                            "table_content_parse_failed",
                            block_id=block.id,
                            content=str(result.text_content or "")[:200],
                        )
                else:
                    block.content_text = result.text_content

        doc_blocks: List[dict] = []

        for block in blocks:
            block_data = {
                "id": block.id,
                "parentBlockId": block.parent_block_id,
                "blockType": self._resolve_output_block_type(block),
                "headingLevel": block.heading_level,
                "orderNo": block.order_no,
                "contentText": block.content_text,
                "blockStyle": block.block_style,
                "inlineStyles": block.inline_styles,
                "attrs": block.attrs,
                "sourceRefs": block.source_refs,
            }
            doc_blocks.append(block_data)

        return doc_blocks

    @staticmethod
    def _resolve_output_block_type(block: TemplateBlock) -> str:
        if block.is_drawio_architecture:
            return "image"
        if block.is_mermaid:
            return "mermaid"
        return block.block_type

    def _build_generated_table(
        self,
        block: TemplateBlock,
        generated_content: Any,
    ) -> Optional[Dict[str, Any]]:
        """将模型生成的轻量表格行数据装配成标准表格结构"""
        payload = self._parse_generated_table_payload(generated_content)
        if payload is None:
            return None

        template_table = block.attrs.get("table")
        table = template_table if isinstance(template_table, dict) else {}
        schema_source = block.table_schema if isinstance(block.table_schema, dict) else {}

        rows_source = self._read_generated_table_rows(payload)
        columns = self._build_table_columns(
            self._first_list(
                table.get("columns"),
                schema_source.get("columns"),
                payload.get("columns") if isinstance(payload, dict) else None,
            ),
            rows_source,
        )
        if not columns:
            return None

        rows = self._build_table_rows(rows_source, columns)
        return {
            "columns": columns,
            "rows": rows,
            "headerRow": self._read_bool(
                table.get("headerRow"),
                table.get("header_row"),
                schema_source.get("headerRow"),
                schema_source.get("header_row"),
                payload.get("headerRow") if isinstance(payload, dict) else None,
                payload.get("header_row") if isinstance(payload, dict) else None,
                block.attrs.get("headerRow"),
                block.attrs.get("header_row"),
                default=False,
            ),
            "headerColumn": self._read_bool(
                table.get("headerColumn"),
                table.get("header_column"),
                schema_source.get("headerColumn"),
                schema_source.get("header_column"),
                payload.get("headerColumn") if isinstance(payload, dict) else None,
                payload.get("header_column") if isinstance(payload, dict) else None,
                block.attrs.get("headerColumn"),
                block.attrs.get("header_column"),
                default=False,
            ),
        }

    def _parse_generated_table_payload(self, content: Any) -> Optional[Any]:
        """解析表格生成结果"""
        if isinstance(content, (dict, list)):
            return content
        if not isinstance(content, str) or not content.strip():
            return None
        raw_content = content.strip()
        if raw_content[0] not in {'{', '['}:
            return None
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            try:
                return json.loads(repair_json(raw_content))
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _first_list(*values: Any) -> List[Any]:
        """返回第一个列表值"""
        for value in values:
            if isinstance(value, list):
                return value
        return []

    def _read_generated_table_rows(self, payload: Any) -> List[Any]:
        """从模型结果中提取行数组"""
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        return self._first_list(
            payload.get("rows"),
            payload.get("tableRows"),
            payload.get("table_rows"),
            payload.get("data"),
        )

    def _build_table_columns(
        self,
        columns_source: List[Any],
        rows_source: List[Any],
    ) -> List[Dict[str, Any]]:
        """构建列定义，优先保留模板列的宽度和样式"""
        columns: List[Dict[str, Any]] = []
        for index, column in enumerate(columns_source):
            column_id = f"col-{index + 1}"
            column_record: Dict[str, Any] = {"id": column_id, "label": ""}
            if isinstance(column, str):
                column_record["label"] = column
            elif isinstance(column, dict):
                # 先保留模板列上的现有属性，再把 id 和 label 收口成统一字段
                column_record.update(column)
                column_record["id"] = str(column.get("id") or column.get("key") or column_id)
                column_record["label"] = str(
                    column.get("label")
                    or column.get("title")
                    or column.get("name")
                    or ""
                )
            columns.append(column_record)

        if columns:
            return columns

        inferred_count = self._guess_column_count(rows_source)
        return [
            {"id": f"col-{index + 1}", "label": ""}
            for index in range(inferred_count)
        ]

    @staticmethod
    def _guess_column_count(rows_source: List[Any]) -> int:
        """根据生成行推断列数"""
        inferred_count = 0
        for row in rows_source:
            if isinstance(row, list):
                inferred_count = max(inferred_count, len(row))
            elif isinstance(row, dict):
                cells = row.get("cells")
                if isinstance(cells, dict):
                    inferred_count = max(inferred_count, len(cells))
                elif isinstance(cells, list):
                    inferred_count = max(inferred_count, len(cells))
                else:
                    inferred_count = max(inferred_count, len(row))
        return inferred_count

    def _build_table_rows(
        self,
        rows_source: List[Any],
        columns: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """按列定义补齐每一行的 cells"""
        rows: List[Dict[str, Any]] = []
        for row_index, row in enumerate(rows_source):
            row_id = f"row-{row_index + 1}"
            values = self._read_row_values(row, columns)
            cells: Dict[str, Dict[str, Any]] = {}
            for column_index, column in enumerate(columns):
                column_id = str(column["id"])
                # 后续前端编辑和导出都按 column.id 取值，这里统一补齐缺失单元格
                cells[column_id] = {"text": self._read_cell_text(values[column_index] if column_index < len(values) else "")}
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                row_id = row["id"]
            rows.append({"id": row_id, "cells": cells})
        return rows

    def _read_row_values(
        self,
        row: Any,
        columns: List[Dict[str, Any]],
    ) -> List[Any]:
        """解析一行中的单元格值"""
        if isinstance(row, list):
            return row
        if not isinstance(row, dict):
            return [row]

        cells = row.get("cells")
        if isinstance(cells, list):
            return cells
        if isinstance(cells, dict):
            # 优先按列 id 取值，拿不到再尝试列标题，兼容人工调整后的返回
            return [
                self._read_mapping_value(
                    cells,
                    column.get("id"),
                    column.get("label"),
                )
                for column in columns
            ]

        values = self._first_list(row.get("values"), row.get("columns"))
        if values:
            return values

        return [
            self._read_mapping_value(
                row,
                column.get("id"),
                column.get("label"),
                str(index),
            )
            for index, column in enumerate(columns)
        ]

    @staticmethod
    def _read_mapping_value(mapping: Dict[str, Any], *keys: Any) -> Any:
        """按键顺序读取映射值，保留 0 和 False 这类合法单元格内容"""
        for key in keys:
            if not isinstance(key, str) or not key:
                continue
            if key in mapping:
                return mapping[key]
        return ""

    @staticmethod
    def _read_cell_text(value: Any) -> str:
        """提取单元格纯文本"""
        if value is None:
            return ""
        if isinstance(value, dict):
            text = value.get("text")
            if text is not None:
                return str(text)
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _read_bool(*values: Any, default: bool) -> bool:
        """解析布尔配置"""
        for value in values:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
        return default
