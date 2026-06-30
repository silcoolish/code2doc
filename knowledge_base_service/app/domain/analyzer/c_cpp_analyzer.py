"""C/C++ 代码分析器."""

import logging
import re
from typing import List, Optional, Tuple

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Node

from app.domain.analyzer.base_tree_sitter_analyzer import BaseTreeSitterAnalyzer
from app.domain.analyzer.code_analyzer import (
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)

logger = logging.getLogger(__name__)


class CAnalyzer(BaseTreeSitterAnalyzer):
    """C 代码分析器."""

    language = Language(tsc.language())

    QUERIES = {
        "struct": """
            ; 具名结构体
            (struct_specifier
                name: (type_identifier) @struct.name
                body: (field_declaration_list) @struct.body
            ) @struct.def

            ; typedef 匿名结构体
            (type_definition
                (struct_specifier
                    body: (field_declaration_list) @struct.body
                )
                declarator: (type_identifier) @struct.name
            ) @struct.def
        """,
        "function": """
            ; 普通函数
            (function_definition
                declarator: (function_declarator
                    declarator: (identifier) @function.name
                )
                body: (compound_statement) @function.body
            ) @function.def

            ; 返回指针的函数
            (function_definition
                declarator: (pointer_declarator
                    declarator: (function_declarator
                        declarator: (identifier) @function.name
                    )
                )
                body: (compound_statement) @function.body
            ) @function.def
        """,
        "typedef": """
            (type_definition
                declarator: (type_identifier) @typedef.name
            ) @typedef.def
        """,
        "include": """
            (preproc_include
                path: (string_literal) @include.path
            )
            (preproc_include
                path: (system_lib_string) @include.path
            )
        """,
        "call": """
            (call_expression
                function: (identifier) @call.name
            ) @call.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".c", ".h"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "c"

    # ==================== 结构图构建阶段 ====================

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 C 代码，提取结构体和函数定义."""
        tree = self._parse_tree(content)
        if tree is None:
            return StructureParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error="Failed to parse C code",
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

        # 提取函数
        function_captures = self._exec_query(self.QUERIES["function"], root_node)
        func_nodes = self._group_captures(function_captures, "function")

        for func_node, info in func_nodes.items():
            func_name = info.get("name", "Unknown")
            func_code = self._node_text(func_node, content)

            # 验证提取的 code 是否有效（应该以函数签名开头）
            if not self._is_valid_function_code(func_code, func_name):
                # 尝试使用正则表达式重新提取
                func_code = self._extract_function_regex(content, func_name)
                if not func_code:
                    logger.warning(f"Could not extract valid code for function: {func_name}")
                    continue

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
            elif f"{prefix}.name" in capture_name:
                for def_node in defs:
                    if self._node_contains(def_node, node):
                        defs[def_node]["name"] = node.text.decode("utf8") if node.text else ""
                        break
        return defs

    # ==================== 依赖图构建阶段 - Include 提取 ====================

    def extract_imports(
        self,
        content: str,
        file_path: Optional[str] = None,
    ) -> List[ImportInfo]:
        """从 C 代码中提取 #include 语句."""
        imports: List[ImportInfo] = []

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_includes_regex(content)

        root_node = tree.root_node
        include_captures = self._exec_query(self.QUERIES["include"], root_node)

        for node, capture_name in include_captures:
            if "include.path" in capture_name:
                include_text = node.text.decode("utf8") if node.text else ""
                # 去除引号
                header = include_text.strip("<>\"\"")
                line_number = self._get_node_line(node)

                imports.append(ImportInfo(
                    module=header,
                    line_number=line_number,
                ))

        return imports

    def _extract_includes_regex(self, content: str) -> List[ImportInfo]:
        """使用正则表达式提取 #include（作为回退）."""
        imports: List[ImportInfo] = []

        for match in re.finditer(r'#\s*include\s+["<]([^">]+)[">]', content):
            imports.append(ImportInfo(module=match.group(1)))

        return imports

    # ==================== 依赖图构建阶段 - 方法调用提取 ====================

    def extract_method_calls(
        self,
        content: str,
        method_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[MethodCallInfo]:
        """从 C 代码中提取函数调用."""
        calls: List[MethodCallInfo] = []
        seen: set = set()

        tree = self._parse_tree(content)
        if tree is None:
            return self._extract_calls_regex(content, method_name)

        root_node = tree.root_node
        call_captures = self._exec_query(self.QUERIES["call"], root_node)

        for node, capture_name in call_captures:
            if "call.name" in capture_name:
                func_name = node.text.decode("utf8") if node.text else ""
                line_number = self._get_node_line(node)

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

        # 匹配 function(arg) 形式，但排除控制结构
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
            "sizeof", "typeof", "offsetof",
        }

    def resolve_import(
        self,
        import_info: ImportInfo,
        current_file: str,
        file_path_index: dict[str, str],
    ) -> Optional[str]:
        """解析 C #include 语句，找到对应的文件ID.

        Args:
            import_info: import 信息
            current_file: 当前文件路径
            file_path_index: 文件路径索引（路径到ID的映射）

        Returns:
            目标文件ID或 None
        """

        module = import_info.module

        # 尝试直接匹配
        if module in file_path_index:
            return file_path_index[module]

        # C/C++: header.h -> 尝试匹配各种扩展名
        # 去除路径前缀，只取文件名
        parts = module.replace("\\", "/").split("/")
        header_name = parts[-1] if parts else module

        # 尝试匹配 C/C++ 头文件和源文件
        for ext in [".h", ".hpp", ".hh", ".hxx", ".c", ".cpp", ".cc", ".cxx"]:
            # 尝试直接使用 header 名（带扩展名）
            if header_name.endswith(ext):
                if header_name in file_path_index:
                    return file_path_index[header_name]
            else:
                # 尝试添加扩展名
                filename = header_name + ext
                if filename in file_path_index:
                    return file_path_index[filename]

        # 尝试匹配路径中包含 header 名
        for path, file_id in file_path_index.items():
            if header_name in path:
                return file_id

        return None

    def _is_valid_function_code(self, code: str, func_name: str) -> bool:
        """验证提取的 code 是否是有效的函数定义.

        检查 code 是否以常见的函数返回类型或函数名开头。
        这对于过滤掉 tree-sitter 在解析压缩代码时产生的错误匹配很有用。

        Args:
            code: 提取的代码
            func_name: 函数名

        Returns:
            是否是有效的函数代码
        """
        if not code or not code.strip():
            return False

        code = code.strip()

        # 有效的函数定义应该以以下之一开头：
        # 1. 返回类型 (int, void, char, bool, auto, etc.)
        # 2. 函数名（当返回类型是宏定义时，如 typedef int I; I func(){}）
        valid_starts = [
            # 常见返回类型
            "int ", "void ", "char ", "bool ", "float ", "double ", "auto ",
            "short ", "long ", "unsigned ", "signed ", "size_t ", "ssize_t ",
            "int8_t ", "int16_t ", "int32_t ", "int64_t ",
            "uint8_t ", "uint16_t ", "uint32_t ", "uint64_t ",
            "std::", "const ", "static ", "inline ", "virtual ",
            # 模板
            "template",
            # 宏定义类型（单个大写字母，如 typedef int I;）
            "A ", "B ", "C ", "D ", "E ", "F ", "G ", "H ", "I ", "J ",
            "K ", "L ", "M ", "N ", "O ", "P ", "Q ", "R ", "S ", "T ",
            "U ", "V ", "W ", "X ", "Y ", "Z ",
        ]

        # 检查是否以有效的开头开始
        for start in valid_starts:
            if code.startswith(start):
                return True

        # 检查是否以函数名开头（后面跟着左括号）
        # 这适用于宏定义类型的情况，如：I func(){}
        if code.startswith(f"{func_name}("):
            return True

        return False

    def _extract_function_regex(self, content: str, func_name: str) -> str:
        """使用正则表达式从内容中提取函数定义.

        当 tree-sitter 解析失败时作为备用方法。

        Args:
            content: 文件内容
            func_name: 函数名

        Returns:
            提取的函数代码，如果提取失败返回空字符串
        """
        escaped_name = re.escape(func_name)

        # 策略1: 尝试匹配完整的函数定义（包括返回类型）
        # 使用平衡花括号匹配来处理嵌套
        full_pattern = rf"[a-zA-Z_][a-zA-Z0-9_]*\s+{escaped_name}\s*\([^)]*\)\s*\{{"
        match = re.search(full_pattern, content)
        if match:
            start = match.start()
            # 手动匹配花括号
            brace_count = 0
            end = start
            for i, char in enumerate(content[start:]):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = start + i + 1
                        break
            if end > start:
                return content[start:end]

        # 策略2: 尝试匹配宏定义类型（单个大写字母）+ 函数名
        macro_pattern = rf"I\s+{escaped_name}\s*\([^)]*\)\s*\{{"
        match = re.search(macro_pattern, content)
        if match:
            start = match.start()
            # 手动匹配花括号
            brace_count = 0
            end = start
            for i, char in enumerate(content[start:]):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = start + i + 1
                        break
            if end > start:
                return content[start:end]

        # 策略3: 直接查找 函数名() { 并在前面加上返回类型
        simple_pattern = rf"{escaped_name}\s*\([^)]*\)\s*\{{"
        match = re.search(simple_pattern, content)
        if match:
            func_start = match.start()
            # 手动匹配花括号
            brace_count = 0
            end = func_start
            for i, char in enumerate(content[func_start:]):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = func_start + i + 1
                        break
            if end > func_start:
                # 尝试向前查找返回类型
                search_start = max(0, func_start - 50)
                prefix = content[search_start:func_start]
                ret_type_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*\s+|I\s+)$", prefix)
                if ret_type_match:
                    return ret_type_match.group(1) + content[func_start:end]
                return content[func_start:end]

        return ""


