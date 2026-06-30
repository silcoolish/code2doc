"""静态列表提供者 - 直接调用 MCP 工具获取列表项."""

import ast
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ListItem:
    """列表项."""

    name: str
    source_refs: List[Dict[str, Any]] = field(default_factory=list)


class StaticListProvider:
    """静态列表提供者.

    当 TemplateBlock 的 list_tool 属性有值时，直接调用对应的 MCP 工具
    获取列表项，无需经过 LLM 推理。
    """

    def __init__(self, mcp_client: MCPClient):
        self.mcp_client = mcp_client

    async def get_list_items(self, list_tool: str, repo_id: str) -> List[ListItem]:
        """获取列表项.

        Args:
            list_tool: 静态工具名称，支持 get_all_methods / get_all_classes / get_all_modules
            repo_id: 仓库ID

        Returns:
            列表项列表

        Raises:
            ValueError: 当工具名称未知或工具返回异常时
        """
        if list_tool == "get_all_methods":
            return await self._get_all_methods(repo_id)
        if list_tool == "get_all_classes":
            return await self._get_all_classes(repo_id)
        if list_tool == "get_all_modules":
            return await self._get_all_modules(repo_id)

        raise ValueError(f"Unknown list_tool: {list_tool}")

    async def _get_all_methods(self, repo_id: str) -> List[ListItem]:
        """获取所有方法节点."""
        return await self._get_all_nodes(
            repo_id,
            ["Method"],
            returns=[
                "node_id",
                "name",
                "node_type",
                "file_path",
                "start_line",
                "end_line",
            ],
        )

    async def _get_all_classes(self, repo_id: str) -> List[ListItem]:
        """获取所有类节点."""
        return await self._get_all_nodes(repo_id, ["Class"])

    async def _get_all_modules(self, repo_id: str) -> List[ListItem]:
        """获取所有模块节点."""
        return await self._get_all_nodes(repo_id, ["Module"])

    async def _get_all_nodes(
        self,
        repo_id: str,
        node_types: List[str],
        returns: Optional[List[str]] = None,
    ) -> List[ListItem]:
        """调用 get_all_nodes 工具获取节点列表.

        Args:
            repo_id: 仓库ID
            node_types: 节点类型列表，枚举值: File, Class, Method, Module, Workflow, Directory

        Returns:
            列表项列表，每项包含节点名称和节点ID(source_refs)
        """
        payload: Dict[str, Any] = {"repo_id": repo_id, "node_types": node_types}
        if returns:
            payload["returns"] = returns

        tool_result = await self.mcp_client.call_tool("get_all_nodes", payload)

        data = self._parse_tool_result(tool_result)
        nodes = data.get("nodes", [])

        items = []
        for node in nodes:
            node_id = node.get("node_id", "")
            name = node.get("name", "")
            file_path = node.get("file_path", "")
            if name:
                item_name = self._build_item_name(name, file_path, node_types)
                source_ref = self._build_source_ref(
                    node_id,
                    name,
                    file_path,
                    node_types,
                    node.get("start_line"),
                    node.get("end_line"),
                )
                items.append(ListItem(name=item_name, source_refs=[source_ref] if source_ref else []))

        logger.info(
            "static_list_get_all_nodes",
            repo_id=repo_id,
            node_types=node_types,
            count=len(items),
        )

        return items

    @staticmethod
    def _build_item_name(name: str, file_path: str, node_types: List[str]) -> str:
        """构建列表项标题，Method 节点附带文件路径避免同名函数歧义."""
        if "Method" in node_types and file_path:
            return f"{name}（{file_path}）"
        return name

    @staticmethod
    def _build_source_ref(
        node_id: str,
        name: str,
        file_path: str,
        node_types: List[str],
        start_line: Any = None,
        end_line: Any = None,
    ) -> Dict[str, Any]:
        """构建 workspace sourceRefs 兼容的源码引用."""
        if not node_id:
            return {}
        source_ref: Dict[str, Any] = {
            "sourceId": node_id,
            "symbolName": name,
        }
        if node_types:
            source_ref["symbolType"] = node_types[0]
        if file_path:
            source_ref["filePath"] = file_path
        if node_types and node_types[0] == "Method":
            start = StaticListProvider._to_positive_int(start_line)
            end = StaticListProvider._to_positive_int(end_line)
            if start is not None:
                source_ref["lineStart"] = start
                source_ref["lineEnd"] = end if end is not None else start
        return source_ref

    @staticmethod
    def _to_positive_int(value: Any) -> Optional[int]:
        """转换源码行号，非法值保持缺省."""
        try:
            line = int(value)
        except (TypeError, ValueError):
            return None
        return line if line > 0 else None

    def _parse_tool_result(self, tool_result: str) -> Dict[str, Any]:
        """解析工具返回结果.

        先尝试按 JSON 解析，失败则回退到 Python 字面量解析.

        Args:
            tool_result: 工具返回的原始字符串

        Returns:
            解析后的字典

        Raises:
            ValueError: 当两种解析方式都失败时
        """
        try:
            return json.loads(tool_result)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(tool_result)
            except (ValueError, SyntaxError) as e:
                raise ValueError(
                    f"Cannot parse tool result: {tool_result[:200]}"
                ) from e
