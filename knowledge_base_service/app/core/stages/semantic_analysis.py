"""语义分析阶段处理器.

该阶段基于依赖图构建的结果，为代码节点生成语义摘要：
1. 为 Method 节点生成 summary（考虑 CALL 关系）
2. 为 Class 节点生成 summary（基于包含的 Method）
3. 为 File 节点生成 summary（代码文件基于 Class/Method，非代码文件基于内容）

生成后把 summary 属性保存到图节点中。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.llm.client import get_llm_service
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)


@dataclass
class MethodAnalysisItem:
    """方法分析项 - 包含多层次依赖信息."""
    id: str
    name: str
    code: str
    docstring: str
    language: str
    # 依赖信息分层
    external_callees: List[Dict] = field(default_factory=list)  # 已有summary
    internal_callees: List[Dict] = field(default_factory=list)  # 批次内待处理
    pending_callees: List[str] = field(default_factory=list)    # 未处理方法ID


class SemanticAnalysisStage(PipelineStageHandler):
    """语义分析阶段处理器.

    为 Method、Class、File 节点生成语义摘要。

    Input (context.data):
        - node_ids: Dict - 包含 file_ids, class_ids, method_ids

    Output (context.data):
        - semantic_analysis: Dict - 生成的摘要统计
          {methods_summarized: int, classes_summarized: int, files_summarized: int}

    Side Effects:
        - 在 图数据库 中更新 Method/Class/File 节点的 summary 属性
    """

    stage = PipelineStage.SEMANTIC_ANALYSIS
    weight = 2.0  # LLM 生成摘要

    def __init__(self):
        self.graph_db: Optional[GraphDatabaseClient] = None
        self._llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行语义分析.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self.graph_db = get_graph_db_client()
            repo_id = getattr(context, 'repo_id', context.repo_name)

            # 1. 生成 Method 节点的 summary
            context.stage_msg = "正在生成 Method 摘要..."
            method_count = await self._generate_method_summaries(repo_id, context)

            # 2. 生成 Class 节点的 summary
            context.stage_msg = "正在生成 Class 摘要..."
            class_count = await self._generate_class_summaries(repo_id)

            # 3. 生成 File 节点的 summary
            context.stage_msg = "正在生成 File 摘要..."
            file_count = await self._generate_file_summaries(repo_id)

            # 保存结果到上下文
            context.data["semantic_analysis"] = {
                "methods_summarized": method_count,
                "classes_summarized": class_count,
                "files_summarized": file_count,
            }

            context.stage_msg = f"语义分析完成：{method_count} 个方法, {class_count} 个类, {file_count} 个文件"
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

    async def _generate_method_summaries(self, repo_id: str, context: PipelineContext) -> int:
        """生成所有 Method 节点的 summary.

        使用智能批次构建策略，聚合有依赖关系的方法，减少 LLM 调用次数。
        策略：
        1. 已处理方法使用 summary 作为上下文
        2. 批次内待处理方法使用源码作为上下文
        3. 未处理方法暂不包含

        Args:
            repo_id: 仓库ID
            context: 流水线上下文

        Returns:
            生成的摘要数量
        """
        # 获取所有 method 及其 CALL 关系
        methods = await self._get_methods_with_calls(repo_id)
        if not methods:
            return 0

        total_methods = len(methods)

        # 构建依赖图
        method_graph = self._build_call_graph(methods)

        # 分离已处理和待处理方法
        summary_cache: Dict[str, str] = {}
        pending: Dict[str, Dict] = {}

        for method_id, data in method_graph.items():
            if data["data"].get("summary"):
                summary_cache[method_id] = data["data"]["summary"]
            else:
                pending[method_id] = data

        # 获取上下文限制
        max_tokens = self._llm_service.get_context_window_or_default(default=100000)

        processed_count = 0
        iteration = 0

        # 循环处理直到所有待处理方法完成
        while pending:
            iteration += 1

            # 构建智能批次
            batch = self._build_smart_batch(
                pending, method_graph, summary_cache, max_tokens
            )

            if not batch:
                logger.warning(f"Iteration {iteration}: 无法构建批次，可能存在超大方法")
                # 降级处理：尝试单个方法，使用截断代码
                for mid in list(pending.keys())[:1]:
                    method_data = pending[mid]["data"]
                    code = method_data.get("code", "")
                    # 如果代码太长，大幅截断
                    if len(code) > 8000:
                        method_data["code"] = code[:6000] + "\n# ... (代码已截断)"
                batch = list(pending.keys())[:1]

            # 准备批次数据
            items = self._prepare_batch_items(
                batch, pending, method_graph, summary_cache
            )

            # 生成摘要
            context.stage_msg = f"正在生成 Method 摘要: {processed_count + len(batch)}/{total_methods}"

            summaries = await self._llm_service.generate_method_summaries_enhanced(
                items=items,
            )

            # 更新缓存和数据库
            updates = []
            for method_id, summary in zip(batch, summaries):
                if summary:
                    summary_cache[method_id] = summary
                    pending.pop(method_id, None)
                    updates.append((method_id, summary))
                    processed_count += 1

            if updates:
                await self._update_node_summaries_batch("Method", updates)

            logger.info(
                f"Iteration {iteration}: processed {len(batch)} methods, "
                f"remaining {len(pending)}"
            )

        context.stage_msg = f"已完成 {processed_count} 个 Method 摘要"
        return processed_count

    def _build_smart_batch(
        self,
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, str],
        max_tokens: int,
    ) -> List[str]:
        """构建智能批次 - 聚合跨依赖边界的方法.

        策略：优先选择能覆盖更多批次内依赖的方法，实现依赖消解。

        Args:
            pending: 待处理方法 {method_id: data}
            graph: 完整调用图
            summary_cache: 已生成的 summary 缓存
            max_tokens: 最大上下文 token 数

        Returns:
            批次中的方法 ID 列表
        """
        batch: List[str] = []
        batch_content: List[str] = []  # 用于估算token的内容

        # 计算每个候选方法的聚合价值分数
        candidate_scores: List[Tuple[str, float, List[str]]] = []

        for mid, data in pending.items():
            callees = graph[mid]["callees"]

            # 统计各类依赖
            internal_deps = [
                c for c in callees
                if c in pending and c != mid  # 排除自调用
            ]

            # 聚合价值 = 内部依赖数量 + 潜在覆盖率
            score = len(internal_deps)
            if score > 0:
                # 额外加分：依赖方法也在待处理列表中
                score += 0.5

            candidate_scores.append((mid, score, internal_deps))

        # 按分数降序排序（高价值优先）
        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        # 贪心选择 - 优先聚合高价值且能容纳的方法
        for mid, score, internal_deps in candidate_scores:
            if mid in batch:
                continue

            # 计算需要额外添加的内容
            additions_tokens = 0
            additions: List[str] = []

            # 必须先加入批次内的被调用方法（依赖关系）
            for dep_id in internal_deps:
                if dep_id not in batch and dep_id in pending:
                    dep_code = pending[dep_id]["data"].get("code", "")[:1500]
                    additions.append(dep_code)
                    additions_tokens += len(dep_code) // 4  # 粗略估算

            # 当前方法自身的token
            current_code = pending[mid]["data"].get("code", "")[:3000]
            current_tokens = len(current_code) // 4

            # 计算加入后的总token
            current_total = sum(len(c) // 4 for c in batch_content)
            total_needed = current_total + additions_tokens + current_tokens

            # 检查是否超出限制（留10%余量）
            if total_needed <= max_tokens * 0.9:
                # 将依赖方法加入批次
                for dep_id in internal_deps:
                    if dep_id not in batch and dep_id in pending:
                        batch.append(dep_id)
                        dep_code = pending[dep_id]["data"].get("code", "")[:1500]
                        batch_content.append(dep_code)

                if mid not in batch:
                    batch.append(mid)
                    batch_content.append(current_code)

        return batch

    def _prepare_batch_items(
        self,
        batch: List[str],
        pending: Dict[str, Dict],
        graph: Dict[str, Dict],
        summary_cache: Dict[str, str],
    ) -> List[MethodAnalysisItem]:
        """准备批次分析数据 - 区分已处理和待处理依赖.

        Args:
            batch: 批次中的方法 ID 列表
            pending: 待处理方法
            graph: 完整调用图
            summary_cache: 已生成的 summary 缓存

        Returns:
            方法分析项列表
        """
        items: List[MethodAnalysisItem] = []

        for mid in batch:
            method_data = pending[mid]["data"]
            all_callees = graph[mid]["callees"]

            external_callees = []
            internal_callees = []
            pending_callees = []

            for cid in all_callees:
                if cid == mid:  # 跳过自调用
                    continue

                if cid in summary_cache:
                    # 已有summary - 使用精炼后的语义
                    callee_name = graph.get(cid, {}).get("data", {}).get("name", "unknown")
                    external_callees.append({
                        "id": cid,
                        "name": callee_name,
                        "summary": summary_cache[cid],
                    })
                elif cid in batch:
                    # 批次内待处理 - 使用源码
                    callee_data = pending.get(cid, {}).get("data", {})
                    internal_callees.append({
                        "id": cid,
                        "name": callee_data.get("name", "unknown"),
                        "code": callee_data.get("code", "")[:1500],
                    })
                else:
                    # 未处理也不在批次中 - 记录ID提示
                    pending_callees.append(cid)

            items.append(MethodAnalysisItem(
                id=mid,
                name=method_data.get("name", ""),
                code=method_data.get("code", "")[:3000],
                docstring=method_data.get("docstring", ""),
                language=method_data.get("language", "python"),
                external_callees=external_callees,
                internal_callees=internal_callees,
                pending_callees=pending_callees,
            ))

        return items

    async def _get_methods_with_calls(self, repo_id: str) -> List[Dict]:
        """获取所有 Method 节点及其 CALL 关系.

        Args:
            repo_id: 仓库ID

        Returns:
            Method 节点列表，包含 code, docstring, language 和 calls 关系
        """
        return await self.graph_db.get_methods_with_calls(repo_id)

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

    async def _generate_class_summaries(self, repo_id: str) -> int:
        """生成所有 Class 节点的 summary.

        基于 Class 包含的 Method 的 summaries 生成，使用批量生成优化。

        Args:
            repo_id: 仓库ID

        Returns:
            生成的摘要数量
        """
        classes = await self._get_classes_with_methods(repo_id)
        if not classes:
            return 0

        # 过滤出需要生成 summary 的 class
        pending_classes = []
        for class_node in classes:
            class_id = class_node.get("id", "")
            if class_id and not class_node.get("summary"):
                pending_classes.append(class_node)

        if not pending_classes:
            return 0

        logger.info(f"Generating summaries for {len(pending_classes)} classes")

        # 准备批量生成数据
        batch_items = []
        for class_node in pending_classes:
            method_summaries = [
                s for s in class_node.get("method_summaries", [])
                if s  # 过滤空值
            ]

            batch_items.append({
                "id": class_node.get("id", ""),
                "code": class_node.get("code", ""),
                "docstring": class_node.get("docstring", ""),
                "name": class_node.get("name", ""),
                "language": class_node.get("language", "python"),
                "callee_summaries": method_summaries if method_summaries else None,
            })

        # 批量生成摘要
        summaries = await self._llm_service.generate_summaries_batch(
            items=batch_items,
            node_type="class",
        )

        # 批量更新
        updates = []
        for class_node, summary in zip(pending_classes, summaries):
            if summary:
                updates.append((class_node.get("id", ""), summary))

        if updates:
            await self._update_node_summaries_batch("Class", updates)

        return len(updates)

    async def _get_classes_with_methods(self, repo_id: str) -> List[Dict]:
        """获取所有 Class 节点及其包含的 Method summaries.

        Args:
            repo_id: 仓库ID

        Returns:
            Class 节点列表
        """
        return await self.graph_db.get_classes_with_methods(repo_id)

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

    async def _generate_file_summaries(self, repo_id: str) -> int:
        """生成所有 File 节点的 summary.

        代码文件基于包含的 Class/Method summaries 生成，
        非代码文件基于文件内容生成，使用批量生成优化。

        Args:
            repo_id: 仓库ID

        Returns:
            生成的摘要数量
        """
        files = await self._get_files_for_summary(repo_id)
        if not files:
            return 0

        # 过滤出需要生成 summary 的 file
        pending_files = []
        for file_node in files:
            file_id = file_node.get("id", "")
            if file_id and not file_node.get("summary"):
                pending_files.append(file_node)

        if not pending_files:
            return 0

        logger.info(f"Generating summaries for {len(pending_files)} files")

        # 准备批量生成数据
        batch_items = []
        for file_node in pending_files:
            code = file_node.get("code", "")
            file_type = file_node.get("file_type", "")

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
                child_summaries = class_summaries + method_summaries

                batch_items.append({
                    "id": file_node.get("id", ""),
                    "code": code[:5000],  # 限制代码长度
                    "docstring": "",
                    "name": file_node.get("name", ""),
                    "language": "",
                    "callee_summaries": child_summaries if child_summaries else None,
                })
            else:
                # 非代码文件：基于文件内容
                batch_items.append({
                    "id": file_node.get("id", ""),
                    "code": code[:5000],  # 限制代码长度
                    "docstring": "",
                    "name": file_node.get("name", ""),
                    "language": "",
                    "callee_summaries": None,
                })

        # 批量生成摘要
        summaries = await self._llm_service.generate_summaries_batch(
            items=batch_items,
            node_type="file",
        )

        # 批量更新
        updates = []
        for file_node, summary in zip(pending_files, summaries):
            if summary:
                updates.append((file_node.get("id", ""), summary))

        if updates:
            await self._update_node_summaries_batch("File", updates)

        return len(updates)

    async def _get_files_for_summary(self, repo_id: str) -> List[Dict]:
        """获取所有 File 节点及其包含的 Class/Method summaries.

        Args:
            repo_id: 仓库ID

        Returns:
            File 节点列表
        """
        return await self.graph_db.get_files_for_summary(repo_id)

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
        await self.graph_db.update_node_summary(label, node_id, summary)

    async def _update_node_summaries_batch(
        self, label: str, updates: List[Tuple[str, str]]
    ) -> int:
        """批量更新节点的 summary 属性.

        Args:
            label: 节点标签
            updates: 更新列表，每项为 (node_id, summary) 元组

        Returns:
            更新的节点数量
        """
        if not updates:
            return 0

        # 过滤掉 summary 为空的更新
        valid_updates = [(node_id, summary) for node_id, summary in updates if summary]

        if not valid_updates:
            return 0

        try:
            # 批量更新
            count = await self.graph_db.update_node_summaries_batch(label, valid_updates)
            return count
        except Exception as e:
            logger.warning(f"Failed to batch update {label} summaries: {e}")
            # 降级：逐个更新
            count = 0
            for node_id, summary in valid_updates:
                try:
                    await self.graph_db.update_node_summary(label, node_id, summary)
                    count += 1
                except Exception as inner_e:
                    logger.warning(f"Failed to update summary for {label} {node_id}: {inner_e}")
            return count
