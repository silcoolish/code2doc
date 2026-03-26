"""Java 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_java as tsjava
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class JavaAnalyzer(BaseTreeSitterAnalyzer):
    """Java 代码分析器."""

    language = Language(tsjava.language())

    QUERIES = {
        "class": """
            (class_declaration
                name: (identifier) @class.name
                body: (class_body) @class.body
            ) @class.def
        """,
        "interface": """
            (interface_declaration
                name: (identifier) @interface.name
            ) @interface.def
        """,
        "method": """
            (method_declaration
                name: (identifier) @method.name
                body: (block)? @method.body
            ) @method.def
        """,
        "constructor": """
            (constructor_declaration
                name: (identifier) @ctor.name
            ) @ctor.def
        """,
        "import": """
            (import_declaration
                (scoped_identifier) @import.name
            ) @import.def
        """,
        "call": """
            (method_invocation
                name: (identifier) @call.name
            ) @call.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".java"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "java"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 Java 代码，提取类和方法定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse Java code",
            )

        root_node = tree.root_node
        classes: List[ParsedSymbol] = []
        methods: List[ParsedSymbol] = []

        # 提取类
        class_captures = self._exec_query(self.QUERIES["class"], root_node)
        class_nodes = self._group_captures(class_captures, "class")

        for class_node, info in class_nodes.items():
            class_name = info.get("name", "Unknown")
            class_code = self._node_text(class_node, content)

            # 提取类中的方法
            class_methods = self._extract_methods_in_class(class_node, content, class_name)

            class_symbol = ParsedSymbol(
                name=class_name,
                symbol_type="class",
                start_line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                code=class_code,
            )
            classes.append(class_symbol)
            methods.extend(class_methods)

        # 提取接口
        interface_captures = self._exec_query(self.QUERIES["interface"], root_node)
        interface_nodes = self._group_captures(interface_captures, "interface")

        for interface_node, info in interface_nodes.items():
            interface_name = info.get("name", "Unknown")
            interface_code = self._node_text(interface_node, content)

            interface_symbol = ParsedSymbol(
                name=interface_name,
                symbol_type="interface",
                start_line=interface_node.start_point[0] + 1,
                end_line=interface_node.end_point[0] + 1,
                code=interface_code,
            )
            classes.append(interface_symbol)  # 接口作为类处理

        return StructureParseResult(
            file_path=file_path,
            language=self.language_name,
            classes=classes,
            methods=methods,
            success=True,
        )

    def _group_captures(
        self,
        captures: List[Tuple[Node, str]],
        prefix: str,
    ) -> dict:
        """将查询结果按定义分组."""
        defs = {}
        for node, capture_name in captures:
            if f"{prefix}.def" in capture_name:
                defs[node] = {"node": node}
            elif f"{prefix}.name" in capture_name:
                for def_node in defs:
                    if self._node_contains(def_node, node):
                        defs[def_node]["name"] = node.text.decode("utf8") if node.text else ""
                        break
        return defs

    def _extract_methods_in_class(
        self,
        class_node: Node,
        content: str,
        class_name: str,
    ) -> List[ParsedSymbol]:
        """提取类中的方法."""
        methods: List[ParsedSymbol] = []

        method_captures = self._exec_query(self.QUERIES["method"], class_node)
        method_nodes = self._group_captures(method_captures, "method")

        for method_node, info in method_nodes.items():
            method_name = info.get("name", "Unknown")
            method_code = self._node_text(method_node, content)

            method_symbol = ParsedSymbol(
                name=method_name,
                symbol_type="method",
                start_line=method_node.start_point[0] + 1,
                end_line=method_node.end_point[0] + 1,
                code=method_code,
                parent_name=class_name,
            )
            methods.append(method_symbol)

        return methods

    # ==================== 依赖图构建阶段 - Import 提取 ====================

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从 Java 代码中提取 import 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_imports_regex(content)

        root_node = tree.root_node
        import_captures = self._exec_query(self.QUERIES["import"], root_node)

        for node, capture_name in import_captures:
            if "import.name" in capture_name:
                import_text = node.text.decode("utf8") if node.text else ""
                line_number = self._get_node_line(node)

                # 解析 import 语句
                import_info = self._parse_import_statement(import_text, line_number)
                if import_info:
                    imports.append(import_info)

        return imports

    def _parse_import_statement(
        self,
        import_text: str,
        line_number: int,
    ) -> Optional[ImportInfo]:
        """解析 Java import 语句."""
        # 处理 import x.y.z 或 import static x.y.z
        match = re.match(r"(?:static\s+)?([\w.]+(?:\.\*)?)", import_text)
        if match:
            return ImportInfo(
                module=match.group(1),
                line_number=line_number,
            )
        return None

    def _extract_imports_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 import（作为回退）."""
        imports: List[ImportInfo] = []

        for match in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)", content, re.MULTILINE):
            imports.append(ImportInfo(module=match.group(1)))

        return imports

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 Java 方法代码中提取方法调用."""
        calls: List[MethodCallInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_calls_regex(content, method_name)

        root_node = tree.root_node
        call_captures = self._exec_query(self.QUERIES["call"], root_node)

        seen: set = set()
        for node, capture_name in call_captures:
            if "call.name" in capture_name:
                method_name_found = node.text.decode("utf8") if node.text else ""
                line_number = self._get_node_line(node)

                if method_name_found and method_name_found != method_name:
                    key = (method_name_found, line_number)
                    if key not in seen:
                        seen.add(key)
                        calls.append(MethodCallInfo(
                            method_name=method_name_found,
                            line_number=line_number,
                        ))

        return calls

    def _extract_calls_regex(
        self,
        content: str,
        method_name: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """使用正则表达式提取方法调用."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        # 匹配 method() 或 obj.method()
        pattern = r"(?<!\w)([a-zA-Z_]\w*)\s*\("
        for match in re.finditer(pattern, content):
            name = match.group(1)
            if name == method_name:
                continue
            if name in self._get_excluded_names():
                continue

            key = (name, match.start())
            if key not in seen:
                seen.add(key)
                calls.append(MethodCallInfo(method_name=name))

        return calls

    def _get_excluded_names(self) -> set:
        """获取需要排除的关键字."""
        return {
            "if", "while", "for", "switch", "catch", "return",
            "new", "sizeof", "typeof", "instanceof",
            "synchronized", "assert",
        }
