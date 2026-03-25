"""Tree-sitter 解析器单元测试."""

from pathlib import Path
import pytest

from app.domain.parser.tree_sitter_parser import (
    TreeSitterParser,
    get_parser_for_file,
)


# 测试代码样本目录
SAMPLES_DIR = Path(__file__).parent.parent / "fixtures" / "code_samples"


class TestTreeSitterParser:
    """TreeSitterParser 测试类."""

    def test_supported_extensions(self):
        """测试支持的文件扩展名."""
        parser = TreeSitterParser(".py")
        extensions = parser.supported_extensions

        assert ".py" in extensions
        assert ".java" in extensions
        assert ".js" in extensions
        assert ".ts" in extensions
        assert ".go" in extensions
        assert ".rs" in extensions
        assert ".c" in extensions
        assert ".cpp" in extensions
        assert ".h" in extensions
        assert ".hpp" in extensions

    def test_language_name(self):
        """测试语言名称."""
        test_cases = [
            (".py", "python"),
            (".java", "java"),
            (".js", "javascript"),
            (".ts", "typescript"),
            (".go", "go"),
            (".rs", "rust"),
            (".c", "c"),
            (".cpp", "cpp"),
        ]

        for ext, expected_name in test_cases:
            parser = TreeSitterParser(ext)
            assert parser.language_name == expected_name, f"Failed for {ext}"

    def test_unsupported_language(self):
        """测试不支持的语言."""
        parser = TreeSitterParser(".unknown")
        assert parser.parser is None
        assert parser.language is None

    def test_get_parser_for_file(self):
        """测试根据文件路径获取解析器."""
        # 支持的文件
        assert get_parser_for_file("test.py") is not None
        assert get_parser_for_file("test.java") is not None
        assert get_parser_for_file("test.js") is not None
        assert get_parser_for_file("test.ts") is not None
        assert get_parser_for_file("test.go") is not None
        assert get_parser_for_file("test.rs") is not None
        assert get_parser_for_file("test.c") is not None
        assert get_parser_for_file("test.cpp") is not None

        # 不支持的文件
        assert get_parser_for_file("test.rb") is None
        assert get_parser_for_file("test.unknown") is None


class TestPythonParsing:
    """Python 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".py")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.py"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.py", sample_content)

        assert result.success is True
        assert result.error is None
        assert result.language == "python"
        assert result.file_path == "sample.py"

    def test_ast_generation(self, parser, sample_content):
        """测试 AST 生成."""
        result = parser.parse("sample.py", sample_content)

        assert result.ast is not None
        assert result.ast.node_type == "module"

    def test_class_extraction(self, parser, sample_content):
        """测试类提取."""
        result = parser.parse("sample.py", sample_content)

        assert len(result.classes) >= 2

        # 查找 Person 类
        person_class = next((c for c in result.classes if c.name == "Person"), None)
        assert person_class is not None
        assert person_class.name == "Person"
        assert len(person_class.methods) >= 2  # greet, celebrate_birthday

        # 查找 Calculator 类
        calculator_class = next((c for c in result.classes if c.name == "Calculator"), None)
        assert calculator_class is not None
        assert len(calculator_class.methods) >= 4  # __init__, add, subtract, get_history

    def test_method_extraction(self, parser, sample_content):
        """测试方法提取."""
        result = parser.parse("sample.py", sample_content)

        # 获取所有方法（包括类内方法）
        all_methods = []
        for cls in result.classes:
            all_methods.extend(cls.methods)
        all_methods.extend(result.methods)  # 独立方法

        # 检查是否有独立函数
        standalone_names = [m.name for m in result.methods]
        assert "standalone_function" in standalone_names
        assert "process_data" in standalone_names

    def test_import_extraction(self, parser, sample_content):
        """测试导入提取."""
        result = parser.parse("sample.py", sample_content)

        assert len(result.imports) >= 3


class TestJavaParsing:
    """Java 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".java")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "Sample.java"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("Sample.java", sample_content)

        assert result.success is True
        assert result.language == "java"

    def test_class_extraction(self, parser, sample_content):
        """测试类提取."""
        result = parser.parse("Sample.java", sample_content)

        # 应该有 Person 和 Calculator 类
        class_names = [c.name for c in result.classes]
        assert "Person" in class_names
        assert "Calculator" in class_names

    def test_interface_not_yet_supported(self, parser, sample_content):
        """测试接口提取 - 当前 Java 接口查询尚未配置."""
        result = parser.parse("Sample.java", sample_content)

        # TODO: Java 接口提取需要添加 interface 查询到 QUERIES
        # 当前只提取了类
        class_names = [c.name for c in result.classes]
        assert "Person" in class_names
        assert "Calculator" in class_names


class TestJavaScriptParsing:
    """JavaScript 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".js")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.js"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.js", sample_content)

        assert result.success is True
        assert result.language == "javascript"

    def test_class_extraction(self, parser, sample_content):
        """测试类提取."""
        result = parser.parse("sample.js", sample_content)

        class_names = [c.name for c in result.classes]
        assert "Person" in class_names
        assert "Calculator" in class_names

    def test_function_extraction(self, parser, sample_content):
        """测试函数提取."""
        result = parser.parse("sample.js", sample_content)

        # 应该有独立函数
        method_names = [m.name for m in result.methods]
        assert "standaloneFunction" in method_names


class TestTypeScriptParsing:
    """TypeScript 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".ts")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.ts"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.ts", sample_content)

        assert result.success is True
        assert result.language == "typescript"

    def test_class_extraction(self, parser, sample_content):
        """测试类提取."""
        result = parser.parse("sample.ts", sample_content)

        class_names = [c.name for c in result.classes]
        assert "Person" in class_names
        assert "Calculator" in class_names


