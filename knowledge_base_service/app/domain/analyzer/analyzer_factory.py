"""代码分析器工厂.

根据文件类型创建对应的代码分析器实例。
"""

from pathlib import Path
from typing import Dict, List, Optional, Type

from app.domain.analyzer.code_analyzer import CodeAnalyzer
from app.domain.analyzer.python_analyzer import PythonAnalyzer
from app.domain.analyzer.java_analyzer import JavaAnalyzer
from app.domain.analyzer.javascript_analyzer import JavaScriptAnalyzer, TypeScriptAnalyzer
from app.domain.analyzer.c_cpp_analyzer import CAnalyzer, CppAnalyzer
from app.domain.analyzer.go_analyzer import GoAnalyzer
from app.domain.analyzer.rust_analyzer import RustAnalyzer

# 分析器注册表：扩展名 -> 分析器类
ANALYZER_REGISTRY: Dict[str, Type[CodeAnalyzer]] = {
    # Python
    ".py": PythonAnalyzer,
    ".pyi": PythonAnalyzer,
    # Java
    ".java": JavaAnalyzer,
    # JavaScript
    ".js": JavaScriptAnalyzer,
    ".jsx": JavaScriptAnalyzer,
    ".mjs": JavaScriptAnalyzer,
    # TypeScript
    ".ts": TypeScriptAnalyzer,
    ".tsx": TypeScriptAnalyzer,
    # C
    ".c": CAnalyzer,
    ".h": CAnalyzer,
    # C++
    ".cpp": CppAnalyzer,
    ".cc": CppAnalyzer,
    ".cxx": CppAnalyzer,
    ".hpp": CppAnalyzer,
    ".hh": CppAnalyzer,
    # Go
    ".go": GoAnalyzer,
    # Rust
    ".rs": RustAnalyzer,
}

# 语言名称到分析器类的映射
LANGUAGE_ANALYZER_MAP: Dict[str, Type[CodeAnalyzer]] = {
    "python": PythonAnalyzer,
    "java": JavaAnalyzer,
    "javascript": JavaScriptAnalyzer,
    "typescript": TypeScriptAnalyzer,
    "c": CAnalyzer,
    "cpp": CppAnalyzer,
    "go": GoAnalyzer,
    "rust": RustAnalyzer,
}


def get_analyzer_for_file(file_path: str) -> Optional[CodeAnalyzer]:
    """根据文件路径获取对应的代码分析器.

    Args:
        file_path: 文件路径

    Returns:
        对应的代码分析器实例，如果不支持则返回 None

    Example:
        >>> analyzer = get_analyzer_for_file("src/main.py")
        >>> isinstance(analyzer, PythonAnalyzer)
        True
    """
    ext = Path(file_path).suffix.lower()
    analyzer_class = ANALYZER_REGISTRY.get(ext)

    if analyzer_class:
        return analyzer_class()

    return None


def get_analyzer_by_language(language: str) -> Optional[CodeAnalyzer]:
    """根据语言名称获取对应的代码分析器.

    Args:
        language: 语言名称（如 'python', 'java'）

    Returns:
        对应的代码分析器实例，如果不支持则返回 None

    Example:
        >>> analyzer = get_analyzer_by_language("python")
        >>> isinstance(analyzer, PythonAnalyzer)
        True
    """
    normalized_language = language.lower()
    analyzer_class = LANGUAGE_ANALYZER_MAP.get(normalized_language)

    if analyzer_class:
        return analyzer_class()

    return None


def get_analyzer_for_extension(extension: str) -> Optional[CodeAnalyzer]:
    """根据文件扩展名获取对应的代码分析器.

    Args:
        extension: 文件扩展名（如 '.py', '.java'）

    Returns:
        对应的代码分析器实例，如果不支持则返回 None

    Example:
        >>> analyzer = get_analyzer_for_extension(".py")
        >>> isinstance(analyzer, PythonAnalyzer)
        True
    """
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext

    analyzer_class = ANALYZER_REGISTRY.get(ext)

    if analyzer_class:
        return analyzer_class()

    return None


def is_supported_file(file_path: str) -> bool:
    """检查文件是否受支持.

    Args:
        file_path: 文件路径

    Returns:
        是否受支持

    Example:
        >>> is_supported_file("main.py")
        True
        >>> is_supported_file("main.txt")
        False
    """
    ext = Path(file_path).suffix.lower()
    return ext in ANALYZER_REGISTRY


def get_supported_extensions() -> List[str]:
    """获取所有支持的文件扩展名列表.

    Returns:
        支持的扩展名列表
    """
    return list(ANALYZER_REGISTRY.keys())


def get_supported_languages() -> List[str]:
    """获取所有支持的语言名称列表.

    Returns:
        支持的语言名称列表
    """
    return list(LANGUAGE_ANALYZER_MAP.keys())


def register_analyzer(
    extension: str,
    analyzer_class: Type[CodeAnalyzer],
) -> None:
    """注册新的分析器.

    Args:
        extension: 文件扩展名（如 '.py'）
        analyzer_class: 分析器类

    Example:
        >>> register_analyzer(".rb", RubyAnalyzer)
    """
    ext = extension.lower()
    if not ext.startswith("."):
        ext = "." + ext

    ANALYZER_REGISTRY[ext] = analyzer_class

    # 更新语言映射
    instance = analyzer_class()
    LANGUAGE_ANALYZER_MAP[instance.language_name] = analyzer_class


class AnalyzerFactory:
    """代码分析器工厂类.

    提供更面向对象的方式来获取分析器实例。
    """

    @staticmethod
    def for_file(file_path: str) -> Optional[CodeAnalyzer]:
        """根据文件路径获取分析器."""
        return get_analyzer_for_file(file_path)

    @staticmethod
    def for_language(language: str) -> Optional[CodeAnalyzer]:
        """根据语言名称获取分析器."""
        return get_analyzer_by_language(language)

    @staticmethod
    def for_extension(extension: str) -> Optional[CodeAnalyzer]:
        """根据扩展名获取分析器."""
        return get_analyzer_for_extension(extension)

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """检查文件是否受支持."""
        return is_supported_file(file_path)

    @staticmethod
    def supported_extensions() -> List[str]:
        """获取支持的扩展名列表."""
        return get_supported_extensions()

    @staticmethod
    def supported_languages() -> List[str]:
        """获取支持的语言列表."""
        return get_supported_languages()
