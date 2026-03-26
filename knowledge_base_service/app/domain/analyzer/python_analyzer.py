"""Python 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_python as tspython
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class PythonAnalyzer(BaseTreeSitterAnalyzer):
    """Python 代码分析器."""

    language = Language(tspython.language())

    # Tree-sitter 查询定义
    QUERIES = {
        "class": """
            (class_definition
                name: (identifier) @class.name
                body: (block) @class.body
            ) @class.def
        """,
        "function": """
            (function_definition
                name: (identifier) @function.name
                body: (block) @function.body
            ) @function.def
        """,
        "import": """
            (import_statement
                name: (dotted_name) @import.name
            ) @import.def
            (import_from_statement
                module_name: (dotted_name)? @import.module
                name: (dotted_name) @import.name
            ) @import.def
        """,
        "call": """
            (call
                function: (identifier) @call.name
            ) @call.def
            (call
                function: (attribute
                    object: (identifier) @call.object
                    attribute: (identifier) @call.attribute
                )
            ) @call.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".py", ".pyi"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "python"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 Python 代码，提取类和函数定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse Python code",
            )

        root_node = tree.root_node
        classes: List[ParsedSymbol] = []
        methods: List[ParsedSymbol] = []

        # 提取类
        class_captures = self._exec_query(self.QUERIES["class"], root_node)
        class_nodes = self._group_class_captures(class_captures)

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

        # 提取独立函数
        function_captures = self._exec_query(self.QUERIES["function"], root_node)
        func_nodes = self._group_function_captures(function_captures)

        for func_node, info in func_nodes.items():
            # 检查是否在类中
            if self._is_in_any_class(func_node, list(class_nodes.keys())):
                continue

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

        return StructureParseResult(
            file_path=file_path,
            language=self.language_name,
            classes=classes,
            methods=methods,
            success=True,
        )

    def _group_class_captures(
        self,
        captures: List[Tuple[Node, str]],
    ) -> dict:
        """将类查询结果按类定义分组."""
        class_defs = {}
        for node, capture_name in captures:
            if "class.def" in capture_name:
                class_defs[node] = {"node": node}
            elif "class.name" in capture_name:
                for class_node in class_defs:
                    if self._node_contains(class_node, node):
                        class_defs[class_node]["name"] = node.text.decode("utf8") if node.text else ""
                        break
        return class_defs

    def _group_function_captures(
        self,
        captures: List[Tuple[Node, str]],
    ) -> dict:
        """将函数查询结果按函数定义分组."""
        func_defs = {}
        for node, capture_name in captures:
            if "function.def" in capture_name or "func.def" in capture_name:
                func_defs[node] = {"node": node}
            elif "function.name" in capture_name or "func.name" in capture_name:
                for func_node in func_defs:
                    if self._node_contains(func_node, node):
                        func_defs[func_node]["name"] = node.text.decode("utf8") if node.text else ""
                        break
        return func_defs

    def _extract_methods_in_class(
        self,
        class_node: Node,
        content: str,
        class_name: str,
    ) -> List[ParsedSymbol]:
        """提取类中的方法."""
        methods: List[ParsedSymbol] = []

        function_captures = self._exec_query(self.QUERIES["function"], class_node)
        func_nodes = self._group_function_captures(function_captures)

        for func_node, info in func_nodes.items():
            # 确保方法在类节点内
            if not self._node_contains(class_node, func_node):
                continue

            func_name = info.get("name", "Unknown")
            func_code = self._node_text(func_node, content)

            method_symbol = ParsedSymbol(
                name=func_name,
                symbol_type="method",
                start_line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                code=func_code,
                parent_name=class_name,
            )
            methods.append(method_symbol)

        return methods

    def _is_in_any_class(self, node: Node, class_nodes: List[Node]) -> bool:
        """检查节点是否在任何一个类中."""
        for class_node in class_nodes:
            if self._node_contains(class_node, node):
                return True
        return False

    # ==================== 依赖图构建阶段 - Import 提取 ====================

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从 Python 代码中提取 import 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            # 使用正则表达式作为回退
            return self._extract_imports_regex(content)

        root_node = tree.root_node
        import_captures = self._exec_query(self.QUERIES["import"], root_node)

        for node, capture_name in import_captures:
            line_number = self._get_node_line(node)

            if "import_from" in node.type or "from" in self._node_text(node, content).lower():
                # from x import y
                import_info = self._parse_from_import(node, content, line_number)
                if import_info:
                    imports.append(import_info)
            else:
                # import x
                import_info = self._parse_import(node, content, line_number)
                if import_info:
                    imports.append(import_info)

        # 合并相同模块的导入
        return self._merge_imports(imports)

    def _parse_import(
        self,
        node: Node,
        content: str,
        line_number: int,
    ) -> Optional[ImportInfo]:
        """解析 import x 语句."""
        text = self._node_text(node, content)

        # 解析 import x as y
        match = re.match(r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?", text)
        if match:
            module = match.group(1)
            alias = match.group(2)
            return ImportInfo(
                module=module,
                alias=alias,
                line_number=line_number,
            )
        return None

    def _parse_from_import(
        self,
        node: Node,
        content: str,
        line_number: int,
    ) -> Optional[ImportInfo]:
        """解析 from x import y 语句."""
        text = self._node_text(node, content)

        # 解析 from x import y, z
        match = re.match(r"^\s*from\s+([\w.]+)\s+import\s+(.+)$", text, re.DOTALL)
        if match:
            module = match.group(1)
            names_str = match.group(2)

            # 提取导入的名称
            names = []
            for name_match in re.finditer(r"([\w*]+)(?:\s+as\s+\w+)?", names_str):
                names.append(name_match.group(1))

            return ImportInfo(
                module=module,
                imported_names=names,
                line_number=line_number,
            )
        return None

    def _extract_imports_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 import（作为回退）."""
        imports: List[ImportInfo] = []

        # import x
        for match in re.finditer(r"^\s*import\s+([\w.]+)", content, re.MULTILINE):
            imports.append(ImportInfo(module=match.group(1)))

        # from x import y
        for match in re.finditer(r"^\s*from\s+([\w.]+)\s+import", content, re.MULTILINE):
            imports.append(ImportInfo(module=match.group(1)))

        return imports

    def _merge_imports(self, imports: List[ImportInfo]) -> List[ImportInfo]:
        """合并相同模块的导入."""
        module_map: dict = {}

        for imp in imports:
            if imp.module in module_map:
                existing = module_map[imp.module]
                # 合并导入的名称
                existing.imported_names.extend(imp.imported_names)
                # 去重
                existing.imported_names = list(set(existing.imported_names))
            else:
                module_map[imp.module] = ImportInfo(
                    module=imp.module,
                    alias=imp.alias,
                    imported_names=list(imp.imported_names),
                    is_relative=imp.is_relative,
                    line_number=imp.line_number,
                )

        return list(module_map.values())

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 Python 方法代码中提取方法调用."""
        calls: List[MethodCallInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            # 使用正则表达式作为回退
            return self._extract_calls_regex(content, method_name)

        root_node = tree.root_node
        call_captures = self._exec_query(self.QUERIES["call"], root_node)

        for node, capture_name in call_captures:
            line_number = self._get_node_line(node)

            if "attribute" in capture_name:
                # obj.method() 形式
                call_info = self._parse_attribute_call(node, content, line_number)
            else:
                # method() 形式
                call_info = self._parse_simple_call(node, content, line_number)

            if call_info and call_info.method_name != method_name:
                calls.append(call_info)

        return calls

    def _parse_simple_call(
        self,
        node: Node,
        content: str,
        line_number: int,
    ) -> Optional[MethodCallInfo]:
        """解析简单方法调用."""
        text = self._node_text(node, content)
        match = re.match(r"([a-zA-Z_]\w*)\s*\(", text)
        if match:
            return MethodCallInfo(
                method_name=match.group(1),
                line_number=line_number,
            )
        return None

    def _parse_attribute_call(
        self,
        node: Node,
        content: str,
        line_number: int,
    ) -> Optional[MethodCallInfo]:
        """解析属性方法调用（obj.method()）."""
        text = self._node_text(node, content)

        # 提取 object.method
        match = re.match(r"([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\s*\(", text)
        if match:
            return MethodCallInfo(
                method_name=match.group(2),
                receiver=match.group(1),
                line_number=line_number,
            )
        return None

    def _extract_calls_regex(
        self,
        content: str,
        method_name: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """使用正则表达式提取方法调用（作为回退）."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        # 匹配 func() 或 obj.method()
        pattern = r"(?<![\w.])([a-zA-Z_]\w*)\s*\("
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
        """获取需要排除的内置名称."""
        return {
            "if", "while", "for", "switch", "catch", "return",
            "print", "println", "printf", "len", "range", "enumerate",
            "map", "filter", "reduce", "sorted", "reversed",
            "int", "str", "float", "bool", "list", "dict", "set", "tuple",
            "super", "self", "cls",
        }
