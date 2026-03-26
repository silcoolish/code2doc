"""语义分析阶段处理器.

该阶段基于依赖图构建的结果，为代码节点生成语义摘要：
1. 为 Method 节点生成 summary（考虑 CALL 关系）
2. 为 Class 节点生成 summary（基于包含的 Method）
3. 为 File 节点生成 summary（代码文件基于 Class/Method，非代码文件基于内容）

生成后把 summary 属性保存到图节点中。
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.llm.client import get_llm_service
from app.infrastructure.db.base_client import GraphDatabaseClient
from app.infrastructure.db.neo4j_client import get_neo4j_client

logger = logging.getLogger(__name__)


class SemanticAnalysisStage(PipelineStageHandler):
    """语义分析阶段处理器.

    为 Method、Class、File 节点生成语义摘要。

    Input (context.data):
        - node_ids: Dict - 包含 file_ids, class_ids, method_ids

    Output (context.data):
        - semantic_analysis: Dict - 生成的摘要统计
          {methods_summarized: int, classes_summarized: int, files_summarized: int}

    Side Effects:
        - 在 Neo4j 中更新 Method/Class/File 节点的 summary 属性
    """

    stage = PipelineStage.SEMANTIC_ANALYSIS

    def __init__(self):
        self._neo4j: Optional[GraphDatabaseClient] = None
        self._llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行语义分析.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self._neo4j = get_neo4j_client()
            repo_name = context.repo_name

            # 1. 生成 Method 节点的 summary
            method_count = await self._generate_method_summaries(repo_name)

            # 2. 生成 Class 节点的 summary
            class_count = await self._generate_class_summaries(repo_name)

            # 3. 生成 File 节点的 summary
            file_count = await self._generate_file_summaries(repo_name)

            # 保存结果到上下文
            context.data["semantic_analysis"] = {
                "methods_summarized": method_count,
                "classes_summarized": class_count,
                "files_summarized": file_count,
            }

            logger.info(
                f"Semantic analysis completed: {method_count} methods, "
                f"{class_count} classes, {file_count} files summarized"
            )

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Generated summaries: {method_count} methods, "
                        f"{class_count} classes, {file_count} files",
                metadata={
                    "methods_summarized": method_count,
                    "classes_summarized": class_count,
                    "files_summarized": file_count,
                },
            )

        except Exception as e:
            logger.exception(f"Semantic analysis failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _generate_method_summaries(self, repo_name: str) -> int:
        """生成所有 Method 节点的 summary.

        使用拓扑排序处理 CALL 依赖关系，确保先生成被调用方法的 summary。

        Args:
            repo_name: 仓库名称

        Returns:
            生成的摘要数量
        """
        # 获取所有 method 及其 CALL 关系
        methods = await self._get_methods_with_calls(repo_name)
        if not methods:
            return 0

        # 构建依赖图
        method_graph = self._build_call_graph(methods)

        # 拓扑排序，确保依赖先处理
        sorted_methods = self._topological_sort(method_graph)

        # 已生成的 summary 缓存
        summary_cache: Dict[str, str] = {}

        count = 0
        for method_id in sorted_methods:
            method = method_graph[method_id]["data"]

            # 跳过已有 summary 的方法
            if method.get("summary"):
                summary_cache[method_id] = method["summary"]
                continue

            # 获取被调用方法的 summaries
            callee_ids = method_graph[method_id]["callees"]
            callee_summaries = []
            for callee_id in callee_ids:
                if callee_id in summary_cache:
                    callee_summaries.append(summary_cache[callee_id])

            # 生成 summary
            summary = await self._generate_method_summary(method, callee_summaries)
            if summary:
                await self._update_node_summary("Method", method_id, summary)
                summary_cache[method_id] = summary
                count += 1

        return count

    async def _get_methods_with_calls(self, repo_name: str) -> List[Dict]:
        """获取所有 Method 节点及其 CALL 关系.

        Args:
            repo_name: 仓库名称

        Returns:
            Method 节点列表，包含 code, docstring, language 和 calls 关系
        """
        query = """
        MATCH (m:Method)
        WHERE m.repo = $repo_name
        OPTIONAL MATCH (m)-[:CALL]->(callee:Method)
        RETURN m.id as id, m.code as code, m.docstring as docstring,
               m.language as language, m.name as name, m.summary as summary,
               collect(DISTINCT callee.id) as callee_ids
        """
        return await self._neo4j.execute_query(query, {"repo_name": repo_name})

    def _build_call_graph(
        self, methods: List[Dict]
    ) -> Dict[str, Dict]:
        """构建方法调用图.

        Args:
            methods: Method 节点列表

        Returns:
            调用图 {method_id: {"data": method, "callees": [callee_ids]}}
        """
        graph = {}
        for method in methods:
            method_id = method.get("id", "")
            if not method_id:
                continue

            callee_ids = [
                cid for cid in method.get("callee_ids", [])
                if cid and cid != method_id  # 排除自调用
            ]

            graph[method_id] = {
                "data": method,
                "callees": callee_ids,
            }

        return graph

    def _topological_sort(self, graph: Dict[str, Dict]) -> List[str]:
        """对方法进行拓扑排序.

        确保被调用的方法排在调用者之前。
        处理循环依赖的情况。

        Args:
            graph: 调用图

        Returns:
            排序后的 method_id 列表
        """
        # 计算入度
        in_degree = defaultdict(int)
        for method_id in graph:
            if method_id not in in_degree:
                in_degree[method_id] = 0
            for callee_id in graph[method_id]["callees"]:
                if callee_id in graph:
                    in_degree[method_id] += 1

        # Kahn 算法
        # 入度为 0 的节点表示不被其他方法调用（叶节点）
        queue = deque([mid for mid in graph if in_degree[mid] == 0])
        result = []

        while queue:
            method_id = queue.popleft()
            result.append(method_id)

            # 找到所有调用该方法的方法（逆向边）
            for mid, data in graph.items():
                if method_id in data["callees"]:
                    in_degree[mid] -= 1
                    if in_degree[mid] == 0:
                        queue.append(mid)

        # 处理循环依赖中剩余的方法
        remaining = set(graph.keys()) - set(result)
        if remaining:
            # 按入度排序，先处理被依赖多的
            remaining_sorted = sorted(
                remaining, key=lambda x: in_degree[x], reverse=True
            )
            result.extend(remaining_sorted)

        return result

    async def _generate_method_summary(
        self, method: Dict, callee_summaries: List[str]
    ) -> str:
        """为单个方法生成 summary.

        Args:
            method: Method 节点数据
            callee_summaries: 被调用方法的 summaries

        Returns:
            生成的摘要
        """
        code = method.get("code", "")
        docstring = method.get("docstring", "")
        language = method.get("language", "python")
        name = method.get("name", "")

        if not code:
            return ""

        try:
            summary = await self._llm_service.generate_summary(
                code=code,
                docstring=docstring,
                callee_summaries=callee_summaries if callee_summaries else None,
                node_type="method",
                language=language,
            )
            return summary
        except Exception as e:
            logger.warning(f"Failed to generate summary for method {name}: {e}")
            return ""

    async def _generate_class_summaries(self, repo_name: str) -> int:
        """生成所有 Class 节点的 summary.

        基于 Class 包含的 Method 的 summaries 生成。

        Args:
            repo_name: 仓库名称

        Returns:
            生成的摘要数量
        """
        classes = await self._get_classes_with_methods(repo_name)
        if not classes:
            return 0

        count = 0
        for class_node in classes:
            class_id = class_node.get("id", "")
            if not class_id or class_node.get("summary"):
                continue

            summary = await self._generate_class_summary(class_node)
            if summary:
                await self._update_node_summary("Class", class_id, summary)
                count += 1

        return count

    async def _get_classes_with_methods(self, repo_name: str) -> List[Dict]:
        """获取所有 Class 节点及其包含的 Method summaries.

        Args:
            repo_name: 仓库名称

        Returns:
            Class 节点列表
        """
        query = """
        MATCH (c:Class)
        WHERE c.repo = $repo_name
        OPTIONAL MATCH (c)-[:CONTAIN]->(m:Method)
        RETURN c.id as id, c.code as code, c.docstring as docstring,
               c.language as language, c.name as name, c.summary as summary,
               collect(DISTINCT m.summary) as method_summaries
        """
        return await self._neo4j.execute_query(query, {"repo_name": repo_name})

    async def _generate_class_summary(self, class_node: Dict) -> str:
        """为单个类生成 summary.

        Args:
            class_node: Class 节点数据

        Returns:
            生成的摘要
        """
        code = class_node.get("code", "")
        docstring = class_node.get("docstring", "")
        language = class_node.get("language", "python")
        name = class_node.get("name", "")
        method_summaries = [
            s for s in class_node.get("method_summaries", [])
            if s  # 过滤空值
        ]

        if not code:
            return ""

        try:
            summary = await self._llm_service.generate_summary(
                code=code,
                docstring=docstring,
                callee_summaries=method_summaries if method_summaries else None,
                node_type="class",
                language=language,
            )
            return summary
        except Exception as e:
            logger.warning(f"Failed to generate summary for class {name}: {e}")
            return ""

    async def _generate_file_summaries(self, repo_name: str) -> int:
        """生成所有 File 节点的 summary.

        代码文件基于包含的 Class/Method summaries 生成，
        非代码文件基于文件内容生成。

        Args:
            repo_name: 仓库名称

        Returns:
            生成的摘要数量
        """
        files = await self._get_files_for_summary(repo_name)
        if not files:
            return 0

        count = 0
        for file_node in files:
            file_id = file_node.get("id", "")
            if not file_id or file_node.get("summary"):
                continue

            summary = await self._generate_file_summary(file_node)
            if summary:
                await self._update_node_summary("File", file_id, summary)
                count += 1

        return count

    async def _get_files_for_summary(self, repo_name: str) -> List[Dict]:
        """获取所有 File 节点及其包含的 Class/Method summaries.

        Args:
            repo_name: 仓库名称

        Returns:
            File 节点列表
        """
        query = """
        MATCH (f:File)
        WHERE f.repo = $repo_name
        OPTIONAL MATCH (f)-[:CONTAIN]->(c:Class)
        OPTIONAL MATCH (f)-[:CONTAIN]->(m:Method)
        RETURN f.id as id, f.code as code, f.fileType as file_type,
               f.suffix as suffix, f.name as name, f.summary as summary,
               collect(DISTINCT c.summary) as class_summaries,
               collect(DISTINCT m.summary) as method_summaries
        """
        return await self._neo4j.execute_query(query, {"repo_name": repo_name})

    async def _generate_file_summary(self, file_node: Dict) -> str:
        """为单个文件生成 summary.

        Args:
            file_node: File 节点数据

        Returns:
            生成的摘要
        """
        code = file_node.get("code", "")
        file_type = file_node.get("file_type", "")
        name = file_node.get("name", "")

        if not code:
            return ""

        try:
            if file_type == "code":
                # 代码文件：基于 Class/Method summaries
                class_summaries = [
                    s for s in file_node.get("class_summaries", [])
                    if s
                ]
                method_summaries = [
                    s for s in file_node.get("method_summaries", [])
                    if s
                ]

                # 合并 summaries 作为上下文
                child_summaries = class_summaries + method_summaries

                summary = await self._llm_service.generate_summary(
                    code=code[:5000],  # 限制代码长度
                    docstring="",
                    callee_summaries=child_summaries if child_summaries else None,
                    node_type="file",
                    language="",
                )
            else:
                # 非代码文件：基于文件内容
                summary = await self._llm_service.generate_summary(
                    code=code[:5000],  # 限制代码长度
                    docstring="",
                    node_type="document",
                    language="",
                )

            return summary
        except Exception as e:
            logger.warning(f"Failed to generate summary for file {name}: {e}")
            return ""

    async def _update_node_summary(
        self, label: str, node_id: str, summary: str
    ) -> None:
        """更新节点的 summary 属性.

        Args:
            label: 节点标签
            node_id: 节点ID
            summary: 摘要内容
        """
        query = f"""
        MATCH (n:{label} {{id: $node_id}})
        SET n.summary = $summary
        """
        try:
            await self._neo4j.execute_query(
                query, {"node_id": node_id, "summary": summary}
            )
        except Exception as e:
            logger.warning(f"Failed to update summary for {label} {node_id}: {e}")
