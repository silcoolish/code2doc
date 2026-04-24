"""依赖图构建阶段处理器.

基于已创建的结构图，分析 File 和 Method 节点的代码内容：
1. 分析 File 节点的 import/include 引用，创建对其他 File 节点的 USE 关系
2. 分析 Method 节点的方法调用，创建对其他 Method 节点的 CALL 关系
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.analyzer.analyzer_factory import get_analyzer_by_language
from app.domain.analyzer.code_analyzer import ImportInfo, MethodCallInfo
from app.domain.graph import GraphHelper
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_graph_db_client

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
    weight = 2.0  # 依赖分析

    def __init__(self):
        graph_db = get_graph_db_client()
        self.graph_helper = GraphHelper(graph_db)

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行依赖图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            repo_id = getattr(context, 'repo_id', context.repo_name)

            # 1. 构建文件依赖（USE 关系）
            context.stage_msg = "正在分析文件依赖关系..."
            file_uses = await self._build_file_dependencies(repo_id)

            # 2. 构建方法调用（CALL 关系）
            context.stage_msg = "正在分析方法调用关系..."
            method_calls = await self._build_method_calls(repo_id)

            # 保存结果到上下文
            context.data["dependencies"] = {
                "file_uses": file_uses,
                "method_calls": method_calls,
            }

            context.stage_msg = f"依赖图构建完成：{file_uses} 个文件依赖, {method_calls} 个方法调用"
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

    async def _build_file_dependencies(self, repo_id: str) -> int:
        """构建文件间的 USE 依赖关系.

        分析 File 节点的 import/include 语句，匹配到对应的文件，
        最后统一批量创建关系（减少网络往返）。

        Args:
            repo_id: 仓库ID

        Returns:
            创建的 USE 关系数量
        """
        # 获取所有代码文件
        files = await self.graph_helper.graph_db.get_code_files(repo_id)
        if not files:
            return 0

        # 构建文件路径索引
        file_path_index = self._build_file_path_index(files)

        seen_relations: Set[Tuple[str, str]] = set()
        relations_to_create: List[Tuple[str, str]] = []

        for file_node in files:
            file_id = file_node.get("id")
            file_path = file_node.get("path", "")
            code = file_node.get("code", "")
            language = file_node.get("language", "")

            if not file_id or not code:
                continue

            # 获取对应语言的分析器
            analyzer = get_analyzer_by_language(language)
            if not analyzer:
                continue

            # 提取 import 引用
            import_infos = analyzer.extract_imports(code, file_path)

            for import_info in import_infos:
                # 查找引用的目标文件
                target_id = analyzer.resolve_import(import_info, file_path, file_path_index)
                if target_id and target_id != file_id:
                    rel_key = (file_id, target_id)
                    if rel_key not in seen_relations:
                        seen_relations.add(rel_key)
                        relations_to_create.append(rel_key)

        # 批量创建 USE 关系（单次 UNWIND 查询）
        if relations_to_create:
            created = await self.graph_helper.batch_create_use_relationships(
                relations_to_create
            )
            logger.info(f"Batch created {created} USE relationships")
            return created
        return 0

    async def _build_method_calls(self, repo_id: str) -> int:
        """构建方法间的 CALL 调用关系.

        分析 Method 节点的代码内容，提取方法调用，
        最后统一批量创建关系（减少网络往返）。

        Args:
            repo_id: 仓库ID

        Returns:
            创建的 CALL 关系数量
        """
        # 获取所有方法
        methods = await self.graph_helper.graph_db.get_all_methods(repo_id)
        if not methods:
            return 0

        # 构建方法名索引
        method_name_index = self._build_method_name_index(methods)

        seen_relations: Set[Tuple[str, str]] = set()
        relations_to_create: List[Tuple[str, str]] = []

        for method in methods:
            source_id = method.get("id")
            code = method.get("code", "")
            language = method.get("language", "")
            file_path = method.get("file_path", "")
            method_name = method.get("name", "")

            if not source_id or not code:
                continue

            # 获取对应语言的分析器
            analyzer = get_analyzer_by_language(language)
            if not analyzer:
                continue

            # 提取方法调用
            call_infos = analyzer.extract_method_calls(code, method_name, file_path)

            for call_info in call_infos:
                call_name = call_info.method_name

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
                            relations_to_create.append(rel_key)

        # 批量创建 CALL 关系（单次 UNWIND 查询）
        if relations_to_create:
            created = await self.graph_helper.batch_create_call_relationships(
                relations_to_create
            )
            logger.info(f"Batch created {created} CALL relationships")
            return created
        return 0

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
