"""Rust 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class RustAnalyzer(BaseTreeSitterAnalyzer):
    """Rust 代码分析器."""

    language = Language(tsrust.language())

    QUERIES = {
        "struct": """
            (struct_item
                name: (type_identifier) @struct.name
            ) @struct.def
        """,
        "enum": """
            (enum_item
                name: (type_identifier) @enum.name
            ) @enum.def
        """,
        "trait": """
            (trait_item
                name: (type_identifier) @trait.name
            ) @trait.def
        """,
        "impl": """
            (impl_item
                type: (type_identifier) @impl.type
            ) @impl.def
        """,
        "function": """
            (function_item
                name: (identifier) @function.name
                body: (block) @function.body
            ) @function.def
        """,
        "method": """
            (function_item
                name: (identifier) @method.name
                body: (block) @method.body
            ) @method.def
        """,
        "use": """
            (use_declaration
                argument: (use_wildcard) @use.wildcard
            ) @use.def
            (use_declaration
                argument: (scoped_identifier) @use.path
            ) @use.def
            (use_declaration
                argument: (identifier) @use.name
            ) @use.def
        """,
        "extern_crate": """
            (extern_crate_item
                name: (identifier) @crate.name
            ) @crate.def
        """,
        "call": """
            (call_expression
                function: (identifier) @call.name
            ) @call.def
            (call_expression
                function: (field_expression
                    value: (identifier) @call.object
                    field: (field_identifier) @call.method
                )
            ) @call.def
            (call_expression
                function: (scoped_identifier) @call.scoped
            ) @call.def
        """,
        "method_call": """
            (call_expression
                function: (field_expression
                    field: (field_identifier) @method.name
                )
            ) @method.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".rs"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "rust"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 Rust 代码，提取结构体、枚举、trait 和函数/方法定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse Rust code",
            )

        root_node = tree.root_node
        classes: List[ParsedSymbol] = []
        methods: List[ParsedSymbol] = []

        # 提取结构体
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

        # 提取枚举
        enum_captures = self._exec_query(self.QUERIES["enum"], root_node)
        enum_nodes = self._group_captures(enum_captures, "enum")

        for enum_node, info in enum_nodes.items():
            enum_name = info.get("name", "Unknown")
            enum_code = self._node_text(enum_node, content)

            enum_symbol = ParsedSymbol(
                name=enum_name,
                symbol_type="enum",
                start_line=enum_node.start_point[0] + 1,
                end_line=enum_node.end_point[0] + 1,
                code=enum_code,
            )
            classes.append(enum_symbol)

        # 提取 trait
        trait_captures = self._exec_query(self.QUERIES["trait"], root_node)
        trait_nodes = self._group_captures(trait_captures, "trait")

        for trait_node, info in trait_nodes.items():
            trait_name = info.get("name", "Unknown")
            trait_code = self._node_text(trait_node, content)

            trait_symbol = ParsedSymbol(
                name=trait_name,
                symbol_type="trait",
                start_line=trait_node.start_point[0] + 1,
                end_line=trait_node.end_point[0] + 1,
                code=trait_code,
            )
            classes.append(trait_symbol)

        # 提取 impl 块中的方法
        impl_captures = self._exec_query(self.QUERIES["impl"], root_node)
        impl_nodes = self._group_captures(impl_captures, "impl")

        for impl_node, info in impl_nodes.items():
            impl_type = info.get("type", "Unknown")

            # 提取 impl 块中的方法
            impl_methods = self._extract_methods_in_impl(impl_node, content, impl_type)
            methods.extend(impl_methods)

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
            elif f"{prefix}.name" in capture_name or f"{prefix}.type" in capture_name:
                for def_node in defs:
                    if self._node_contains(def_node, node):
                        defs[def_node]["name"] = node.text.decode("utf8") if node.text else ""
                        break
        return defs

    def _extract_methods_in_impl(
        self,
        impl_node: Node,
        content: str,
        impl_type: str,
    ) -> List[ParsedSymbol]:
        """提取 impl 块中的方法."""
        methods: List[ParsedSymbol] = []

        function_captures = self._exec_query(self.QUERIES["function"], impl_node)
        func_nodes = self._group_captures(function_captures, "function")

        for func_node, info in func_nodes.items():
            func_name = info.get("name", "Unknown")
            func_code = self._node_text(func_node, content)

            method_symbol = ParsedSymbol(
                name=func_name,
                symbol_type="method",
                start_line=func_node.start_point[0] + 1,
                end_line=func_node.end_point[0] + 1,
                code=func_code,
                parent_name=impl_type,
            )
            methods.append(method_symbol)

        return methods

    # ==================== 依赖图构建阶段 - Import 提取 ====================

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从 Rust 代码中提取 use 和 extern crate 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_imports_regex(content)

        root_node = tree.root_node

        # use 声明
        use_captures = self._exec_query(self.QUERIES["use"], root_node)
        for node, capture_name in use_captures:
            if "use.path" in capture_name:
                use_text = node.text.decode("utf8") if node.text else ""
                line_number = self._get_node_line(node)
                imports.append(ImportInfo(
                    module=use_text,
                    line_number=line_number,
                ))
            elif "use.wildcard" in capture_name:
                # use x::y::*
                wildcard_text = node.text.decode("utf8") if node.text else ""
                # 提取路径部分
                base = wildcard_text.replace("::*", "").replace("*", "")
                line_number = self._get_node_line(node)
                imports.append(ImportInfo(
                    module=base,
                    line_number=line_number,
                ))

        # extern crate
        crate_captures = self._exec_query(self.QUERIES["extern_crate"], root_node)
        for node, capture_name in crate_captures:
            if "crate.name" in capture_name:
                crate_name = node.text.decode("utf8") if node.text else ""
                line_number = self._get_node_line(node)
                imports.append(ImportInfo(
                    module=crate_name,
                    line_number=line_number,
                ))

        return imports

    def _extract_imports_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 use（作为回退）."""
        imports: List[ImportInfo] = []

        # use x::y
        for match in re.finditer(r"^\s*use\s+([\w:]+)", content, re.MULTILINE):
            imports.append(ImportInfo(module=match.group(1)))

        # extern crate x
        for match in re.finditer(r"^\s*extern\s+crate\s+(\w+)", content, re.MULTILINE):
            imports.append(ImportInfo(module=match.group(1)))

        return imports

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 Rust 代码中提取函数/方法调用."""
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
                # obj.method() 形式
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
            elif "call.scoped" in capture_name:
                # ::function() 形式
                scoped_text = node.text.decode("utf8") if node.text else ""
                parts = scoped_text.split("::")
                if parts:
                    func_name = parts[-1]
                    if func_name and func_name != method_name:
                        key = (func_name, line_number)
                        if key not in seen:
                            seen.add(key)
                            calls.append(MethodCallInfo(
                                method_name=func_name,
                                line_number=line_number,
                            ))
            elif "call.name" in capture_name:
                # function() 形式
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

        # 匹配 function() 或 obj.method()
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
            "if", "while", "for", "match", "return", "loop",
            "Some", "None", "Ok", "Err", "Box", "Vec",
            "println", "print", "format", "panic", "todo", "unimplemented",
        }
