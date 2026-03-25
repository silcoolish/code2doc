"""语义图构建阶段处理器."""

import logging
from typing import List

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Module, Workflow
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import get_neo4j_client

logger = logging.getLogger(__name__)


class SemanticGraphBuildStage(PipelineStageHandler):
    """语义图构建阶段处理器 - 构建语义图关系.

    Input (context.data):
        - modules: List[Module] - 模块列表
        - workflows: List[Workflow] - 业务流程列表

    Output (context.data):
        - 无直接输出

    Side Effects:
        - 在 Neo4j 中创建 Workflow 到 Class/Method 的 CONTAIN 关系
    """

    stage = PipelineStage.SEMANTIC_GRAPH_BUILD

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行语义图构建.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            neo4j = get_neo4j_client()

            # 获取模块和工作流
            modules: List[Module] = context.data.get("modules", [])
            workflows: List[Workflow] = context.data.get("workflows", [])

            created_relations = {
                "module_belong_to": 0,
                "workflow_belong_to": 0,
                "workflow_contain": 0,
            }

            # 1. 建立 Class/Method 到 Module 的 BELONG_TO 关系
            # （已在结构图构建时建立）

            # 2. 建立 Workflow 包含 Class/Method 的关系
            for workflow in workflows:
                # 这里可以根据 workflow.keywords 中的文件路径
                # 查找相关的 Class 和 Method 并建立关系
                for keyword in workflow.keywords:
                    # 简单的字符串匹配来查找相关节点
                    query = """
                    MATCH (n)
                    WHERE (n:Class OR n:Method) AND n.filePath CONTAINS $keyword
                    RETURN n.id as node_id, labels(n) as labels
                    LIMIT 10
                    """
                    results = await neo4j.execute_query(
                        query,
                        {"keyword": keyword},
                    )

                    for result in results:
                        success = await neo4j.create_relationship(
                            from_label="Workflow",
                            from_key="id",
                            from_value=workflow.id,
                            to_label=result["labels"][0],
                            to_key="id",
                            to_value=result["node_id"],
                            rel_type="CONTAIN",
                        )
                        if success:
                            created_relations["workflow_contain"] += 1

            logger.info(f"Semantic graph build completed: {created_relations}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Semantic graph built successfully",
                metadata=created_relations,
            )

        except Exception as e:
            logger.exception(f"Semantic graph build failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )
