"""基于 Tree-sitter 的代码分析器基类.

提供通用的 Tree-sitter 解析基础设施，语言特定分析器继承此类。
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from tree_sitter import Language, Parser, Node, Query

# 尝试导入 QueryCursor（tree-sitter 0.22+）
try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None

from app.domain.analyzer.code_analyzer import (
    CodeAnalyzer,
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class BaseTreeSitterAnalyzer(CodeAnalyzer):
    """基于 Tree-sitter 的代码分析器基类.

    子类需要设置 language 和 queries 属性。
    """

    # 子类需要覆盖这些属性
    language: Optional[Language] = None
    queries: Dict[str, str] = {}

    def __init__(self):
        """初始化解析器."""
        self.parser = Parser(self.language) if self.language else None

    # ==================== Tree-sitter 基础设施 ====================

    def _parse_tree(self, content: str) -> Optional[Any]:
        """解析代码为 AST.

        Args:
            content: 代码内容

        Returns:
            解析树或 None
        """
        if self.parser is None:
            return None
        try:
            return self.parser.parse(bytes(content, "utf8"))
        except Exception as e:
            logger.warning(f"Failed to parse tree: {e}")
            return None

    def _exec_query(
        self,
        query_str: str,
        node: Node,
    ) -> List[Tuple[Node, str]]:
        """执行 Tree-sitter 查询.

        Args:
            query_str: 查询字符串
            node: 要查询的节点

        Returns:
            节点和捕获名称的列表
        """
        if self.language is None:
            return []

        try:
            query = Query(self.language, query_str)

            # 优先尝试新版 API (tree-sitter 0.22+)
            if hasattr(query, 'captures'):
                captures = query.captures(node)
                return self._process_captures(captures)

            # 旧版 API 使用 QueryCursor
            if QueryCursor is not None:
                cursor = QueryCursor(query)
                captures = cursor.captures(node)
                return self._process_captures(captures)

            logger.warning("无法执行查询: tree-sitter API 不兼容")
            return []

        except Exception as e:
            logger.warning(f"Query execution failed: {e}")
            return []

    def _process_captures(self, captures: dict) -> List[Tuple[Node, str]]:
        """处理新版本的 captures 返回格式.

        Args:
            captures: tree-sitter QueryCursor.captures() 返回的字典

        Returns:
            节点和捕获名称的列表
        """
        result = []
        for capture_name, nodes in captures.items():
            for node in nodes:
                result.append((node, capture_name))
        return result

    def _node_contains(self, parent: Node, child: Node) -> bool:
        """检查父节点是否包含子节点.

        Args:
            parent: 父节点
            child: 子节点

        Returns:
            是否包含
        """
        return (
            parent.start_byte <= child.start_byte
            and parent.end_byte >= child.end_byte
        )

    def _node_text(self, node: Node, content: str) -> str:
        """获取节点的文本内容.

        Args:
            node: 节点
            content: 原始内容

        Returns:
            节点文本
        """
        return content[node.start_byte:node.end_byte]

    def _get_node_line(self, node: Node) -> int:
        """获取节点的行号（1-based）.

        Args:
            node: 节点

        Returns:
            行号
        """
        return node.start_point[0] + 1

    # ==================== 子类可覆盖的辅助方法 ====================

    def _extract_symbol_text(
        self,
        node: Node,
        content: str,
        capture_name: str,
    ) -> Optional[str]:
        """从查询结果中提取指定捕获的文本.

        Args:
            node: 查询的根节点
            content: 原始内容
            capture_name: 捕获名称（如 'class.name'）

        Returns:
            捕获的文本或 None
        """
        query_str = self.queries.get(capture_name.split('.')[0])
        if not query_str:
            return None

        captures = self._exec_query(query_str, node)
        for cap_node, cap_name in captures:
            if cap_name == capture_name:
                return self._node_text(cap_node, content)
        return None

    def _find_captures(
        self,
        captures: List[Tuple[Node, str]],
        pattern: str,
    ) -> List[Node]:
        """从捕获结果中查找匹配的节点.

        Args:
            captures: 捕获列表
            pattern: 匹配模式（如 'class.name'）

        Returns:
            匹配的节点列表
        """
        return [node for node, name in captures if pattern in name]

    # ==================== 抽象方法的默认实现 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """默认实现：子类应覆盖此方法."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement parse_for_structure"
        )

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """默认实现：子类应覆盖此方法."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement extract_imports"
        )

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """默认实现：子类应覆盖此方法."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement extract_method_calls"
        )
