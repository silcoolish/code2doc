"""代码分析器模块.

提供多语言代码分析功能，包括：
1. 结构图构建阶段的代码解析
2. 依赖图构建阶段的 import 提取
3. 依赖图构建阶段的方法调用提取

Usage:
    from app.domain.analyzer import get_analyzer_for_file, AnalyzerFactory

    # 方式1：使用工厂函数
    analyzer = get_analyzer_for_file("src/main.py")
    if analyzer:
        result = analyzer.parse_for_structure("src/main.py", content)
        imports = analyzer.extract_imports(content)
        calls = analyzer.extract_method_calls(code)

    # 方式2：使用工厂类
    analyzer = AnalyzerFactory.for_file("src/main.py")
"""

from app.domain.analyzer.code_analyzer import (
    CodeAnalyzer,
    StructureParseResult,
    ParsedSymbol,
    ImportInfo,
    MethodCallInfo,
)
from app.domain.analyzer.analyzer_factory import (
    get_analyzer_for_file,
    get_analyzer_by_language,
    get_analyzer_for_extension,
    is_supported_file,
    get_supported_extensions,
    get_supported_languages,
    register_analyzer,
    AnalyzerFactory,
)
from app.domain.analyzer.python_analyzer import PythonAnalyzer
from app.domain.analyzer.java_analyzer import JavaAnalyzer
from app.domain.analyzer.javascript_analyzer import JavaScriptAnalyzer, TypeScriptAnalyzer
from app.domain.analyzer.c_cpp_analyzer import CAnalyzer, CppAnalyzer
from app.domain.analyzer.go_analyzer import GoAnalyzer
from app.domain.analyzer.rust_analyzer import RustAnalyzer

__all__ = [
    # 抽象基类
    "CodeAnalyzer",
    # 数据类
    "StructureParseResult",
    "ParsedSymbol",
    "ImportInfo",
    "MethodCallInfo",
    # 工厂函数
    "get_analyzer_for_file",
    "get_analyzer_by_language",
    "get_analyzer_for_extension",
    "is_supported_file",
    "get_supported_extensions",
    "get_supported_languages",
    "register_analyzer",
    "AnalyzerFactory",
    # 具体实现
    "PythonAnalyzer",
    "JavaAnalyzer",
    "JavaScriptAnalyzer",
    "TypeScriptAnalyzer",
    "CAnalyzer",
    "CppAnalyzer",
    "GoAnalyzer",
    "RustAnalyzer",
]
