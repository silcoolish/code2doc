"""Go 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_go as tsgo
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class GoAnalyzer(BaseTreeSitterAnalyzer):
    """Go 代码分析器."""

    language = Language(tsgo.language())

    QUERIES = {
        "type": """
            (type_declaration
                (type_spec
                    name: (type_identifier) @type.name
                )
            ) @type.def
        """,
        "struct": """
            (type_declaration
                (type_spec
                    name: (type_identifier) @struct.name
                    type: (struct_type)
                )
            ) @struct.def
        """,
        "interface": """
            (type_declaration
                (type_spec
                    name: (type_identifier) @interface.name
                    type: (interface_type)
                )
            ) @interface.def
        """,
        "function": """
            (function_declaration
                name: (identifier) @function.name
                body: (block) @function.body
            ) @function.def
        """,
        "method": """
            (method_declaration
                name: (field_identifier) @method.name
                body: (block) @method.body
            ) @method.def
        """,
        "import": """
            (import_declaration
                (import_spec
                    path: (interpreted_string_literal) @import.path
                )
            ) @import.def
            (import_declaration
                (import_spec_list
                    (import_spec
                        path: (interpreted_string_literal) @import.path
                    )
                )
            ) @import.def
        """,
        "call": """
            (call_expression
                function: (identifier) @call.name
            ) @call.def
            (call_expression
                function: (selector_expression
                    operand: (identifier) @call.object
                    field: (field_identifier) @call.method
                )
            ) @call.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".go"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "go"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 Go 代码，提取类型和函数/方法定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse Go code",
            )

        root_node = tree.root_node
        classes: List[ParsedSymbol] = []
        methods: List[ParsedSymbol] = []

        # 提取结构体（作为类处理）
        struct_captures = self._exec_query(self.QUERIES["struct"], root_node)
        struct_nodes = self._group_captures(struct_captures, "struct")

        for struct_node, info in struct_nodes.items():
            struct_name = info.get("name", "Unknown")
            struct_code = self._node_text(struct_node, content)

            struct_symbol = ParsedSymbol(
                name=struct_name,
                symbol_type="struct",
                start_line=struct_node.start_point[0] + 1,
                end_line=struct_node.end_point[0] + 1,
                code=struct_code,
            )
            classes.append(struct_symbol)

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
            classes.append(interface_symbol)

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

        # 提取方法（带接收者的函数）
        method_captures = self._exec_query(self.QUERIES["method"], root_node)
        method_nodes = self._group_captures(method_captures, "method")

        for method_node, info in method_nodes.items():
            method_name = info.get("name", "Unknown")
            method_code = self._node_text(method_node, content)

            # 尝试提取接收者类型
            receiver_type = self._extract_receiver_type(method_node, content)

            method_symbol = ParsedSymbol(
                name=method_name,
                symbol_type="method",
                start_line=method_node.start_point[0] + 1,
                end_line=method_node.end_point[0] + 1,
                code=method_code,
                parent_name=receiver_type,
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

    def _extract_receiver_type(self, method_node: Node, content: str) -> Optional[str]:
        """提取方法的接收者类型."""
        try:
            # 在方法声明中查找 receiver
            for child in method_node.children:
                if child.type == "parameter_list":
                    # 第一个 parameter_list 是接收者
                    receiver_text = self._node_text(child, content)
                    # 提取类型名
                    match = re.search(r"\(\s*\w*\s*\*?(\w+)\s*\)", receiver_text)
                    if match:
                        return match.group(1)
                    break
        except Exception:
            pass
        return None

    # ==================== 依赖图构建阶段 - Import 提取 ====================

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从 Go 代码中提取 import 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_imports_regex(content)

        root_node = tree.root_node
        import_captures = self._exec_query(self.QUERIES["import"], root_node)

        seen: set = set()
        for node, capture_name in import_captures:
            if "import.path" in capture_name:
                import_text = node.text.decode("utf8") if node.text else ""
                # 去除引号
                module = import_text.strip('"')
                line_number = self._get_node_line(node)

                key = (module, line_number)
                if key not in seen:
                    seen.add(key)
                    imports.append(ImportInfo(
                        module=module,
                        line_number=line_number,
                    ))

        return imports

    def _extract_imports_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 import（作为回退）."""
        imports: List[ImportInfo] = []

        # 单行 import
        for match in re.finditer(r'import\s+["\']([^"\']+)["\']', content):
            imports.append(ImportInfo(module=match.group(1)))

        # 多行 import 块
        block_match = re.search(r'import\s*\((.*?)\)', content, re.DOTALL)
        if block_match:
            block_content = block_match.group(1)
            for match in re.finditer(r'["\']([^"\']+)["\']', block_content):
                imports.append(ImportInfo(module=match.group(1)))

        return imports

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 Go 代码中提取函数/方法调用."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_calls_regex(content, method_name)

        root_node = tree.root_node
        call_captures = self._exec_query(self.QUERIES["call"], root_node)

        for node, capture_name in call_captures:
            line_number = self._get_node_line(node)

            if "call.method" in capture_name:
                # obj.Method() 形式
                method_name_found = node.text.decode("utf8") if node.text else ""
                if method_name_found and method_name_found != method_name:
                    # 查找 receiver
                    receiver = None
                    for obj_node, obj_name in call_captures:
                        if "call.object" in obj_name:
                            receiver = obj_node.text.decode("utf8") if obj_node.text else None
                            break

                    key = (method_name_found, line_number)
                    if key not in seen:
                        seen.add(key)
                        calls.append(MethodCallInfo(
                            method_name=method_name_found,
                            receiver=receiver,
                            line_number=line_number,
                        ))
            elif "call.name" in capture_name:
                # Function() 形式
                func_name = node.text.decode("utf8") if node.text else ""
                if func_name and func_name != method_name:
                    if func_name not in self._get_excluded_names():
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
        """使用正则表达式提取函数调用."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        # 匹配 function() 或 obj.Method()
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
            "if", "for", "switch", "return", "panic",
            "make", "len", "cap", "append", "copy", "delete",
            "close", "complex", "real", "imag",
        }
