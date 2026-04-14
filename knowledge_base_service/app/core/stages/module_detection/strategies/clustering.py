"""分层聚类策略 - 新方案实现.

支持任意规模仓库的模块检测，通过智能聚类和并行处理提升性能和准确性。

Example:
    ```python
    strategy = ClusteringStrategy(
        max_cluster_size=80,
        max_concurrency=5,
    )
    result = await strategy.detect_modules(
        context=context,
        repo_id="repo_123",
        file_summaries=file_summaries,
        graph_db=graph_db,
        llm_service=llm,
    )
    ```
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple
from uuid import uuid4

from app.domain.graph import GraphHelper, Module, Workflow
from app.domain.models.pipeline import PipelineContext
from app.infrastructure.db import GraphDatabaseClient

from ..models import (
    ClusterModuleResult,
    FileCluster,
    FileDependency,
    MergedModule,
    ModuleInfo,
    WorkflowInfo,
)
from .base import ModuleDetectionResult, ModuleDetectionStrategy

logger = logging.getLogger(__name__)


class ClusteringStrategy(ModuleDetectionStrategy):
    """分层聚类策略 - 新方案实现.

    特点:
    - 智能聚类，支持任意规模仓库
    - 引入依赖关系信息
    - 多簇并行处理
    - 适合中大型仓库 (>50文件)

    处理流程:
    1. Phase 1: 预聚类 - 基于目录结构和依赖关系智能分簇
    2. Phase 2: 簇内模块识别 - 并行调用LLM识别模块
    3. Phase 3: 跨簇合并 - 合并相似模块
    4. Phase 4: 工作流识别 - 基于方法调用链识别业务流程
    5. Phase 5: 语义图构建 - 持久化结果到图数据库
    """

    def __init__(
        self,
        max_cluster_size: int = 80,
        max_concurrency: int = 5,
        merge_similarity_threshold: float = 0.7,
    ):
        """初始化策略.

        Args:
            max_cluster_size: 最大簇大小，默认80
            max_concurrency: 最大并发数，默认5
            merge_similarity_threshold: 模块合并相似度阈值，默认0.7
        """
        self.max_cluster_size = max_cluster_size
        self.max_concurrency = max_concurrency
        self.merge_similarity_threshold = merge_similarity_threshold

    @property
    def name(self) -> str:
        """策略名称."""
        return "clustering"

    @property
    def description(self) -> str:
        """策略描述."""
        return (
            f"分层聚类策略 - 智能分簇(max={self.max_cluster_size})并行处理，"
            f"支持任意规模仓库"
        )

    def validate_config(self) -> bool:
        """验证配置.

        Returns:
            True if 配置有效
        """
        return (
            self.max_cluster_size >= 20
            and self.max_concurrency > 0
            and 0 < self.merge_similarity_threshold <= 1
        )

    async def detect_modules(
        self,
        context: PipelineContext,
        repo_id: str,
        file_summaries: Dict[str, str],
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> ModuleDetectionResult:
        """执行分层聚类模块检测.

        Args:
            context: Pipeline上下文
            repo_id: 仓库ID
            file_summaries: 文件ID到摘要的映射
            graph_db: 图数据库客户端
            llm_service: LLM服务

        Returns:
            ModuleDetectionResult: 检测结果
        """
        # 创建 GraphHelper 实例
        helper = GraphHelper(graph_db)

        logger.info(f"Starting clustering strategy for repo: {repo_id}")

        # Phase 1: 预聚类
        context.stage_msg = "Phase 1/5: 正在分析代码结构并进行预聚类..."
        clusters = await self._phase1_clustering(repo_id, graph_db)
        logger.info(f"Phase 1 completed: {len(clusters)} clusters created")

        # 小仓库优化：如果只有一个簇且文件数不多，直接全量分析
        if len(clusters) == 1 and clusters[0].file_count <= self.max_cluster_size:
            logger.info("Small repository detected, using single cluster analysis")

        # Phase 2: 簇内模块识别（并行）
        context.stage_msg = f"Phase 2/5: 正在并行分析 {len(clusters)} 个代码簇..."
        cluster_results = await self._phase2_intra_cluster_detection(
            clusters, file_summaries, repo_id, graph_db, llm_service
        )
        total_modules = sum(r.module_count for r in cluster_results)
        logger.info(f"Phase 2 completed: {total_modules} modules detected")

        # Phase 3: 跨簇合并与优化
        context.stage_msg = "Phase 3/5: 正在合并跨簇相似模块..."
        merged_modules = self._phase3_cross_cluster_merging(cluster_results)
        logger.info(
            f"Phase 3 completed: {len(merged_modules)} modules after merging"
        )

        # Phase 4: 工作流识别
        context.stage_msg = "Phase 4/5: 正在识别业务流程..."
        await self._phase4_workflow_detection(
            merged_modules, file_summaries, repo_id, graph_db, llm_service
        )
        total_workflows = sum(len(m.workflows) for m in merged_modules)
        logger.info(f"Phase 4 completed: {total_workflows} workflows detected")

        # Phase 5: 语义图构建
        context.stage_msg = "Phase 5/5: 正在构建语义图..."
        module_ids, workflow_ids = await self._phase5_build_semantic_graph(
            merged_modules, repo_id, helper
        )
        logger.info(
            f"Phase 5 completed: {len(module_ids)} modules, "
            f"{len(workflow_ids)} workflows persisted"
        )

        return ModuleDetectionResult(
            module_ids=module_ids,
            workflow_ids=workflow_ids,
            metadata={
                "strategy": self.name,
                "cluster_count": len(clusters),
                "total_modules_before_merge": total_modules,
                "module_count": len(module_ids),
                "workflow_count": len(workflow_ids),
            },
        )

    # ==================== Phase 1: 预聚类 ====================

    async def _phase1_clustering(
        self,
        repo_id: str,
        graph_db: GraphDatabaseClient,
    ) -> List[FileCluster]:
        """Phase 1: 预聚类.

        基于目录结构和依赖关系智能分簇。

        Args:
            repo_id: 仓库ID
            graph_db: 图数据库客户端

        Returns:
            文件簇列表
        """
        # 1. 获取代码文件元数据
        files = await self._get_code_files(repo_id, graph_db)
        if not files:
            logger.warning(f"No code files found in repo: {repo_id}")
            return []

        # 2. 获取文件依赖图
        dependencies = await self._get_file_dependencies(repo_id, graph_db)

        # 3. 基于目录和依赖关系进行智能聚类
        clusters = self._cluster_files_with_dependencies(
            files, dependencies, self.max_cluster_size
        )

        return clusters

    async def _get_code_files(
        self,
        repo_id: str,
        graph_db: GraphDatabaseClient,
    ) -> List[Dict]:
        """从图数据库获取代码文件.

        Args:
            repo_id: 仓库ID
            graph_db: 图数据库客户端

        Returns:
            代码文件列表
        """
        return await graph_db.get_code_files_with_summary(repo_id)

    async def _get_file_dependencies(
        self,
        repo_id: str,
        graph_db: GraphDatabaseClient,
    ) -> List[FileDependency]:
        """获取文件依赖关系.

        包括USE关系（import依赖）和CALL关系（方法调用）。

        Args:
            repo_id: 仓库ID
            graph_db: 图数据库客户端

        Returns:
            文件依赖列表
        """
        all_deps: Dict[Tuple[str, str], FileDependency] = {}

        # 查询USE关系（import依赖）
        use_edges = await graph_db.get_file_use_dependencies(repo_id)

        for edge in use_edges:
            key = (edge["source"], edge["target"])
            if key in all_deps:
                all_deps[key].weight += edge["weight"]
                all_deps[key].dep_type = "both"
            else:
                all_deps[key] = FileDependency(
                    source=edge["source"],
                    target=edge["target"],
                    weight=edge["weight"],
                    dep_type="use",
                )

        # 查询CALL关系（通过方法调用隐式依赖）
        call_edges = await graph_db.get_file_call_dependencies(repo_id)

        for edge in call_edges:
            key = (edge["source"], edge["target"])
            if key in all_deps:
                all_deps[key].weight += edge["weight"]
                all_deps[key].dep_type = "both"
            else:
                all_deps[key] = FileDependency(
                    source=edge["source"],
                    target=edge["target"],
                    weight=edge["weight"],
                    dep_type="call",
                )

        return list(all_deps.values())

    def _cluster_files_with_dependencies(
        self,
        files: List[Dict],
        dependencies: List[FileDependency],
        max_cluster_size: int,
    ) -> List[FileCluster]:
        """基于目录和依赖关系进行智能聚类.

        算法步骤:
        1. 基于目录前缀进行初始分组
        2. 处理过大的组（使用依赖关系子划分）
        3. 合并高依赖的小簇

        Args:
            files: 文件列表
            dependencies: 依赖关系列表
            max_cluster_size: 最大簇大小

        Returns:
            文件簇列表
        """
        if not files:
            return []

        # 构建文件ID到信息的映射
        file_map = {f["id"]: f for f in files}

        # 构建依赖邻接表
        dep_map: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for dep in dependencies:
            dep_map[dep.source].append((dep.target, dep.weight))
            dep_map[dep.target].append((dep.source, dep.weight))

        # 步骤1: 基于目录前缀进行初始分组
        dir_groups: Dict[str, List[str]] = defaultdict(list)
        for file_info in files:
            dir_prefix = self._get_directory_prefix(file_info["path"])
            dir_groups[dir_prefix].append(file_info["id"])

        # 步骤2: 处理过大的组
        clusters: List[FileCluster] = []
        cluster_idx = 0

        for dir_prefix, file_ids in dir_groups.items():
            if len(file_ids) <= max_cluster_size:
                # 直接创建簇
                cluster = self._create_cluster(
                    f"cluster_{cluster_idx}",
                    dir_prefix,
                    file_ids,
                    dependencies,
                    file_map,
                )
                clusters.append(cluster)
                cluster_idx += 1
            else:
                # 使用依赖关系进行子划分
                sub_clusters = self._split_large_group(
                    f"cluster_{cluster_idx}",
                    dir_prefix,
                    file_ids,
                    dependencies,
                    max_cluster_size,
                    file_map,
                )
                clusters.extend(sub_clusters)
                cluster_idx += len(sub_clusters)

        # 步骤3: 合并高依赖的小簇
        merged_clusters = self._merge_highly_connected_clusters(
            clusters, dependencies, min_size=10
        )

        logger.info(
            f"Clustering completed: {len(files)} files -> "
            f"{len(merged_clusters)} clusters"
        )
        return merged_clusters

    def _get_directory_prefix(self, path: str, depth: int = 2) -> str:
        """获取目录前缀.

        Args:
            path: 文件路径
            depth: 目录深度，默认2

        Returns:
            目录前缀
        """
        parts = path.replace("\\", "/").split("/")
        if len(parts) <= 1:
            return ""
        return "/".join(parts[: min(depth, len(parts) - 1)])

    def _create_cluster(
        self,
        cluster_id: str,
        dir_prefix: str,
        file_ids: List[str],
        dependencies: List[FileDependency],
        file_map: Dict[str, Dict],
    ) -> FileCluster:
        """创建文件簇.

        Args:
            cluster_id: 簇ID
            dir_prefix: 目录前缀
            file_ids: 文件ID列表
            dependencies: 依赖关系列表
            file_map: 文件ID到信息的映射

        Returns:
            文件簇
        """
        file_set = set(file_ids)

        internal_edges = []
        external_edges = []

        for dep in dependencies:
            if dep.source in file_set and dep.target in file_set:
                internal_edges.append((dep.source, dep.target, dep.weight))
            elif dep.source in file_set or dep.target in file_set:
                external_edges.append((dep.source, dep.target, dep.weight))

        return FileCluster(
            id=cluster_id,
            file_ids=file_ids,
            internal_edges=internal_edges,
            external_edges=external_edges,
            directory_prefix=dir_prefix,
        )

    def _split_large_group(
        self,
        base_id: str,
        dir_prefix: str,
        file_ids: List[str],
        dependencies: List[FileDependency],
        max_size: int,
        file_map: Dict[str, Dict],
    ) -> List[FileCluster]:
        """将大组拆分为多个子簇.

        使用社区发现算法（简化的贪心算法）进行划分。

        Args:
            base_id: 基础簇ID
            dir_prefix: 目录前缀
            file_ids: 文件ID列表
            dependencies: 依赖关系列表
            max_size: 最大簇大小
            file_map: 文件ID到信息的映射

        Returns:
            子簇列表
        """
        file_set = set(file_ids)

        # 构建内部依赖图
        internal_deps: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for dep in dependencies:
            if dep.source in file_set and dep.target in file_set:
                internal_deps[dep.source].append((dep.target, dep.weight))
                internal_deps[dep.target].append((dep.source, dep.weight))

        # 按依赖度排序文件（优先保留高连接度的文件在一起）
        sorted_files = sorted(
            file_ids,
            key=lambda fid: sum(w for _, w in internal_deps.get(fid, [])),
            reverse=True,
        )

        # 贪心划分
        clusters: List[FileCluster] = []
        assigned: Set[str] = set()
        cluster_idx = 0

        while len(assigned) < len(file_ids):
            # 找未分配且连接度最高的文件作为种子
            seed = None
            for fid in sorted_files:
                if fid not in assigned:
                    seed = fid
                    break

            if seed is None:
                break

            # 构建新簇
            cluster_files = [seed]
            assigned.add(seed)

            # 添加与种子高连接的文件
            neighbors = sorted(
                internal_deps.get(seed, []),
                key=lambda x: x[1],
                reverse=True,
            )

            for neighbor_id, weight in neighbors:
                if neighbor_id not in assigned and len(cluster_files) < max_size:
                    cluster_files.append(neighbor_id)
                    assigned.add(neighbor_id)

            # 创建簇
            cluster = self._create_cluster(
                f"{base_id}_{cluster_idx}",
                dir_prefix,
                cluster_files,
                dependencies,
                file_map,
            )
            clusters.append(cluster)
            cluster_idx += 1

        return clusters

    def _merge_highly_connected_clusters(
        self,
        clusters: List[FileCluster],
        dependencies: List[FileDependency],
        min_size: int = 10,
    ) -> List[FileCluster]:
        """合并高依赖的小簇.

        Args:
            clusters: 簇列表
            dependencies: 依赖关系列表
            min_size: 最小簇大小

        Returns:
            合并后的簇列表
        """
        if len(clusters) <= 1:
            return clusters

        # 计算簇间依赖密度
        cluster_map = {c.id: c for c in clusters}
        cluster_ids = list(cluster_map.keys())

        # 构建簇间依赖图
        inter_cluster_deps: Dict[Tuple[str, str], int] = defaultdict(int)

        for dep in dependencies:
            source_cluster = None
            target_cluster = None

            for cluster in clusters:
                if dep.source in cluster.file_ids:
                    source_cluster = cluster.id
                if dep.target in cluster.file_ids:
                    target_cluster = cluster.id

            if (
                source_cluster
                and target_cluster
                and source_cluster != target_cluster
            ):
                key = tuple(sorted([source_cluster, target_cluster]))
                inter_cluster_deps[key] += dep.weight

        # 简单的贪心合并
        merged: Set[str] = set()
        result: List[FileCluster] = []

        for cluster in clusters:
            if cluster.id in merged:
                continue

            # 找最佳合并伙伴（依赖密度最高且目录前缀相近）
            best_partner = None
            best_score = 0

            for other in clusters:
                if other.id == cluster.id or other.id in merged:
                    continue

                if cluster.file_count + other.file_count > self.max_cluster_size:
                    continue

                dep_key = tuple(sorted([cluster.id, other.id]))
                dep_weight = inter_cluster_deps.get(dep_key, 0)

                # 计算合并分数
                dir_similarity = self._directory_similarity(
                    cluster.directory_prefix, other.directory_prefix
                )
                score = dep_weight * dir_similarity

                if score > best_score:
                    best_score = score
                    best_partner = other

            # 如果分数足够高，执行合并
            if best_partner and best_score > 3:  # 阈值可调整
                merged_cluster = self._merge_two_clusters(
                    cluster, best_partner, dependencies
                )
                merged.add(cluster.id)
                merged.add(best_partner.id)
                result.append(merged_cluster)
            else:
                result.append(cluster)

        return result

    def _directory_similarity(self, prefix1: str, prefix2: str) -> float:
        """计算目录前缀相似度.

        Args:
            prefix1: 前缀1
            prefix2: 前缀2

        Returns:
            相似度 (0-1)
        """
        if not prefix1 or not prefix2:
            return 0.5

        parts1 = prefix1.split("/")
        parts2 = prefix2.split("/")

        # 计算共同前缀长度
        common = 0
        for p1, p2 in zip(parts1, parts2):
            if p1 == p2:
                common += 1
            else:
                break

        return common / max(len(parts1), len(parts2))

    def _merge_two_clusters(
        self,
        c1: FileCluster,
        c2: FileCluster,
        dependencies: List[FileDependency],
    ) -> FileCluster:
        """合并两个簇.

        Args:
            c1: 簇1
            c2: 簇2
            dependencies: 依赖关系列表

        Returns:
            合并后的簇
        """
        merged_files = list(set(c1.file_ids + c2.file_ids))

        # 重新计算边
        file_set = set(merged_files)
        internal_edges = []
        external_edges = []

        for dep in dependencies:
            in_c1 = dep.source in file_set and dep.target in file_set
            if in_c1:
                internal_edges.append((dep.source, dep.target, dep.weight))
            elif dep.source in file_set or dep.target in file_set:
                external_edges.append((dep.source, dep.target, dep.weight))

        # 选择更通用的目录前缀
        prefix = c1.directory_prefix
        if len(c2.directory_prefix) < len(prefix):
            prefix = c2.directory_prefix

        return FileCluster(
            id=f"{c1.id}_merged_{c2.id}",
            file_ids=merged_files,
            internal_edges=internal_edges,
            external_edges=external_edges,
            directory_prefix=prefix,
            metadata={"merged_from": [c1.id, c2.id]},
        )

    # ==================== Phase 2: 簇内模块识别 ====================

    async def _phase2_intra_cluster_detection(
        self,
        clusters: List[FileCluster],
        file_summaries: Dict[str, str],
        repo_id: str,
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> List[ClusterModuleResult]:
        """Phase 2: 簇内模块识别（并行）.

        Args:
            clusters: 文件簇列表
            file_summaries: 文件摘要
            repo_id: 仓库ID
            graph_db: 图数据库客户端
            llm_service: LLM服务

        Returns:
            簇级模块检测结果列表
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def process_cluster(cluster: FileCluster) -> ClusterModuleResult:
            async with semaphore:
                return await self._detect_modules_in_cluster(
                    cluster, file_summaries, repo_id, graph_db, llm_service
                )

        # 并行处理所有簇
        results = await asyncio.gather(*[process_cluster(c) for c in clusters])
        return list(results)

    async def _detect_modules_in_cluster(
        self,
        cluster: FileCluster,
        file_summaries: Dict[str, str],
        repo_id: str,
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> ClusterModuleResult:
        """检测单个簇内的模块.

        Args:
            cluster: 文件簇
            file_summaries: 文件摘要
            repo_id: 仓库ID
            graph_db: 图数据库客户端
            llm_service: LLM服务

        Returns:
            簇级模块检测结果
        """
        try:
            # 构建簇的结构JSON
            structure_json = await self._build_cluster_structure_json(
                cluster, file_summaries, repo_id, graph_db
            )

            # 构建Prompt
            prompt = self._build_cluster_detection_prompt(structure_json)

            # 调用LLM
            response = await llm_service.complete(
                prompt=prompt,
                system_prompt="你是软件架构专家。分析代码结构并识别功能模块，所有描述必须使用中文。",
                temperature=0.3,
            )

            # 解析结果
            modules = self._parse_cluster_detection_response(response)

            return ClusterModuleResult(
                cluster_id=cluster.id,
                modules=modules,
                metadata={"file_count": cluster.file_count},
            )

        except Exception as e:
            logger.exception(f"Failed to detect modules in cluster {cluster.id}: {e}")
            # 降级：返回基于目录结构的简单模块
            return self._fallback_module_detection(cluster)

    async def _build_cluster_structure_json(
        self,
        cluster: FileCluster,
        file_summaries: Dict[str, str],
        repo_id: str,
        graph_db: GraphDatabaseClient,
    ) -> Dict:
        """构建簇的结构JSON.

        Args:
            cluster: 文件簇
            file_summaries: 文件摘要
            repo_id: 仓库ID
            graph_db: 图数据库客户端

        Returns:
            结构JSON字典
        """
        # 获取簇内文件信息
        files_info = []
        for file_id in cluster.file_ids:
            summary = file_summaries.get(file_id, "")

            # 查询文件相关的类和关键方法
            classes, key_methods = await self._get_file_classes_and_methods(
                file_id, graph_db
            )

            file_data = {
                "id": file_id,
                "summary": summary[:300] if summary else "",
                "classes": [
                    {"name": c["name"], "summary": c["summary"][:100]}
                    for c in classes[:3]  # 最多3个类
                ],
                "key_methods": [
                    {"name": m["name"], "summary": m["summary"][:80]}
                    for m in key_methods[:5]  # 最多5个关键方法
                ],
            }
            files_info.append(file_data)

        # 构建依赖图
        dependency_graph = [
            {"source": src, "target": tgt, "weight": wgt}
            for src, tgt, wgt in cluster.internal_edges
        ]

        # 外部依赖摘要
        external_summary = self._summarize_external_edges(cluster.external_edges)

        return {
            "cluster_id": cluster.id,
            "directory_prefix": cluster.directory_prefix,
            "file_count": cluster.file_count,
            "files": files_info,
            "internal_dependencies": dependency_graph,
            "external_dependency_summary": external_summary,
        }

    async def _get_file_classes_and_methods(
        self,
        file_id: str,
        graph_db: GraphDatabaseClient,
    ) -> Tuple[List[Dict], List[Dict]]:
        """获取文件的类和方法信息.

        Args:
            file_id: 文件ID，格式为 "file_{repo_name}_{file_path}"
            graph_db: 图数据库客户端

        Returns:
            (类列表, 关键方法列表)
        """
        # 从 file_id 提取 file_path
        # file_id 格式: file_{repo_name}_{file_path}
        file_path = self._extract_file_path_from_id(file_id)

        # 使用抽象基类方法查询类和方法
        classes = await graph_db.get_classes_by_file_path(file_path)
        methods = await graph_db.get_methods_by_file_path(file_path, limit=5)

        return classes, methods

    def _extract_file_path_from_id(self, file_id: str) -> str:
        """从文件ID中提取文件路径.

        file_id 格式: file_{repo_name}_{file_path}
        例如: file_my-repo_src/main.py -> src/main.py

        Args:
            file_id: 文件ID

        Returns:
            文件路径
        """
        # 移除前缀 "file_"
        if file_id.startswith("file_"):
            remaining = file_id[5:]  # 跳过 "file_"
            # 找到第一个下划线后的内容（repo_name 和 file_path 的分隔）
            parts = remaining.split("_", 1)
            if len(parts) >= 2:
                return parts[1]  # 返回 file_path 部分
            return remaining
        return file_id

    def _summarize_external_edges(
        self, external_edges: List[Tuple[str, str, int]]
    ) -> str:
        """摘要外部依赖边.

        Args:
            external_edges: 外部依赖边列表

        Returns:
            摘要字符串
        """
        if not external_edges:
            return "无显著外部依赖"

        # 统计外部依赖方向
        outgoing = sum(1 for e in external_edges if e[2] > 0)
        incoming = len(external_edges) - outgoing

        return f"外部依赖: {outgoing} 出边, {incoming} 入边"

    def _build_cluster_detection_prompt(self, structure_json: Dict) -> str:
        """构建簇检测Prompt.

        Args:
            structure_json: 结构JSON

        Returns:
            Prompt字符串
        """
        import json

        return f"""分析以下代码簇的结构，识别功能模块和业务流程。

簇信息:
- ID: {structure_json['cluster_id']}
- 目录前缀: {structure_json['directory_prefix']}
- 文件数: {structure_json['file_count']}

文件列表（含摘要和关键类/方法）:
```json
{json.dumps(structure_json['files'], indent=2, ensure_ascii=False)}
```

内部依赖关系:
```json
{json.dumps(structure_json['internal_dependencies'], indent=2, ensure_ascii=False)}
```

外部依赖摘要:
{structure_json['external_dependency_summary']}

请识别:
1. 该簇包含的功能模块（1-3个）
2. 每个模块的核心职责
3. 模块内的工作流程/业务流程
4. 模块间的关系（基于依赖图）

返回JSON格式:
{{
    "modules": [
        {{
            "name": "模块名称(中文)",
            "description": "简述(50字以内)",
            "detail": "详细说明(200-500字)",
            "files": ["file_id_1", "file_id_2"],
            "confidence": 0.85,
            "workflows": [
                {{
                    "name": "工作流名称(中文)",
                    "description": "简述(50字以内)",
                    "files": ["file_id_1"]
                }}
            ]
        }}
    ],
    "cross_module_dependencies": [
        {{"from": "模块A", "to": "模块B", "type": "调用/数据流"}}
    ]
}}

注意:
- name、description、detail 字段必须使用中文
- files 应该包含相关的文件ID（不是路径）
- confidence 是置信度 (0-1)
"""

    def _parse_cluster_detection_response(self, response: str) -> List[ModuleInfo]:
        """解析簇检测结果.

        Args:
            response: LLM响应

        Returns:
            模块信息列表
        """
        import json
        import re

        # 提取JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = response

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return []

        modules = []
        for mod_data in data.get("modules", []):
            workflows = [
                WorkflowInfo(
                    name=wf.get("name", "Unknown"),
                    description=wf.get("description", ""),
                    files=wf.get("files", []),
                )
                for wf in mod_data.get("workflows", [])
            ]

            module = ModuleInfo(
                name=mod_data.get("name", "Unknown Module"),
                description=mod_data.get("description", ""),
                detail=mod_data.get("detail", ""),
                files=mod_data.get("files", []),
                workflows=workflows,
                confidence=mod_data.get("confidence", 0.8),
                cross_module_deps=mod_data.get("cross_module_dependencies", []),
            )
            modules.append(module)

        return modules

    def _fallback_module_detection(
        self, cluster: FileCluster
    ) -> ClusterModuleResult:
        """降级模块检测（基于目录结构）.

        Args:
            cluster: 文件簇

        Returns:
            降级检测结果
        """
        # 基于目录前缀创建简单模块
        module_name = f"{cluster.directory_prefix or 'Unknown'} 模块"

        module = ModuleInfo(
            name=module_name,
            description=f"基于目录结构识别的模块，包含 {cluster.file_count} 个文件",
            detail=f"该模块通过目录聚类自动识别，目录前缀: {cluster.directory_prefix}",
            files=cluster.file_ids,
            confidence=0.5,
        )

        return ClusterModuleResult(
            cluster_id=cluster.id,
            modules=[module],
            metadata={"fallback": True, "file_count": cluster.file_count},
        )

    # ==================== Phase 3: 跨簇合并 ====================

    def _phase3_cross_cluster_merging(
        self, cluster_results: List[ClusterModuleResult]
    ) -> List[MergedModule]:
        """Phase 3: 跨簇合并与优化.

        合并跨簇识别的相似模块。

        Args:
            cluster_results: 簇级模块检测结果列表

        Returns:
            合并后的模块列表
        """
        # 收集所有模块
        all_modules: List[Tuple[str, ModuleInfo]] = []
        for result in cluster_results:
            for module in result.modules:
                all_modules.append((result.cluster_id, module))

        if not all_modules:
            return []

        # 计算模块相似度并合并
        merged = self._merge_similar_modules(all_modules)

        return merged

    def _merge_similar_modules(
        self, modules: List[Tuple[str, ModuleInfo]]
    ) -> List[MergedModule]:
        """合并相似模块.

        Args:
            modules: (簇ID, 模块信息) 列表

        Returns:
            合并后的模块列表
        """
        if len(modules) <= 1:
            return [
                self._convert_to_merged_module([m])
                for m in modules
            ]

        # 计算相似度矩阵
        n = len(modules)
        similarity_matrix = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(i + 1, n):
                sim = self._calculate_module_similarity(
                    modules[i][1], modules[j][1]
                )
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim

        # 使用并查集合并相似模块
        parent = list(range(n))

        def find(x: int) -> int:
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: int, y: int):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # 合并相似度高于阈值的模块
        for i in range(n):
            for j in range(i + 1, n):
                if similarity_matrix[i][j] >= self.merge_similarity_threshold:
                    union(i, j)

        # 分组
        groups: Dict[int, List[Tuple[int, str, ModuleInfo]]] = defaultdict(list)
        for idx, (cluster_id, module) in enumerate(modules):
            root = find(idx)
            groups[root].append((idx, cluster_id, module))

        # 转换为MergedModule
        merged_modules = []
        for group in groups.values():
            merged = self._convert_group_to_merged_module(group)
            merged_modules.append(merged)

        return merged_modules

    def _calculate_module_similarity(
        self, m1: ModuleInfo, m2: ModuleInfo
    ) -> float:
        """计算两个模块的相似度.

        Args:
            m1: 模块1
            m2: 模块2

        Returns:
            相似度 (0-1)
        """
        scores = []

        # 1. 名称相似度
        name_sim = self._string_similarity(m1.name, m2.name)
        scores.append(name_sim * 0.3)

        # 2. 关键词重叠度
        files1, files2 = set(m1.files), set(m2.files)
        if files1 and files2:
            jaccard = len(files1 & files2) / len(files1 | files2)
            scores.append(jaccard * 0.4)

        # 3. 描述相似度
        desc_sim = self._string_similarity(m1.description, m2.description)
        scores.append(desc_sim * 0.3)

        return sum(scores)

    def _string_similarity(self, s1: str, s2: str) -> float:
        """计算字符串相似度（Jaccard）.

        Args:
            s1: 字符串1
            s2: 字符串2

        Returns:
            相似度 (0-1)
        """
        if not s1 or not s2:
            return 0.0

        # 简单分词
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _convert_to_merged_module(
        self, modules: List[Tuple[str, ModuleInfo]]
    ) -> MergedModule:
        """将单个模块转换为MergedModule.

        Args:
            modules: (簇ID, 模块) 列表

        Returns:
            合并模块
        """
        if len(modules) == 1:
            cluster_id, module = modules[0]
            return MergedModule(
                id=f"module_{uuid4().hex[:8]}",
                name=module.name,
                description=module.description,
                detail=module.detail,
                file_ids=module.files,
                source_clusters=[cluster_id],
                workflows=module.workflows,
                confidence=module.confidence,
            )
        else:
            return self._convert_group_to_merged_module(modules)

    def _convert_group_to_merged_module(
        self, group: List[Tuple[int, str, ModuleInfo]]
    ) -> MergedModule:
        """将模块组转换为MergedModule.

        Args:
            group: (索引, 簇ID, 模块) 列表

        Returns:
            合并模块
        """
        # 选择信息最丰富的模块作为主模块
        main_module = max(group, key=lambda x: len(x[2].detail))

        # 合并文件列表
        all_files = set()
        all_workflows = []
        source_clusters = []

        for _, cluster_id, module in group:
            all_files.update(module.files)
            all_workflows.extend(module.workflows)
            source_clusters.append(cluster_id)

        return MergedModule(
            id=f"module_{uuid4().hex[:8]}",
            name=main_module[2].name,
            description=main_module[2].description,
            detail=main_module[2].detail,
            file_ids=list(all_files),
            source_clusters=source_clusters,
            workflows=all_workflows,
            confidence=main_module[2].confidence,
            merged_from=[m[2].name for m in group],
        )

    # ==================== Phase 4: 工作流识别 ====================

    async def _phase4_workflow_detection(
        self,
        modules: List[MergedModule],
        file_summaries: Dict[str, str],
        repo_id: str,
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> None:
        """Phase 4: 工作流识别.

        为每个模块识别详细的业务流程。

        Args:
            modules: 模块列表
            file_summaries: 文件摘要
            repo_id: 仓库ID
            graph_db: 图数据库客户端
            llm_service: LLM服务
        """
        for module in modules:
            if module.workflows:
                continue  # 已有工作流

            # 基于方法调用链识别工作流
            workflows = await self._detect_module_workflows(
                module, file_summaries, repo_id, graph_db, llm_service
            )
            module.workflows = workflows

    async def _detect_module_workflows(
        self,
        module: MergedModule,
        file_summaries: Dict[str, str],
        repo_id: str,
        graph_db: GraphDatabaseClient,
        llm_service: Any,
    ) -> List[WorkflowInfo]:
        """检测模块的工作流.

        Args:
            module: 模块
            file_summaries: 文件摘要
            repo_id: 仓库ID
            graph_db: 图数据库客户端
            llm_service: LLM服务

        Returns:
            工作流列表
        """
        # 获取模块内方法调用链
        call_chains = await self._get_module_call_chains(
            module.file_ids, graph_db
        )

        if not call_chains:
            # 无调用链时返回默认工作流
            return [
                WorkflowInfo(
                    name=f"{module.name} 主流程",
                    description=f"{module.name} 的核心业务流程",
                    files=module.file_ids[:5],  # 最多5个文件
                )
            ]

        # 构建Prompt识别工作流
        prompt = self._build_workflow_detection_prompt(module, call_chains)

        try:
            response = await llm_service.complete(
                prompt=prompt,
                system_prompt="你是业务流程分析专家。基于方法调用链识别业务流程，所有描述必须使用中文。",
                temperature=0.3,
            )

            workflows = self._parse_workflow_response(response)
            return workflows

        except Exception as e:
            logger.warning(f"Failed to detect workflows for {module.name}: {e}")
            return [
                WorkflowInfo(
                    name=f"{module.name} 主流程",
                    description=f"{module.name} 的核心业务流程",
                    files=module.file_ids[:5],
                )
            ]

    async def _get_module_call_chains(
        self,
        file_ids: List[str],
        graph_db: GraphDatabaseClient,
    ) -> List[Dict]:
        """获取模块内方法调用链.

        Args:
            file_ids: 文件ID列表
            graph_db: 图数据库客户端

        Returns:
            调用链列表
        """
        # 将 file_ids 转换为 file_paths
        file_paths = [self._extract_file_path_from_id(fid) for fid in file_ids]

        return await graph_db.get_method_call_chains_by_file_paths(
            file_paths, limit=50
        )

    def _build_workflow_detection_prompt(
        self, module: MergedModule, call_chains: List[Dict]
    ) -> str:
        """构建工作流检测Prompt.

        Args:
            module: 模块
            call_chains: 调用链

        Returns:
            Prompt字符串
        """
        import json

        return f"""分析以下模块的方法调用关系，识别核心业务流程。

模块名称: {module.name}
模块描述: {module.description}
文件数量: {module.file_count}

方法调用链:
```json
{json.dumps(call_chains[:20], indent=2, ensure_ascii=False)}
```

请识别:
1. 该模块的核心业务流程（1-3个）
2. 每个流程的入口点和关键步骤
3. 流程涉及的主要文件

返回JSON格式:
{{
    "workflows": [
        {{
            "name": "流程名称(中文)",
            "description": "流程描述(50字以内)",
            "entry_points": ["方法名1", "方法名2"],
            "key_files": ["file_id_1", "file_id_2"]
        }}
    ]
}}
"""

    def _parse_workflow_response(self, response: str) -> List[WorkflowInfo]:
        """解析工作流响应.

        Args:
            response: LLM响应

        Returns:
            工作流列表
        """
        import json
        import re

        # 提取JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        workflows = []
        for wf_data in data.get("workflows", []):
            workflow = WorkflowInfo(
                name=wf_data.get("name", "Unknown"),
                description=wf_data.get("description", ""),
                files=wf_data.get("key_files", []),
            )
            workflows.append(workflow)

        return workflows

    # ==================== Phase 5: 语义图构建 ====================

    async def _phase5_build_semantic_graph(
        self,
        modules: List[MergedModule],
        repo_id: str,
        helper: GraphHelper,
    ) -> Tuple[List[str], List[str]]:
        """Phase 5: 语义图构建.

        将识别结果持久化到图数据库。

        Args:
            modules: 模块列表
            repo_id: 仓库ID
            helper: GraphHelper 实例

        Returns:
            (module_ids, workflow_ids)
        """
        module_ids = []
        workflow_ids = []

        for module in modules:
            # 创建Module节点
            module_node = Module(
                id=module.id,
                name=module.name,
                type="Module",
                repo_id=repo_id,
                description=module.description,
                summary=module.description,
                detail=module.detail,
                keywords=module.file_ids,
                confidence=module.confidence,
            )

            # 创建 Module 节点
            await helper.create_module(module_node)
            module_ids.append(module.id)

            # 关联文件到Module
            for file_id in module.file_ids:
                await helper.create_belong_to_relationship(
                    from_id=file_id,
                    to_id=module.id,
                    from_label="File",
                )

            # 创建Workflow节点
            for workflow in module.workflows:
                workflow_id = f"workflow_{uuid4().hex[:8]}"

                workflow_node = Workflow(
                    id=workflow_id,
                    name=workflow.name,
                    type="Workflow",
                    repo_id=repo_id,
                    description=workflow.description,
                    summary=workflow.description,
                    detail=workflow.description,
                    keywords=workflow.files,
                    confidence=workflow.confidence,
                    module_id=module.id,
                )

                # 创建 Workflow 节点
                await helper.create_workflow(workflow_node)
                workflow_ids.append(workflow_id)

                # 关联Workflow到Module
                await helper.create_belong_to_relationship(
                    from_id=workflow_id,
                    to_id=module.id,
                    from_label="Workflow",
                )

                # 关联文件到Workflow
                for file_id in workflow.files:
                    await helper.create_belong_to_relationship(
                        from_id=file_id,
                        to_id=workflow_id,
                        from_label="File",
                    )

        return module_ids, workflow_ids
