"""JavaScript/TypeScript 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class JavaScriptAnalyzer(BaseTreeSitterAnalyzer):
    """JavaScript 代码分析器."""

    language = Language(tsjavascript.language())

    QUERIES = {
        "class": """
            (class_declaration
                name: (identifier) @class.name
                body: (class_body) @class.body
            ) @class.def
        """,
        "function": """
            (function_declaration
                name: (identifier) @function.name
                body: (statement_block) @function.body
            ) @function.def
        """,
        "arrow_function": """
            (lexical_declaration
                (variable_declarator
                    name: (identifier) @function.name
                    value: (arrow_function) @function.body
                )
            ) @function.def
        """,
        "method": """
            (method_definition
                name: (property_identifier) @method.name
                body: (statement_block) @method.body
            ) @method.def
        """,
        "import": """
            (import_statement
                source: (string) @import.source
            ) @import.def
            (import_statement
                (import_clause) @import.clause
                source: (string) @import.source
            ) @import.def
        """,
        "require": """
            (call_expression
                function: (identifier) @require.name (#eq? @require.name "require")
                arguments: (arguments (string) @require.source)
            ) @require.def
        """,
        "call": """
            (call_expression
                function: (identifier) @call.name
            ) @call.def
            (call_expression
                function: (member_expression
                    object: (identifier) @call.object
                    property: (property_identifier) @call.property
                )
            ) @call.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".js", ".jsx", ".mjs"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "javascript"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 JavaScript 代码，提取类和函数定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse JavaScript code",
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

            class_symbol = ParsedSymbol(
                name=class_name,
                symbol_type="class",
                start_line=class_node.start_point[0] + 1,
                end_line=class_node.end_point[0] + 1,
                code=class_code,
            )
            classes.append(class_symbol)

            # 提取类方法
            class_methods = self._extract_methods_in_class(class_node, content, class_name)
            methods.extend(class_methods)

        # 提取独立函数
        function_captures = self._exec_query(self.QUERIES["function"], root_node)
        func_nodes = self._group_captures(function_captures, "function")

        for func_node, info in func_nodes.items():
            func_name = info.get("name", "Unknown")
            func_code = self._node_text(func_node, content)

            method_symbol = ParsedSymbol(
                name=func_name,
                symbol_type="function",
                start_line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                code=func_code,
            )
            methods.append(method_symbol)

        # 提取箭头函数
        arrow_captures = self._exec_query(self.QUERIES["arrow_function"], root_node)
        arrow_nodes = self._group_captures(arrow_captures, "function")

        for arrow_node, info in arrow_nodes.items():
            func_name = info.get("name", "Unknown")
            func_code = self._node_text(arrow_node, content)

            method_symbol = ParsedSymbol(
                name=func_name,
                symbol_type="function",
                start_line=arrow_node.start_point[0] + 1,
                end_line=arrow_node.end_point[0] + 1,
                code=func_code,
            )
            methods.append(method_symbol)

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
        """从 JavaScript 代码中提取 import/require 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_imports_regex(content)

        root_node = tree.root_node

        # ES6 import
        import_captures = self._exec_query(self.QUERIES["import"], root_node)
        for node, capture_name in import_captures:
            if "import.source" in capture_name:
                source_text = node.text.decode("utf8") if node.text else ""
                source = source_text.strip("'\"")
                line_number = self._get_node_line(node)
                imports.append(ImportInfo(
                    module=source,
                    line_number=line_number,
                ))

        # CommonJS require
        require_captures = self._exec_query(self.QUERIES["require"], root_node)
        for node, capture_name in require_captures:
            if "require.source" in capture_name:
                source_text = node.text.decode("utf8") if node.text else ""
                source = source_text.strip("'\"")
                line_number = self._get_node_line(node)
                imports.append(ImportInfo(
                    module=source,
                    line_number=line_number,
                ))

        return imports

    def _extract_imports_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 import."""
        imports: List[ImportInfo] = []

        # ES6 import
        for match in re.finditer(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", content):
            imports.append(ImportInfo(module=match.group(1)))

        # require()
        for match in re.finditer(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            imports.append(ImportInfo(module=match.group(1)))

        return imports

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 JavaScript 代码中提取方法调用."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_calls_regex(content, method_name)

        root_node = tree.root_node
        call_captures = self._exec_query(self.QUERIES["call"], root_node)

        for node, capture_name in call_captures:
            line_number = self._get_node_line(node)

            if "call.property" in capture_name:
                # obj.method() 形式
                property_name = node.text.decode("utf8") if node.text else ""
                # 查找对应的 object
                for obj_node, obj_name in call_captures:
                    if "call.object" in obj_name:
                        object_name = obj_node.text.decode("utf8") if obj_node.text else ""
                        if property_name and property_name != method_name:
                            key = (property_name, line_number)
                            if key not in seen:
                                seen.add(key)
                                calls.append(MethodCallInfo(
                                    method_name=property_name,
                                    receiver=object_name,
                                    line_number=line_number,
                                ))
                        break
            elif "call.name" in capture_name:
                # method() 形式
                func_name = node.text.decode("utf8") if node.text else ""
                if func_name and func_name != method_name and func_name not in self._get_excluded_names():
                    key = (func_name, line_number)
                    if key not in seen:
                        seen.add(key)
                        calls.append(MethodCallInfo(
                            method_name=func_name,
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
            "typeof", "instanceof", "void", "delete", "new",
            "require", "console",
        }


class TypeScriptAnalyzer(JavaScriptAnalyzer):
    """TypeScript 代码分析器."""

    language = Language(tstypescript.language_typescript())

    # TypeScript 扩展查询
    QUERIES = {
        **JavaScriptAnalyzer.QUERIES,
        "interface": """
            (interface_declaration
                name: (type_identifier) @interface.name
            ) @interface.def
        """,
        "type_alias": """
            (type_alias_declaration
                name: (type_identifier) @type.name
            ) @type.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".ts", ".tsx"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "typescript"

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 TypeScript 代码，包含接口和类型别名."""
        result = super().parse_for_structure(file_path, content)

        # TypeScript 特有：提取接口和类型别名
        tree = self._parse_tree(content)
        if tree:
            root_node = tree.root_node

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
                result.classes.append(interface_symbol)

        return result
