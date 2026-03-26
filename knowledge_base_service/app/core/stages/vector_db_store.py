"""向量存储阶段处理器."""

import logging
from typing import List

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.models.vector import (
    FileSummaryRecord,
    ClassSummaryRecord,
    MethodSummaryRecord,
)
from app.infrastructure.db import (
    GraphDatabaseClient,
    VectorDatabaseClient,
    get_milvus_client,
    get_neo4j_client,
)

logger = logging.getLogger(__name__)


class VectorDBStoreStage(PipelineStageHandler):
    """向量存储阶段处理器 - 将向量保存到 Milvus.

    Input (context.data):
        - file_vectors: List[FileSummaryRecord] - 文件向量记录列表
        - class_vectors: List[ClassSummaryRecord] - 类向量记录列表
        - method_vectors: List[MethodSummaryRecord] - 方法向量记录列表

    Output (context.data):
        - 无直接输出

    Side Effects:
        - 将向量数据插入 Milvus 相应 collection
        - 更新 Neo4j 中 File, Class, Method 节点的 embeddingId 属性
    """

    stage = PipelineStage.VECTOR_DB_STORE

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行向量存储.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            milvus: VectorDatabaseClient = get_milvus_client()
            neo4j: GraphDatabaseClient = get_neo4j_client()

            # 获取向量数据
            file_vectors: List[FileSummaryRecord] = context.data.get("file_vectors", [])
            class_vectors: List[ClassSummaryRecord] = context.data.get("class_vectors", [])
            method_vectors: List[MethodSummaryRecord] = context.data.get("method_vectors", [])

            stats = {
                "file_vectors": 0,
                "class_vectors": 0,
                "method_vectors": 0,
            }

            # 1. 存储文件向量
            if file_vectors:
                records = [v.to_dict() for v in file_vectors]
                await milvus.insert(
                    collection_name="file_summary_collection",
                    records=records,
                )
                stats["file_vectors"] = len(file_vectors)

                # 更新 Neo4j 中的 embeddingId
                for vector in file_vectors:
                    await neo4j.execute_query(
                        "MATCH (f:File {id: $id}) SET f.embeddingId = $embedding_id",
                        {"id": vector.node_id, "embedding_id": vector.id},
                    )

                logger.info(f"Stored {len(file_vectors)} file vectors")

            # 2. 存储类向量
            if class_vectors:
                records = [v.to_dict() for v in class_vectors]
                await milvus.insert(
                    collection_name="class_summary_collection",
                    records=records,
                )
                stats["class_vectors"] = len(class_vectors)

                # 更新 Neo4j
                for vector in class_vectors:
                    await neo4j.execute_query(
                        "MATCH (c:Class {id: $id}) SET c.embeddingId = $embedding_id",
                        {"id": vector.node_id, "embedding_id": vector.id},
                    )

                logger.info(f"Stored {len(class_vectors)} class vectors")

            # 3. 存储方法向量
            if method_vectors:
                records = [v.to_dict() for v in method_vectors]
                await milvus.insert(
                    collection_name="method_summary_collection",
                    records=records,
                )
                stats["method_vectors"] = len(method_vectors)

                # 更新 Neo4j
                for vector in method_vectors:
                    await neo4j.execute_query(
                        "MATCH (m:Method {id: $id}) SET m.embeddingId = $embedding_id",
                        {"id": vector.node_id, "embedding_id": vector.id},
                    )

                logger.info(f"Stored {len(method_vectors)} method vectors")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Vector storage completed",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Vector storage failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )
