"""语义分析阶段处理器.

该阶段基于依赖图构建的结果，为代码节点生成语义摘要：
1. 为 Method 节点生成 summary（考虑 CALL 关系）
2. 为 Class 节点生成 summary（基于包含的 Method）
3. 为 File 节点生成 summary（代码文件基于 Class/Method，非代码文件基于内容）

生成后把 summary 属性保存到图节点中。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.graph import GraphHelper
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.llm import get_llm_service
from app.infrastructure.db import get_graph_db_client

from .batch_strategies import BatchStrategy, BatchStrategyFactory

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

    def __init__(self, batch_strategy: str = "dependency_aware"):
        """初始化语义分析阶段.

        Args:
            batch_strategy: 批次构建策略名称，可选值：
                - "dependency_aware": 依赖感知策略（默认）
                - "simple": 简单策略
                - "topological": 拓扑排序策略
        """
        graph_db = get_graph_db_client()
        self.graph_helper = GraphHelper(graph_db)
        self._llm_service = get_llm_service()
        self._batch_strategy = BatchStrategyFactory.create(batch_strategy)

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行语义分析.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            repo_id = getattr(context, 'repo_id', context.repo_name)

            # 1. 生成 Method 节点的 summary
            context.stage_msg = "正在生成 Method 摘要..."
            method_count = await self._generate_method_summaries(repo_id)

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

    async def _generate_method_summaries(self, repo_id: str) -> int:
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
        methods = await self.graph_helper.graph_db.get_methods_with_calls(repo_id)
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

            # 构建智能批次（使用策略模式）
            batch = self._batch_strategy.build_batch(
                pending, method_graph, summary_cache, max_tokens
            )

            # 准备批次数据
            items = self._prepare_batch_items(
                batch, pending, method_graph, summary_cache
            )

            # 生成摘要
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
                await self.graph_helper.update_node_summaries_batch("Method", updates)

            logger.info(
                f"Iteration {iteration}: processed {len(batch)} methods, "
                f"remaining {len(pending)}"
            )

        return processed_count

    async def _generate_class_summaries(self, repo_id: str) -> int:
        """生成所有 Class 节点的 summary.

        基于 Class 包含的 Method 的 summaries 生成，使用批量生成优化。

        Args:
            repo_id: 仓库ID

        Returns:
            生成的摘要数量
        """
        classes = await self.graph_helper.graph_db.get_classes_with_methods(repo_id)
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
            await self.graph_helper.update_node_summaries_batch("Class", updates)

        return len(updates)

    async def _generate_file_summaries(self, repo_id: str) -> int:
        """生成所有 File 节点的 summary.

        代码文件基于包含的 Class/Method summaries 生成，
        非代码文件基于文件内容生成，使用批量生成优化。

        Args:
            repo_id: 仓库ID

        Returns:
            生成的摘要数量
        """
        files = await self.graph_helper.graph_db.get_files_for_summary(repo_id)
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
            await self.graph_helper.update_node_summaries_batch("File", updates)

        return len(updates)

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

