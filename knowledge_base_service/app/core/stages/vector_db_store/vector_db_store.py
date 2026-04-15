"""向量数据库存储阶段处理器.

该阶段合并了原 embedding_generation 和 vector_db_store 的功能：
1. 从图数据库分页查询 File/Class/Method/Module/Workflow 节点及其 summary
2. 分批生成 embedding 向量
3. 分批存储到向量数据库
4. 批量更新图数据库节点的 embeddingId 属性
"""

import logging
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.models.vector import (
    FileSummaryRecord,
    ClassSummaryRecord,
    MethodSummaryRecord,
    SemanticSummaryRecord,
)
from app.domain.llm import get_llm_service
from app.infrastructure.db import (
    GraphDatabaseClient,
    VectorDatabaseClient,
    get_graph_db_client,
    get_vector_db_client,
)

logger = logging.getLogger(__name__)


class VectorDBStoreStage(PipelineStageHandler):
    """向量数据库存储阶段处理器 - 分页提取内容、分批生成向量并存储.

    Input (context.data):
        - node_ids: Dict - 包含 file_ids, class_ids, method_ids（可选，如不提供则查询所有）

    Output (context.data):
        - vector_storage: Dict - 存储统计信息
          {file_vectors: int, class_vectors: int, method_vectors: int, semantic_vectors: int, total_vectors: int}

    Side Effects:
        - 将向量数据分批插入向量数据库相应 collection
        - 批量更新图数据库中 File, Class, Method, Module, Workflow 节点的 embeddingId 属性
    """

    stage = PipelineStage.VECTOR_DB_STORE
    weight = 1.5  # 向量存储

    def __init__(self):
        self.settings = get_settings()
        self.llm_service = get_llm_service()
        self.graph_db: GraphDatabaseClient = get_graph_db_client()
        self.vector_db: VectorDatabaseClient = get_vector_db_client()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行向量存储.

        流程：
        1. 按节点类型分页从图数据库查询节点及其 summary
        2. 分批生成 embedding
        3. 分批存储到向量数据库
        4. 批量更新图数据库的 embeddingId

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            repo_id = getattr(context, 'repo_id', context.repo_name)  # 获取初始化时传入的 repo_id
            batch_size = self.settings.batch_size

            # 初始化统计信息
            stats = {
                "file_vectors": 0,
                "class_vectors": 0,
                "method_vectors": 0,
                "semantic_vectors": 0,
                "total_vectors": 0,
            }

            # 定义要处理的节点类型配置
            # (node_type, stat_key, collection_name, is_semantic)
            node_type_configs = [
                ("File", "file_vectors", "file_summary_collection", False),
                ("Class", "class_vectors", "class_summary_collection", False),
                ("Method", "method_vectors", "method_summary_collection", False),
                ("Module", "semantic_vectors", "semantic_summary_collection", True),
                ("Workflow", "semantic_vectors", "semantic_summary_collection", True),
            ]

            # 顺序处理各类型节点（降低并发复杂度，控制内存使用）
            for node_type, stat_key, collection_name, is_semantic in node_type_configs:
                context.stage_msg = f"正在处理 {node_type} 节点..."
                count = await self._process_node_type_in_batches(
                    graph_db=self.graph_db,
                    vector_db=self.vector_db,
                    repo_id=repo_id,
                    node_type=node_type,
                    collection_name=collection_name,
                    stat_key=stat_key,
                    is_semantic=is_semantic,
                    batch_size=batch_size,
                    context=context,
                )
                stats[stat_key] += count
                stats["total_vectors"] += count

            # 保存结果到上下文
            context.data["vector_storage"] = stats

            context.stage_msg = f"向量存储完成：共 {stats['total_vectors']} 个向量"
            logger.info(f"Vector storage completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Vector extraction, generation and storage completed with pagination",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Vector storage failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _process_node_type_in_batches(
        self,
        graph_db: GraphDatabaseClient,
        vector_db: VectorDatabaseClient,
        repo_id: str,
        node_type: str,
        collection_name: str,
        stat_key: str,
        is_semantic: bool,
        batch_size: int = 100,
        context: PipelineContext = None,
    ) -> int:
        """分页处理指定类型的节点.

        Args:
            graph_db: 图数据库客户端
            vector_db: 向量数据库客户端
            repo_id: 仓库ID
            node_type: 节点类型 (File, Class, Method, Module, Workflow)
            collection_name: 向量数据库 collection 名称
            stat_key: 统计信息中的键名
            is_semantic: 是否为语义节点 (Module/Workflow)
            batch_size: 每批处理的节点数

        Returns:
            处理的向量数量
        """
        # 获取总数用于进度计算
        total = await graph_db.count_nodes_with_summary(repo_id, node_type)
        if total == 0:
            logger.debug(f"No {node_type} nodes found for repo: {repo_id}")
            return 0

        logger.info(f"Processing {total} {node_type} nodes in batches of {batch_size}")

        total_processed = 0
        skip = 0

        while skip < total:
            # 1. 分页查询节点
            nodes = await graph_db.get_nodes_with_summary_paginated(
                repo_id=repo_id,
                node_type=node_type,
                skip=skip,
                limit=batch_size,
            )

            if not nodes:
                break

            # 2. 转换节点数据并生成 embedding
            contents = self._convert_nodes_to_contents(nodes, node_type)
            vectors = await self._generate_embeddings_for_batch(contents)

            if not vectors:
                logger.warning(f"No embeddings generated for {node_type} batch (skip={skip})")
                skip += len(nodes)
                continue

            # 3. 构建记录并存储到向量数据库
            records, updates = self._build_records_and_updates(
                vectors=vectors,
                contents=contents,  # 传入 contents 以获取 detail 信息
                node_type=node_type,
                is_semantic=is_semantic,
                repo_id=repo_id,
            )

            if records:
                await vector_db.insert(collection_name, records)

            # 4. 批量更新图数据库的 embeddingId
            if updates:
                updated_count = await graph_db.update_node_embedding_ids_batch(
                    label=node_type,
                    updates=updates,
                )
                if updated_count != len(updates):
                    logger.warning(
                        f"Updated {updated_count}/{len(updates)} {node_type} embeddingIds"
                    )

            total_processed += len(records)
            skip += len(nodes)

            progress_msg = f"{node_type} 节点处理: {min(skip, total)}/{total}"
            if context:
                context.stage_msg = progress_msg
            logger.info(
                f"{node_type} progress: {min(skip, total)}/{total} "
                f"(batch: {len(records)} vectors)"
            )

        completion_msg = f"已完成 {total_processed} 个 {node_type} 向量"
        if context:
            context.stage_msg = completion_msg
        logger.info(f"Completed processing {total_processed} {node_type} vectors")
        return total_processed

    def _convert_nodes_to_contents(
        self, nodes: List[Dict[str, str]], node_type: str
    ) -> List[Dict[str, str]]:
        """将节点数据转换为内容列表.

        Args:
            nodes: 节点列表
            node_type: 节点类型

        Returns:
            内容列表，每项包含 type, id, name, summary, detail(可选), path(可选)
        """
        contents = []
        type_lower = node_type.lower()
        is_semantic = node_type in ["Module", "Workflow"]

        for node in nodes:
            summary = node.get("summary")
            if not summary or not isinstance(summary, str) or not summary.strip():
                continue

            content = {
                "type": type_lower,
                "id": node["id"],
                "name": node.get("name", ""),
                "summary": summary.strip(),
            }

            # File 节点包含 path
            if node_type == "File" and "path" in node:
                content["path"] = node["path"]

            # Module/Workflow 节点包含 detail
            if is_semantic:
                detail = node.get("detail")
                if detail and isinstance(detail, str) and detail.strip():
                    content["detail"] = detail.strip()

            contents.append(content)

        return contents

    async def _generate_embeddings_for_batch(
        self, contents: List[Dict[str, str]]
    ) -> List[Tuple[str, str, str, str, List[float], Optional[str]]]:
        """为一批内容生成 embedding.

        只使用 summary 生成 embedding，detail 仅作为附加字段存储。

        Args:
            contents: 内容列表，每项包含 type, id, name, summary, detail(可选)

        Returns:
            向量列表，每项为 (type, node_id, name, summary, embedding, detail)
            - detail: 如果是语义节点则包含detail内容，否则为None
        """
        if not contents:
            return []

        # 只使用 summary 生成 embedding
        texts = [item["summary"] for item in contents]

        try:
            # 批量生成向量
            embeddings = await self.llm_service.generate_embeddings(
                texts=texts,
                batch_size=self.settings.batch_size,
            )
        except Exception as e:
            logger.error(f"Failed to generate embeddings for batch: {e}")
            return []

        # 组合结果
        results = []
        for i, item in enumerate(contents):
            if i >= len(embeddings):
                continue

            detail = item.get("detail") if item["type"] in ["module", "workflow"] else None

            results.append((
                item["type"],
                item["id"],
                item["name"],
                item["summary"],
                embeddings[i],
                detail,
            ))

        return results

    def _build_records_and_updates(
        self,
        vectors: List[Tuple[str, str, str, str, List[float], Optional[str]]],
        contents: List[Dict[str, str]],
        node_type: str,
        is_semantic: bool,
        repo_id: str,
    ) -> Tuple[List[Dict], List[Tuple[str, str]]]:
        """构建向量数据库记录和图数据库更新列表.

        Args:
            vectors: 向量列表，每项为 (type, node_id, name, summary, embedding, detail)
            contents: 原始内容列表，用于获取额外字段如 path
            node_type: 节点类型
            is_semantic: 是否为语义节点
            repo_id: 仓库ID

        Returns:
            (records, updates) 元组
            - records: 向量数据库记录列表
            - updates: 图数据库更新列表，每项为 (node_id, embedding_id)
        """
        records = []
        updates = []
        updated_nodes = set()  # 用于去重，确保每个节点只更新一次embeddingId

        # 构建 contents 字典，方便通过 id 查找
        contents_map = {item["id"]: item for item in contents}

        for item_type, node_id, name, summary, embedding, detail in vectors:
            vector_id = str(uuid4())
            content = contents_map.get(node_id, {})

            if is_semantic:
                # Module 或 Workflow - 合并 summary 和 detail 在一个记录中
                record = SemanticSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo=repo_id,
                    repo_id=repo_id,
                    type=node_type,
                    summary=summary,
                    detail=detail or "",  # detail 作为字段存储，但不用于 embedding
                    embedding=embedding,
                )
                records.append(record.to_dict())
                if node_id not in updated_nodes:
                    updates.append((node_id, vector_id))
                    updated_nodes.add(node_id)
            elif item_type == "file":
                record = FileSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo=repo_id,
                    repo_id=repo_id,
                    summary=summary,
                    embedding=embedding,
                )
                records.append(record.to_dict())
                if node_id not in updated_nodes:
                    updates.append((node_id, vector_id))
                    updated_nodes.add(node_id)
            elif item_type == "class":
                record = ClassSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo=repo_id,
                    repo_id=repo_id,
                    summary=summary,
                    embedding=embedding,
                )
                records.append(record.to_dict())
                if node_id not in updated_nodes:
                    updates.append((node_id, vector_id))
                    updated_nodes.add(node_id)
            elif item_type == "method":
                record = MethodSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo=repo_id,
                    repo_id=repo_id,
                    summary=summary,
                    embedding=embedding,
                )
                records.append(record.to_dict())
                if node_id not in updated_nodes:
                    updates.append((node_id, vector_id))
                    updated_nodes.add(node_id)

        return records, updates
