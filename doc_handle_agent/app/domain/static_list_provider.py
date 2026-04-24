"""静态列表提供者 - 直接调用 MCP 工具获取列表项."""

import ast
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ListItem:
    """列表项."""

    name: str
    source_refs: List[str] = field(default_factory=list)


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
        return await self._get_all_nodes(repo_id, ["Method"])

    async def _get_all_classes(self, repo_id: str) -> List[ListItem]:
        """获取所有类节点."""
        return await self._get_all_nodes(repo_id, ["Class"])

    async def _get_all_modules(self, repo_id: str) -> List[ListItem]:
        """获取所有模块节点."""
        return await self._get_all_nodes(repo_id, ["Module"])

    async def _get_all_nodes(
        self, repo_id: str, node_types: List[str]
    ) -> List[ListItem]:
        """调用 get_all_nodes 工具获取节点列表.

        Args:
            repo_id: 仓库ID
            node_types: 节点类型列表，枚举值: File, Class, Method, Module, Workflow, Directory

        Returns:
            列表项列表，每项包含节点名称和节点ID(source_refs)
        """
        tool_result = await self.mcp_client.call_tool(
            "get_all_nodes",
            {"repo_id": repo_id, "node_types": node_types},
        )

        data = self._parse_tool_result(tool_result)
        nodes = data.get("nodes", [])

        items = []
        for node in nodes:
            node_id = node.get("node_id", "")
            name = node.get("name", "")
            if name:
                items.append(ListItem(name=name, source_refs=[node_id] if node_id else []))

        logger.info(
            "static_list_get_all_nodes",
            repo_id=repo_id,
            node_types=node_types,
            count=len(items),
        )

        return items

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
