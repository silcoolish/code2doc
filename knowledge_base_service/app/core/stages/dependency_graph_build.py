"""依赖图构建阶段处理器.

基于已创建的结构图，分析 File 和 Method 节点的代码内容：
1. 分析 File 节点的 import/include 引用，创建对其他 File 节点的 USE 关系
2. 分析 Method 节点的方法调用，创建对其他 Method 节点的 CALL 关系
"""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)


class DependencyGraphBuildStage(PipelineStageHandler):
    """依赖图构建阶段处理器.

    从结构图中查询 File 和 Method 节点，分析代码内容提取依赖关系。

    Input (context.data):
        - node_ids: Dict - 包含 file_ids, method_ids 等

    Output (context.data):
        - dependencies: Dict - 创建的依赖关系统计
          {file_uses: int, method_calls: int}

    Side Effects:
        - 在 Neo4j 中创建 File 之间的 USE 关系
        - 在 Neo4j 中创建 Method 之间的 CALL 关系
    """

    stage = PipelineStage.DEPENDENCY_GRAPH_BUILD

    def __init__(self):
        self._neo4j: Optional[GraphDatabaseClient] = None

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行依赖图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self._neo4j = get_graph_db_client()
            repo_name = context.repo_name

            # 1. 构建文件依赖（USE 关系）
            file_uses = await self._build_file_dependencies(repo_name)

            # 2. 构建方法调用（CALL 关系）
            method_calls = await self._build_method_calls(repo_name)

            # 保存结果到上下文
            context.data["dependencies"] = {
                "file_uses": file_uses,
                "method_calls": method_calls,
            }

            logger.info(
                f"Dependency graph built: {file_uses} file uses, {method_calls} method calls"
            )

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Built {file_uses} file uses, {method_calls} method calls",
                metadata={
                    "file_uses": file_uses,
                    "method_calls": method_calls,
                },
            )

        except Exception as e:
            logger.exception(f"Dependency graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _build_file_dependencies(self, repo_name: str) -> int:
        """构建文件间的 USE 依赖关系.

        分析 File 节点的 import/include 语句，匹配到对应的文件。

        Args:
            repo_name: 仓库名称

        Returns:
            创建的 USE 关系数量
        """
        # 获取所有代码文件
        files = await self._get_code_files(repo_name)
        if not files:
            return 0

        # 构建文件路径索引
        file_path_index = self._build_file_path_index(files)

        created_count = 0
        seen_relations: Set[Tuple[str, str]] = set()

        for file_node in files:
            file_id = file_node.get("id")
            file_path = file_node.get("path", "")
            code = file_node.get("code", "")
            language = file_node.get("language", "")

            if not file_id or not code:
                continue

            # 提取 import 引用
            imports = self._extract_imports(code, language)

            for import_stmt in imports:
                # 查找引用的目标文件
                target_id = self._resolve_import(import_stmt, file_path, file_path_index)
                if target_id and target_id != file_id:
                    rel_key = (file_id, target_id)
                    if rel_key not in seen_relations:
                        seen_relations.add(rel_key)
                        success = await self._create_use_relation(file_id, target_id)
                        if success:
                            created_count += 1

        return created_count

    async def _build_method_calls(self, repo_name: str) -> int:
        """构建方法间的 CALL 调用关系.

        分析 Method 节点的代码内容，提取方法调用。

        Args:
            repo_name: 仓库名称

        Returns:
            创建的 CALL 关系数量
        """
        # 获取所有方法
        methods = await self._get_all_methods(repo_name)
        if not methods:
            return 0

        # 构建方法名索引
        method_name_index = self._build_method_name_index(methods)

        created_count = 0
        seen_relations: Set[Tuple[str, str]] = set()

        for method in methods:
            source_id = method.get("id")
            code = method.get("code", "")
            language = method.get("language", "")
            file_path = method.get("file_path", "")

            if not source_id or not code:
                continue

            # 提取方法调用
            call_names = self._extract_method_calls(code, language)

            for call_name in call_names:
                # 查找目标方法
                target_ids = method_name_index.get(call_name, [])

                # 优先匹配同文件的方法
                same_file_targets = [
                    tid for tid in target_ids
                    if self._is_method_in_file(tid, file_path)
                ]

                # 如果同文件有匹配，优先使用；否则使用全局匹配
                targets = same_file_targets if same_file_targets else target_ids

                for target_id in targets:
                    if target_id != source_id:
                        rel_key = (source_id, target_id)
                        if rel_key not in seen_relations:
                            seen_relations.add(rel_key)
                            success = await self._create_call_relation(source_id, target_id)
                            if success:
                                created_count += 1

        return created_count

    async def _get_code_files(self, repo_name: str) -> List[Dict]:
        """获取所有代码文件节点.

        Args:
            repo_name: 仓库名称

        Returns:
            File 节点列表
        """
        query = """
        MATCH (f:File)
        WHERE f.repo = $repo_name AND f.fileType = 'code'
        RETURN f.id as id, f.path as path, f.code as code, f.suffix as suffix
        """
        result = await self._neo4j.execute_query(query, {"repo_name": repo_name})

        # 添加 language 字段
        for file_node in result:
            suffix = file_node.get("suffix", "").lower()
            language_map = {
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
            }
            file_node["language"] = language_map.get(suffix, "")

        return result

    async def _get_all_methods(self, repo_name: str) -> List[Dict]:
        """获取所有 Method 节点.

        Args:
            repo_name: 仓库名称

        Returns:
            Method 节点列表
        """
        query = """
        MATCH (m:Method)
        WHERE m.repo = $repo_name
        RETURN m.id as id, m.name as name, m.code as code,
               m.language as language, m.filePath as file_path
        """
        return await self._neo4j.execute_query(query, {"repo_name": repo_name})

    def _build_file_path_index(self, files: List[Dict]) -> Dict[str, str]:
        """构建文件路径索引.

        Args:
            files: 文件节点列表

        Returns:
            路径到ID的映射
        """
        index = {}
        for f in files:
            path = f.get("path", "")
            file_id = f.get("id", "")
            if path and file_id:
                index[path] = file_id
                # 也添加文件名索引
                filename = Path(path).name
                if filename not in index:
                    index[filename] = file_id
        return index

    def _build_method_name_index(self, methods: List[Dict]) -> Dict[str, List[str]]:
        """构建方法名索引.

        Args:
            methods: 方法节点列表

        Returns:
            方法名到ID列表的映射
        """
        index: Dict[str, List[str]] = {}
        for m in methods:
            name = m.get("name", "")
            method_id = m.get("id", "")
            if name and method_id:
                if name not in index:
                    index[name] = []
                index[name].append(method_id)
        return index

    def _is_method_in_file(self, method_id: str, file_path: str) -> bool:
        """检查方法是否属于指定文件.

        Args:
            method_id: 方法ID
            file_path: 文件路径

        Returns:
            是否属于该文件
        """
        # 方法ID格式: method_{repo}_{file_path}_{method_name}
        # 或 method_{repo}_{file_path}_{class_name}_{method_name}
        return file_path in method_id

    def _extract_imports(self, code: str, language: str) -> List[str]:
        """从代码中提取 import 语句.

        Args:
            code: 代码内容
            language: 语言类型

        Returns:
            import 模块名列表
        """
        imports = []

        if language == "python":
            # Python: import x, from x import y
            patterns = [
                r"^\s*import\s+([\w.]+)",
                r"^\s*from\s+([\w.]+)\s+import",
            ]
        elif language in ("java", "kotlin"):
            # Java: import x.y.z
            patterns = [r"^\s*import\s+([\w.]+)"]
        elif language in ("javascript", "typescript"):
            # JS/TS: import x from 'y', require('y')
            patterns = [
                r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]",
                r"require\(['\"]([^'\"]+)['\"]\)",
            ]
        elif language == "go":
            # Go: import "x", import ( "x" )
            patterns = [r'import\s*\(?\s*["\']([^"\']+)["\']']
        elif language == "rust":
            # Rust: use x::y, extern crate x
            patterns = [
                r"^\s*use\s+([\w:]+)",
                r"^\s*extern\s+crate\s+(\w+)",
            ]
        elif language in ("c", "cpp"):
            # C/C++: #include "x" or #include <x>
            patterns = [r'#\s*include\s+["<]([^">]+)[">]']
        else:
            return imports

        for pattern in patterns:
            for match in re.finditer(pattern, code, re.MULTILINE):
                module = match.group(1).strip()
                if module:
                    imports.append(module)

        return imports

    def _resolve_import(
        self,
        import_stmt: str,
        current_file: str,
        file_path_index: Dict[str, str],
    ) -> Optional[str]:
        """解析 import 语句，找到对应的文件ID.

        Args:
            import_stmt: import 语句内容
            current_file: 当前文件路径
            file_path_index: 文件路径索引

        Returns:
            目标文件ID或 None
        """
        # 尝试直接匹配
        if import_stmt in file_path_index:
            return file_path_index[import_stmt]

        # 提取模块名并尝试匹配文件名
        parts = import_stmt.replace(".", "/").split("/")
        module_name = parts[-1] if parts else import_stmt

        # 尝试匹配文件名（带扩展名）
        for ext in [".py", ".java", ".js", ".ts", ".go", ".rs", ".c", ".h", ".cpp", ".hpp"]:
            filename = module_name + ext
            if filename in file_path_index:
                return file_path_index[filename]

        # 尝试匹配路径中包含模块名
        for path, file_id in file_path_index.items():
            if module_name in path:
                return file_id

        return None

    def _extract_method_calls(self, code: str, language: str) -> List[str]:
        """从方法代码中提取方法调用.

        Args:
            code: 方法代码
            language: 语言类型

        Returns:
            被调用的方法名列表
        """
        calls = []

        if not code:
            return calls

        # 简单正则匹配方法调用
        # 匹配 pattern: identifier(arg) 或 obj.method(arg) 或 self.method(arg)
        if language in ("python", "ruby"):
            # Python: func(), self.func(), obj.func()
            pattern = r"(?<!\w)([a-zA-Z_]\w*)\s*\("
        elif language in ("java", "javascript", "typescript", "c", "cpp", "go"):
            # Java/JS/TS/C/Go: func(), this.func(), obj.func()
            pattern = r"(?<!\w)([a-zA-Z_]\w*)\s*\("
        elif language == "rust":
            # Rust: func(), self.func()
            pattern = r"(?<!\w)([a-zA-Z_]\w*)\s*\("
        else:
            pattern = r"(?<!\w)([a-zA-Z_]\w*)\s*\("

        # 查找所有匹配
        matches = re.finditer(pattern, code)

        # 排除关键字和常见内置函数
        exclude = {
            "if", "while", "for", "switch", "catch", "return",
            "print", "println", "printf", "len", "range", "enumerate",
            "map", "filter", "reduce", "sorted", "reversed",
            "int", "str", "float", "bool", "list", "dict", "set", "tuple",
            "new", "sizeof", "typeof", "instanceof",
        }

        for match in matches:
            name = match.group(1)
            if name and name not in exclude and not name.startswith("_"):
                calls.append(name)

        return calls

    async def _create_use_relation(self, from_id: str, to_id: str) -> bool:
        """创建 USE 关系.

        Args:
            from_id: 源文件ID
            to_id: 目标文件ID

        Returns:
            是否成功创建
        """
        try:
            return await self._neo4j.create_relationship(
                from_label="File",
                from_key="id",
                from_value=from_id,
                to_label="File",
                to_key="id",
                to_value=to_id,
                rel_type="USE",
            )
        except Exception as e:
            logger.warning(f"Failed to create USE relation {from_id} -> {to_id}: {e}")
            return False

    async def _create_call_relation(self, from_id: str, to_id: str) -> bool:
        """创建 CALL 关系.

        Args:
            from_id: 源方法ID
            to_id: 目标方法ID

        Returns:
            是否成功创建
        """
        try:
            return await self._neo4j.create_relationship(
                from_label="Method",
                from_key="id",
                from_value=from_id,
                to_label="Method",
                to_key="id",
                to_value=to_id,
                rel_type="CALL",
            )
        except Exception as e:
            logger.warning(f"Failed to create CALL relation {from_id} -> {to_id}: {e}")
            return False
