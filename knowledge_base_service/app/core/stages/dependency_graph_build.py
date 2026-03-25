"""依赖图构建阶段处理器."""

import logging
from typing import List

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_neo4j_client
from app.core.stages.dependency_analysis import DependencyResult

logger = logging.getLogger(__name__)


class DependencyGraphBuildStage(PipelineStageHandler):
    """依赖图构建阶段处理器.

    Input (context.data):
        - dependencies: DependencyResult - 依赖分析结果，包含 method_calls, class_inherits,
          class_implements, file_uses 等关系列表

    Output (context.data):
        - 无直接输出，结果写入 Neo4j

    Side Effects:
        - 在 Neo4j 中创建方法调用(CALL)、类继承(INHERIT)、接口实现(IMPLEMENT)、
          文件使用(USE)等关系
    """

    stage = PipelineStage.DEPENDENCY_GRAPH_BUILD

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行依赖图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            neo4j = get_neo4j_client()
            dependencies: DependencyResult = context.data.get("dependencies")

            if not dependencies:
                logger.warning("No dependency data found, skipping dependency graph build")
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                    message="No dependencies to build",
                    metadata={},
                )

            created_relations = {
                "method_calls": 0,
                "class_inherits": 0,
                "class_implements": 0,
                "file_uses": 0,
            }

            # 1. 创建方法调用关系
            for rel in dependencies.method_calls:
                success = await neo4j.create_relationship(
                    from_label="Method",
                    from_key="id",
                    from_value=rel.source_id,
                    to_label="Method",
                    to_key="id",
                    to_value=rel.target_id,
                    rel_type="CALL",
                    properties=rel.metadata,
                )
                if success:
                    created_relations["method_calls"] += 1

            logger.info(f"Created {created_relations['method_calls']} method call relations")

            # 2. 创建类继承关系
            for rel in dependencies.class_inherits:
                success = await neo4j.create_relationship(
                    from_label="Class",
                    from_key="id",
                    from_value=rel.source_id,
                    to_label="Class",
                    to_key="id",
                    to_value=rel.target_id,
                    rel_type="INHERIT",
                )
                if success:
                    created_relations["class_inherits"] += 1

            logger.info(f"Created {created_relations['class_inherits']} class inherit relations")

            # 3. 创建接口实现关系
            for rel in dependencies.class_implements:
                success = await neo4j.create_relationship(
                    from_label="Class",
                    from_key="id",
                    from_value=rel.source_id,
                    to_label="Class",
                    to_key="id",
                    to_value=rel.target_id,
                    rel_type="IMPLEMENT",
                )
                if success:
                    created_relations["class_implements"] += 1

            # 4. 创建文件使用关系
            for rel in dependencies.file_uses:
                success = await neo4j.create_relationship(
                    from_label="File",
                    from_key="id",
                    from_value=rel.source_id,
                    to_label="File",
                    to_key="id",
                    to_value=rel.target_id,
                    rel_type="USE",
                )
                if success:
                    created_relations["file_uses"] += 1

            logger.info(f"Created {created_relations['file_uses']} file use relations")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Dependency graph built successfully",
                metadata=created_relations,
            )

        except Exception as e:
            logger.exception(f"Dependency graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )
