"""向量数据库存储阶段处理器.

该阶段合并了原 embedding_generation 和 vector_db_store 的功能：
1. 从 Neo4j 查询 File/Class/Method 节点及其 summary
2. 批量生成 embedding 向量
3. 存储到 Milvus 向量数据库
4. 更新 Neo4j 节点的 embeddingId 属性
"""

import logging
from typing import Dict, List, Tuple
from uuid import uuid4

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.models.vector import (
    FileSummaryRecord,
    ClassSummaryRecord,
    MethodSummaryRecord,
)
from app.domain.llm.client import get_llm_service
from app.infrastructure.db import (
    GraphDatabaseClient,
    VectorDatabaseClient,
    get_graph_db_client,
    get_vector_db_client,
)

logger = logging.getLogger(__name__)


class VectorDBStoreStage(PipelineStageHandler):
    """向量数据库存储阶段处理器 - 提取内容、生成向量并存储.

    Input (context.data):
        - node_ids: Dict - 包含 file_ids, class_ids, method_ids（可选，如不提供则查询所有）

    Output (context.data):
        - vector_storage: Dict - 存储统计信息
          {file_vectors: int, class_vectors: int, method_vectors: int, total_vectors: int}

    Side Effects:
        - 将向量数据插入 Milvus 相应 collection
        - 更新 Neo4j 中 File, Class, Method 节点的 embeddingId 属性
    """

    stage = PipelineStage.VECTOR_DB_STORE

    def __init__(self):
        self.settings = get_settings()
        self.llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行向量存储.

        流程：
        1. 从 Neo4j 查询节点及其 summary
        2. 批量生成 embedding
        3. 存储到 Milvus
        4. 更新 Neo4j 的 embeddingId

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            neo4j: GraphDatabaseClient = get_graph_db_client()
            milvus: VectorDatabaseClient = get_vector_db_client()
            repo_name = context.repo_name

            # 1. 从 Neo4j 提取节点内容（包含 summary）
            logger.info("Extracting node contents from Neo4j...")
            node_contents = await self._extract_node_contents(neo4j, repo_name)

            if not node_contents:
                logger.warning("No node contents found for vectorization")
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                    message="No content to vectorize",
                    metadata={"file_vectors": 0, "class_vectors": 0, "method_vectors": 0, "total_vectors": 0},
                )

            # 2. 批量生成 embedding
            logger.info(f"Generating embeddings for {len(node_contents)} items...")
            vectors = await self._generate_embeddings(node_contents)

            # 3. 存储到 Milvus 并更新 Neo4j
            logger.info("Storing vectors to Milvus...")
            stats = await self._store_vectors(milvus, neo4j, vectors)

            # 保存结果到上下文
            context.data["vector_storage"] = stats

            logger.info(f"Vector storage completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Vector extraction, generation and storage completed",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Vector storage failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _extract_node_contents(
        self, neo4j: GraphDatabaseClient, repo_name: str
    ) -> List[Dict[str, str]]:
        """从 Neo4j 提取节点内容.

        查询所有 File、Class、Method 节点，获取其 id、name、summary。

        Args:
            neo4j: 图数据库客户端
            repo_name: 仓库名称

        Returns:
            节点内容列表，每项包含 type, id, name, summary
        """
        contents = []

        # 查询 File 节点
        file_results = await neo4j.get_nodes_with_summary(repo_name, "File")
        for result in file_results:
            if result.get("summary"):
                contents.append({
                    "type": "file",
                    "id": result["id"],
                    "name": result.get("name", ""),
                    "summary": result["summary"],
                    "path": result.get("path", ""),
                })

        # 查询 Class 节点
        class_results = await neo4j.get_nodes_with_summary(repo_name, "Class")
        for result in class_results:
            if result.get("summary"):
                contents.append({
                    "type": "class",
                    "id": result["id"],
                    "name": result.get("name", ""),
                    "summary": result["summary"],
                })

        # 查询 Method 节点
        method_results = await neo4j.get_nodes_with_summary(repo_name, "Method")
        for result in method_results:
            if result.get("summary"):
                contents.append({
                    "type": "method",
                    "id": result["id"],
                    "name": result.get("name", ""),
                    "summary": result["summary"],
                })

        logger.info(
            f"Extracted {len(file_results)} files, {len(class_results)} classes, "
            f"{len(method_results)} methods from Neo4j"
        )

        return contents

    async def _generate_embeddings(
        self, node_contents: List[Dict[str, str]]
    ) -> List[Tuple[str, str, str, str, List[float]]]:
        """批量生成 embedding.

        Args:
            node_contents: 节点内容列表

        Returns:
            向量列表，每项为 (type, node_id, name, summary, embedding)
        """
        # 准备批量数据
        texts = [item["summary"] for item in node_contents]

        # 批量生成向量
        embeddings = await self.llm_service.generate_embeddings(
            texts=texts,
            batch_size=self.settings.batch_size,
        )

        # 组合结果
        results = []
        for i, item in enumerate(node_contents):
            if i < len(embeddings):
                results.append((
                    item["type"],
                    item["id"],
                    item["name"],
                    item["summary"],
                    embeddings[i],
                ))

        return results

    async def _store_vectors(
        self,
        milvus: VectorDatabaseClient,
        neo4j: GraphDatabaseClient,
        vectors: List[Tuple[str, str, str, str, List[float]]],
    ) -> Dict[str, int]:
        """存储向量到 Milvus 并更新 Neo4j.

        Args:
            milvus: 向量数据库客户端
            neo4j: 图数据库客户端
            vectors: 向量列表 (type, node_id, name, summary, embedding)

        Returns:
            存储统计
        """
        file_records = []
        class_records = []
        method_records = []

        # 构建记录
        for item_type, node_id, name, summary, embedding in vectors:
            vector_id = str(uuid4())

            if item_type == "file":
                file_records.append(FileSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo="",  # 从 node_id 可以推断
                    summary=summary,
                    embedding=embedding,
                ))
            elif item_type == "class":
                class_records.append(ClassSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo="",
                    summary=summary,
                    embedding=embedding,
                ))
            elif item_type == "method":
                method_records.append(MethodSummaryRecord(
                    id=vector_id,
                    name=name,
                    node_id=node_id,
                    repo="",
                    summary=summary,
                    embedding=embedding,
                ))

        stats = {"file_vectors": 0, "class_vectors": 0, "method_vectors": 0, "total_vectors": 0}

        # 存储文件向量
        if file_records:
            records = [v.to_dict() for v in file_records]
            await milvus.insert(
                collection_name="file_summary_collection",
                records=records,
            )
            stats["file_vectors"] = len(file_records)

            # 更新 Neo4j 中的 embeddingId
            for vector in file_records:
                await neo4j.update_node_embedding_id(
                    "File", vector.node_id, vector.id
                )

            logger.info(f"Stored {len(file_records)} file vectors")

        # 存储类向量
        if class_records:
            records = [v.to_dict() for v in class_records]
            await milvus.insert(
                collection_name="class_summary_collection",
                records=records,
            )
            stats["class_vectors"] = len(class_records)

            # 更新 Neo4j
            for vector in class_records:
                await neo4j.update_node_embedding_id(
                    "Class", vector.node_id, vector.id
                )

            logger.info(f"Stored {len(class_records)} class vectors")

        # 存储方法向量
        if method_records:
            records = [v.to_dict() for v in method_records]
            await milvus.insert(
                collection_name="method_summary_collection",
                records=records,
            )
            stats["method_vectors"] = len(method_records)

            # 更新 Neo4j
            for vector in method_records:
                await neo4j.update_node_embedding_id(
                    "Method", vector.node_id, vector.id
                )

            logger.info(f"Stored {len(method_records)} method vectors")

        stats["total_vectors"] = (
            stats["file_vectors"] + stats["class_vectors"] + stats["method_vectors"]
        )
        return stats