class CppAnalyzer(CAnalyzer):
    """C++ 代码分析器."""

    language = Language(tscpp.language())

    QUERIES = {
        **CAnalyzer.QUERIES,
        "class": """
            (class_specifier
                name: (type_identifier) @class.name
                body: (field_declaration_list) @class.body
            ) @class.def
        """,
        "namespace": """
            (namespace_definition
                name: (identifier) @namespace.name
                body: (declaration_list) @namespace.body
            ) @namespace.def
        """,
        "method": """
            ; 类方法
            (function_definition
                declarator: (function_declarator
                    declarator: (field_identifier) @method.name
                )
                body: (compound_statement) @method.body
            ) @method.def

            ; 返回指针的类方法
            (function_definition
                declarator: (pointer_declarator
                    declarator: (function_declarator
                        declarator: (field_identifier) @method.name
                    )
                )
                body: (compound_statement) @method.body
            ) @method.def
        """,
    }

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"]

    @property
    def language_name(self) -> str:
        """语言名称."""
        return "cpp"

    def parse_for_structure(
        self,
        file_path: str,
        content: str,
    ) -> StructureParseResult:
        """解析 C++ 代码，包含类和方法."""
        result = super().parse_for_structure(file_path, content)
        result.language = self.language_name

        tree = self._parse_tree(content)
        if tree is None:
            return result

        root_node = tree.root_node

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
            result.classes.append(class_symbol)

            # 提取类方法
            class_methods = self._extract_methods_in_class(class_node, content, class_name)
            result.methods.extend(class_methods)

        return result

    def _extract_methods_in_class(
        self,
        class_node: Node,
        content: str,
        class_name: str,
    ) -> List[ParsedSymbol]:
        """提取 C++ 类中的方法."""
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

    def _get_excluded_names(self) -> set:
        """获取需要排除的关键字."""
        return {
            "if", "while", "for", "switch", "catch", "return",
            "sizeof", "typeof", "decltype", "new", "delete",
            "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
        }
