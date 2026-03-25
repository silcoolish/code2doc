"""Tree-sitter 代码解析器实现."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser, Node, Query

# 尝试导入 QueryCursor（tree-sitter 0.22+）
try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None

from app.domain.parser.code_parser import (
    CodeParser,
    ParseResult,
    ASTNode,
    ClassSymbol,
    MethodSymbol,
)

logger = logging.getLogger(__name__)


class TreeSitterParser(CodeParser):
    """基于 Tree-sitter 的代码解析器."""

    # 语言映射表
    LANGUAGE_MAP: Dict[str, Language] = {
        ".py": Language(tspython.language()),
        ".java": Language(tsjava.language()),
        ".js": Language(tsjavascript.language()),
        ".ts": Language(tstypescript.language_typescript()),
        ".tsx": Language(tstypescript.language_tsx()),
        ".go": Language(tsgo.language()),
        ".rs": Language(tsrust.language()),
        ".c": Language(tsc.language()),
        ".h": Language(tsc.language()),
        ".cpp": Language(tscpp.language()),
        ".hpp": Language(tscpp.language()),
        ".cc": Language(tscpp.language()),
        ".cxx": Language(tscpp.language()),
    }

    # 查询定义（用于提取符号）
    QUERIES = {
        ".py": {
            "class": """
                (class_definition
                    name: (identifier) @class.name
                    body: (block) @class.body
                ) @class.def
            """,
            "method": """
                (function_definition
                    name: (identifier) @method.name
                    body: (block) @method.body
                ) @method.def
            """,
            "method_in_class": """
                (class_definition
                    body: (block
                        (function_definition
                            name: (identifier) @method.name
                            body: (block) @method.body
                        ) @method.def
                    )
                )
            """,
            "import": """
                (import_statement
                    name: (dotted_name) @import.name
                )
                (import_from_statement
                    module_name: (dotted_name) @import.name
                )
            """,
        },
        ".java": {
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
                    body: (block) @method.body
                ) @method.def
            """,
            "import": """
                (import_declaration
                    (scoped_identifier) @import.name
                )
            """,
        },
        ".js": {
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
                )
            """,
            "import": """
                (import_statement
                    source: (string) @import.source
                )
            """,
        },
        ".ts": {
            "class": """
                (class_declaration
                    name: (type_identifier) @class.name
                    body: (class_body) @class.body
                ) @class.def
            """,
            "interface": """
                (interface_declaration
                    name: (type_identifier) @interface.name
                ) @interface.def
            """,
            "method": """
                (method_signature
                    name: (property_identifier) @method.name
                )
                (method_definition
                    name: (property_identifier) @method.name
                )
            """,
            "import": """
                (import_statement
                    source: (string) @import.source
                )
            """,
        },
        ".c": {
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
        },
        ".cpp": {
            "class": """
                (class_specifier
                    name: (type_identifier) @class.name
                    body: (field_declaration_list) @class.body
                ) @class.def
            """,
            "struct": """
                (struct_specifier
                    name: (type_identifier) @struct.name
                    body: (field_declaration_list) @struct.body
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
            "namespace": """
                (namespace_definition
                    name: (identifier) @namespace.name
                    body: (declaration_list) @namespace.body
                ) @namespace.def
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
        },
        ".h": {
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
        },
        ".hpp": {
            "class": """
                (class_specifier
                    name: (type_identifier) @class.name
                    body: (field_declaration_list) @class.body
                ) @class.def
            """,
            "struct": """
                (struct_specifier
                    name: (type_identifier) @struct.name
                    body: (field_declaration_list) @struct.body
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
            "namespace": """
                (namespace_definition
                    name: (identifier) @namespace.name
                    body: (declaration_list) @namespace.body
                ) @namespace.def
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
        },
    }

    def __init__(self, language: str):
        """初始化解析器.

        Args:
            language: 语言标识符（如 .py, .java）
        """
        self.language_ext = language
        self.language = self.LANGUAGE_MAP.get(language)
        self.parser = Parser(self.language) if self.language else None
        self._language_name = self._get_language_name(language)

    def _get_language_name(self, ext: str) -> str:
        """获取语言名称."""
        names = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
        }
        return names.get(ext, "unknown")

    @property
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名."""
        return list(self.LANGUAGE_MAP.keys())

    @property
    def language_name(self) -> str:
        """语言名称."""
        return self._language_name

    def parse(self, file_path: str, content: str) -> ParseResult:
        """解析代码文件.

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            解析结果
        """
        if self.parser is None:
            return ParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error=f"Unsupported language: {self.language_ext}",
            )

        try:
            # 解析为 AST
            tree = self.parser.parse(bytes(content, "utf8"))
            root_node = tree.root_node

            # 转换为自定义 ASTNode
            ast = self._convert_node(root_node, content)

            # 提取符号
            classes, methods = self._extract_symbols(root_node, content)
            imports = self._extract_imports(root_node)

            return ParseResult(
                file_path=file_path,
                language=self.language_name,
                ast=ast,
                classes=classes,
                methods=methods,
                imports=imports,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return ParseResult(
                file_path=file_path,
                language=self.language_name,
                success=False,
                error=str(e),
            )

    def _convert_node(self, node: Node, content: str) -> ASTNode:
        """将 Tree-sitter 节点转换为 ASTNode.

        Args:
            node: Tree-sitter 节点
            content: 原始内容

        Returns:
            ASTNode
        """
        start_point = node.start_point
        end_point = node.end_point

        children = [self._convert_node(child, content) for child in node.children]

        return ASTNode(
            node_type=node.type,
            start_line=start_point[0] + 1,  # 转换为 1-based
            end_line=end_point[0] + 1,
            start_col=start_point[1],
            end_col=end_point[1],
            text=content[node.start_byte:node.end_byte],
            children=children,
            properties={
                "is_named": node.is_named,
                "has_error": node.has_error,
            },
        )

    def _process_captures(self, captures: dict) -> list[tuple[Node, str]]:
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

    def _exec_query(self, query_str: str, node: Node) -> list[tuple[Node, str]]:
        """执行查询并返回捕获结果.

        Args:
            query_str: 查询字符串
            node: 要查询的节点

        Returns:
            节点和捕获名称的列表
        """
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

    def _get_queries_for_ext(self, ext: str) -> dict:
        """获取指定扩展名的查询配置.

        Args:
            ext: 文件扩展名

        Returns:
            查询配置字典
        """
        # 扩展名映射到查询键
        ext_mapping = {
            ".h": ".c",
            ".hpp": ".cpp",
            ".cc": ".cpp",
            ".cxx": ".cpp",
        }
        query_key = ext_mapping.get(ext, ext)
        return self.QUERIES.get(query_key, {})

    def _extract_symbols(
        self,
        root_node: Node,
        content: str,
    ) -> tuple[List[ClassSymbol], List[MethodSymbol]]:
        """提取类和方法符号.

        Args:
            root_node: 根节点
            content: 原始内容

        Returns:
            (类列表, 独立方法列表)
        """
        classes: List[ClassSymbol] = []
        standalone_methods: List[MethodSymbol] = []

        queries = self._get_queries_for_ext(self.language_ext)
        if not queries:
            logger.debug(f"No queries found for extension: {self.language_ext}")
            return classes, standalone_methods

        # 提取类
        if "class" in queries:
            try:
                capture_list = self._exec_query(queries["class"], root_node)

                # 按模式分组捕获
                class_defs = {}
                for node, capture_name in capture_list:
                    if "class.def" in capture_name:
                        class_defs[node] = {"node": node}
                    elif "class.name" in capture_name:
                        for class_node in class_defs:
                            if self._node_contains(class_node, node):
                                class_defs[class_node]["name"] = content[node.start_byte:node.end_byte]
                                break

                for class_node, info in class_defs.items():
                    name = info.get("name", "Unknown")
                    class_code = content[class_node.start_byte:class_node.end_byte]

                    # 提取类中的方法
                    class_methods = self._extract_methods_in_class(
                        class_node, content, name
                    )

                    class_symbol = ClassSymbol(
                        name=name,
                        start_line=class_node.start_point[0] + 1,
                        end_line=class_node.end_point[0] + 1,
                        code=class_code,
                        methods=class_methods,
                    )
                    classes.append(class_symbol)

                    # 从独立方法列表中移除类中的方法
                    standalone_methods = [
                        m for m in standalone_methods
                        if not self._is_method_in_class(m, class_symbol)
                    ]

            except Exception as e:
                logger.warning(f"Failed to extract classes: {e}")

        # 提取结构体 (C/C++)
        if "struct" in queries:
            try:
                capture_list = self._exec_query(queries["struct"], root_node)

                struct_defs = {}
                for node, capture_name in capture_list:
                    if "struct.def" in capture_name:
                        struct_defs[node] = {"node": node}
                    elif "struct.name" in capture_name:
                        for struct_node in struct_defs:
                            if self._node_contains(struct_node, node):
                                struct_defs[struct_node]["name"] = content[node.start_byte:node.end_byte]
                                break

                for struct_node, info in struct_defs.items():
                    name = info.get("name", "Unknown")
                    struct_code = content[struct_node.start_byte:struct_node.end_byte]

                    # 结构体作为类符号处理
                    class_symbol = ClassSymbol(
                        name=name,
                        start_line=struct_node.start_point[0] + 1,
                        end_line=struct_node.end_point[0] + 1,
                        code=struct_code,
                        methods=[],  # C struct 通常没有方法
                    )
                    classes.append(class_symbol)

            except Exception as e:
                logger.warning(f"Failed to extract structs: {e}")

        # 提取独立方法
        if "method" in queries or "function" in queries:
            try:
                # 对于独立函数，优先使用 function 查询（如果存在）
                # function 查询使用 identifier 匹配独立函数
                # method 查询使用 field_identifier 匹配类方法
                method_query = queries.get("function") or queries.get("method")
                if not method_query:
                    logger.debug(f"No method/function query found for {self.language_ext}")
                    return classes, standalone_methods

                capture_list = self._exec_query(method_query, root_node)
                logger.debug(f"Found {len(capture_list)} captures for {self.language_ext}")

                method_defs = {}
                for node, capture_name in capture_list:
                    # 支持 function.def (C/C++) 和 method.def (其他语言)
                    if ".def" in capture_name and ("function" in capture_name or "method" in capture_name):
                        method_defs[node] = {"node": node}
                        logger.debug(f"Found method/function definition: {capture_name}")
                    # 支持 function.name (C/C++) 和 method.name (其他语言)
                    elif ".name" in capture_name and ("function" in capture_name or "method" in capture_name):
                        for method_node in method_defs:
                            if self._node_contains(method_node, node):
                                method_defs[method_node]["name"] = content[node.start_byte:node.end_byte]
                                logger.debug(f"Found method/function name: {content[node.start_byte:node.end_byte]}")
                                break

                logger.debug(f"Processing {len(method_defs)} method/function definitions")
                for method_node, info in method_defs.items():
                    name = info.get("name", "Unknown")
                    if name == "Unknown":
                        logger.warning(f"Method without name found at line {method_node.start_point[0] + 1}")
                        continue

                    method_code = content[method_node.start_byte:method_node.end_byte]

                    # 检查方法是否在类中
                    if not self._is_in_any_class(method_node, classes):
                        method_symbol = MethodSymbol(
                            name=name,
                            start_line=method_node.start_point[0] + 1,
                            end_line=method_node.end_point[0] + 1,
                            code=method_code,
                        )
                        standalone_methods.append(method_symbol)
                        logger.debug(f"Added standalone method: {name}")

            except Exception as e:
                logger.warning(f"Failed to extract methods: {e}", exc_info=True)

        return classes, standalone_methods

    def _extract_methods_in_class(
        self,
        class_node: Node,
        content: str,
        class_name: str,
    ) -> List[MethodSymbol]:
        """提取类中的方法.

        Args:
            class_node: 类节点
            content: 原始内容
            class_name: 类名

        Returns:
            方法列表
        """
        methods: List[MethodSymbol] = []

        queries = self._get_queries_for_ext(self.language_ext)
        if not queries:
            return methods

        # 使用查询提取类中的方法
        method_pattern = queries.get("method_in_class") or queries.get("method")
        if not method_pattern:
            return methods

        try:
            capture_list = self._exec_query(method_pattern, class_node)

            method_defs = {}
            for node, capture_name in capture_list:
                if "method.def" in capture_name:
                    method_defs[node] = {"node": node}
                elif "method.name" in capture_name:
                    for method_node in method_defs:
                        if self._node_contains(method_node, node):
                            method_defs[method_node]["name"] = content[node.start_byte:node.end_byte]
                            break

            for method_node, info in method_defs.items():
                # 确保方法节点在类节点内
                if not self._node_contains(class_node, method_node):
                    continue

                name = info.get("name", "Unknown")
                method_code = content[method_node.start_byte:method_node.end_byte]

                method_symbol = MethodSymbol(
                    name=name,
                    start_line=method_node.start_point[0] + 1,
                    end_line=method_node.end_point[0] + 1,
                    code=method_code,
                )
                methods.append(method_symbol)

        except Exception as e:
            logger.warning(f"Failed to extract methods from class {class_name}: {e}")

        return methods

    def _extract_imports(self, root_node: Node) -> List[str]:
        """提取导入语句.

        Args:
            root_node: 根节点

        Returns:
            导入列表
        """
        imports: List[str] = []

        queries = self._get_queries_for_ext(self.language_ext)
        if not queries:
            return imports

        # 处理标准 import 查询
        import_query = queries.get("import")
        if import_query:
            try:
                capture_list = self._exec_query(import_query, root_node)

                for node, capture_name in capture_list:
                    if "import" in capture_name:
                        import_text = node.text.decode("utf8") if node.text else ""
                        imports.append(import_text)

            except Exception as e:
                logger.warning(f"Failed to extract imports: {e}")

        # 处理 C/C++ include 查询
        include_query = queries.get("include")
        if include_query:
            try:
                capture_list = self._exec_query(include_query, root_node)

                for node, capture_name in capture_list:
                    if "include" in capture_name:
                        include_text = node.text.decode("utf8") if node.text else ""
                        imports.append(include_text)

            except Exception as e:
                logger.warning(f"Failed to extract includes: {e}")

        return imports

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

    def _is_method_in_class(
        self,
        method: MethodSymbol,
        class_symbol: ClassSymbol,
    ) -> bool:
        """检查方法是否在类中.

        Args:
            method: 方法
            class_symbol: 类

        Returns:
            是否在类中
        """
        return (
            method.start_line >= class_symbol.start_line
            and method.end_line <= class_symbol.end_line
        )

    def _is_in_any_class(self, node: Node, classes: List[ClassSymbol]) -> bool:
        """检查节点是否在任何一个类中.

        Args:
            node: 节点
            classes: 类列表

        Returns:
            是否在类中
        """
        node_start = node.start_point[0] + 1
        node_end = node.end_point[0] + 1

        for class_symbol in classes:
            if (
                node_start >= class_symbol.start_line
                and node_end <= class_symbol.end_line
            ):
                return True

        return False


def get_parser_for_file(file_path: str) -> Optional[TreeSitterParser]:
    """根据文件路径获取对应的解析器.

    Args:
        file_path: 文件路径

    Returns:
        解析器实例或None
    """
    ext = Path(file_path).suffix.lower()

    if ext in TreeSitterParser.LANGUAGE_MAP:
        return TreeSitterParser(ext)

    return None