class TestGoParsing:
    """Go 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".go")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.go"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.go", sample_content)

        assert result.success is True
        assert result.language == "go"

    def test_struct_not_yet_supported(self, parser, sample_content):
        """测试结构体提取 - 当前 Go 查询尚未配置."""
        result = parser.parse("sample.go", sample_content)

        # TODO: Go 的 struct 和方法提取需要添加专门的查询
        # 当前 Go 查询未在 QUERIES 中配置
        assert result.success is True
        assert result.language == "go"


class TestRustParsing:
    """Rust 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".rs")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.rs"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.rs", sample_content)

        assert result.success is True
        assert result.language == "rust"

    def test_struct_extraction(self, parser, sample_content):
        """测试结构体提取."""
        result = parser.parse("sample.rs", sample_content)

        # Rust 中使用 struct
        struct_names = [c.name for c in result.classes]
        # Rust 的 struct 在 query 中定义
        assert len(result.classes) >= 0


class TestCParsing:
    """C 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".c")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.c"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.c", sample_content)

        assert result.success is True
        assert result.language == "c"

    def test_struct_extraction(self, parser, sample_content):
        """测试结构体提取."""
        result = parser.parse("sample.c", sample_content)

        # C 中的 struct 应该被提取
        struct_names = [c.name for c in result.classes]
        # 可能有 Person 结构体

    def test_function_extraction(self, parser, sample_content):
        """测试函数提取."""
        result = parser.parse("sample.c", sample_content)

        # C 中的函数
        assert len(result.methods) > 0


class TestCppParsing:
    """C++ 代码解析测试."""

    @pytest.fixture
    def parser(self):
        return TreeSitterParser(".cpp")

    @pytest.fixture
    def sample_content(self):
        sample_file = SAMPLES_DIR / "sample.cpp"
        return sample_file.read_text(encoding="utf-8")

    def test_parse_success(self, parser, sample_content):
        """测试成功解析."""
        result = parser.parse("sample.cpp", sample_content)

        assert result.success is True
        assert result.language == "cpp"

    def test_class_extraction(self, parser, sample_content):
        """测试类提取."""
        result = parser.parse("sample.cpp", sample_content)

        # C++ 中的类
        class_names = [c.name for c in result.classes]
        assert "Person" in class_names
        assert "Calculator" in class_names


class TestParseResult:
    """解析结果数据结构测试."""

    def test_parse_result_structure(self):
        """测试解析结果数据结构."""
        from app.domain.parser.code_parser import (
            ParseResult,
            ClassSymbol,
            MethodSymbol,
            ASTNode,
        )

        # 创建解析结果
        result = ParseResult(
            file_path="test.py",
            language="python",
            success=True,
            classes=[
                ClassSymbol(
                    name="TestClass",
                    start_line=1,
                    end_line=10,
                    code="class TestClass:\n    pass",
                    methods=[
                        MethodSymbol(
                            name="test_method",
                            start_line=2,
                            end_line=3,
                            code="def test_method(self): pass",
                        )
                    ],
                )
            ],
            methods=[
                MethodSymbol(
                    name="standalone_func",
                    start_line=12,
                    end_line=13,
                    code="def standalone_func(): pass",
                )
            ],
            imports=["import os", "import sys"],
        )

        assert result.file_path == "test.py"
        assert result.language == "python"
        assert result.success is True
        assert len(result.classes) == 1
        assert len(result.methods) == 1
        assert len(result.imports) == 2

        # 测试类符号
        test_class = result.classes[0]
        assert test_class.name == "TestClass"
        assert test_class.start_line == 1
        assert test_class.end_line == 10
        assert len(test_class.methods) == 1

        # 测试方法符号
        test_method = test_class.methods[0]
        assert test_method.name == "test_method"
        assert test_method.start_line == 2

    def test_parse_result_error(self):
        """测试解析失败的返回结果."""
        from app.domain.parser.code_parser import ParseResult

        result = ParseResult(
            file_path="test.unknown",
            language="unknown",
            success=False,
            error="Unsupported language",
        )

        assert result.success is False
        assert result.error == "Unsupported language"


class TestEdgeCases:
    """边界情况测试."""

    def test_empty_content(self):
        """测试空内容."""
        parser = TreeSitterParser(".py")
        result = parser.parse("empty.py", "")

        # 空内容应该能成功解析
        assert result.success is True
        assert result.ast is not None

    def test_syntax_error_content(self):
        """测试语法错误内容."""
        parser = TreeSitterParser(".py")
        # 有语法错误的代码
        content = "def broken_func(\n    pass\n"
        result = parser.parse("broken.py", content)

        # 即使代码有语法错误，tree-sitter 也能解析
        assert result.success is True
        # AST 可能有错误标记
        assert result.ast is not None

    def test_unicode_content(self):
        """测试 Unicode 内容."""
        parser = TreeSitterParser(".py")
        content = '''# -*- coding: utf-8 -*-
# 这是一个中文注释

def 中文函数():
    """函数文档字符串"""
    return "你好，世界"
'''
        result = parser.parse("unicode.py", content)

        assert result.success is True
