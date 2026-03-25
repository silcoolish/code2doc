"""向量化阶段处理器."""

import logging
from typing import Dict, List
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

logger = logging.getLogger(__name__)


class EmbeddingGenerationStage(PipelineStageHandler):
    """向量化阶段处理器 - 为摘要生成嵌入向量.

    Input (context.data):
        - file_summaries: Dict[str, str] - 文件ID到摘要的映射
        - class_summaries: Dict[str, str] - 类ID到摘要的映射
        - method_summaries: Dict[str, str] - 方法ID到摘要的映射

    Output (context.data):
        - file_vectors: List[FileSummaryRecord] - 文件向量记录列表
        - class_vectors: List[ClassSummaryRecord] - 类向量记录列表
        - method_vectors: List[MethodSummaryRecord] - 方法向量记录列表
    """

    stage = PipelineStage.EMBEDDING_GENERATION

    def __init__(self):
        self.settings = get_settings()
        self.llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行向量化.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            repo_name = context.repo_name

            # 获取摘要数据
            file_summaries = context.data.get("file_summaries", {})
            class_summaries = context.data.get("class_summaries", {})
            method_summaries = context.data.get("method_summaries", {})

            # 准备批量向量化数据
            batch_texts = []
            batch_items = []  # (type, id, node_id, name)

            # 收集文件摘要
            for file_id, summary in file_summaries.items():
                if summary:
                    batch_texts.append(summary)
                    file_path = file_id.replace(f"file_{repo_name}_", "")
                    batch_items.append(("file", file_id, file_id, file_path))

            # 收集类摘要
            for class_id, summary in class_summaries.items():
                if summary:
                    batch_texts.append(summary)
                    # 提取类名
                    parts = class_id.split("_")
                    class_name = parts[-1] if len(parts) > 0 else "Unknown"
                    batch_items.append(("class", class_id, class_id, class_name))

            # 收集方法摘要
            for method_id, summary in method_summaries.items():
                if summary:
                    batch_texts.append(summary)
                    # 提取方法名
                    parts = method_id.split("_")
                    method_name = parts[-1] if len(parts) > 0 else "Unknown"
                    batch_items.append(("method", method_id, method_id, method_name))

            logger.info(f"Generating embeddings for {len(batch_texts)} items...")

            # 批量生成向量
            embeddings = await self.llm_service.generate_embeddings(
                texts=batch_texts,
                batch_size=self.settings.batch_size,
            )

            # 构建向量记录
            file_vectors = []
            class_vectors = []
            method_vectors = []

            for i, (item_type, node_id, _, name) in enumerate(batch_items):
                if i >= len(embeddings):
                    break

                embedding = embeddings[i]
                vector_id = str(uuid4())

                if item_type == "file":
                    file_vectors.append(FileSummaryRecord(
                        id=vector_id,
                        name=name,
                        node_id=node_id,
                        repo=repo_name,
                        summary=batch_texts[i],
                        embedding=embedding,
                    ))
                elif item_type == "class":
                    class_vectors.append(ClassSummaryRecord(
                        id=vector_id,
                        name=name,
                        node_id=node_id,
                        repo=repo_name,
                        summary=batch_texts[i],
                        embedding=embedding,
                    ))
                elif item_type == "method":
                    method_vectors.append(MethodSummaryRecord(
                        id=vector_id,
                        name=name,
                        node_id=node_id,
                        repo=repo_name,
                        summary=batch_texts[i],
                        embedding=embedding,
                    ))

            # 保存到上下文
            context.data["file_vectors"] = file_vectors
            context.data["class_vectors"] = class_vectors
            context.data["method_vectors"] = method_vectors

            stats = {
                "file_vectors": len(file_vectors),
                "class_vectors": len(class_vectors),
                "method_vectors": len(method_vectors),
                "total_vectors": len(file_vectors) + len(class_vectors) + len(method_vectors),
            }

            logger.info(f"Embedding generation completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Embedding generation completed",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Embedding generation failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )
