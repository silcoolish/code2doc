"""依赖图构建阶段处理器."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import GraphDatabaseClient, get_neo4j_client

logger = logging.getLogger(__name__)


@dataclass
class DependencyRelation:
    """依赖关系."""

    source_id: str
    target_id: str
    rel_type: str  # CALL, INHERIT, IMPLEMENT, USE
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "rel_type": self.rel_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DependencyRelation":
        """从字典创建实例."""
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            rel_type=data["rel_type"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class DependencyResult:
    """依赖分析结果."""

    method_calls: List[DependencyRelation] = field(default_factory=list)
    class_inherits: List[DependencyRelation] = field(default_factory=list)
    class_implements: List[DependencyRelation] = field(default_factory=list)
    file_uses: List[DependencyRelation] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "method_calls": [r.to_dict() for r in self.method_calls],
            "class_inherits": [r.to_dict() for r in self.class_inherits],
            "class_implements": [r.to_dict() for r in self.class_implements],
            "file_uses": [r.to_dict() for r in self.file_uses],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DependencyResult":
        """从字典创建实例."""
        return cls(
            method_calls=[DependencyRelation.from_dict(r) for r in data.get("method_calls", [])],
            class_inherits=[DependencyRelation.from_dict(r) for r in data.get("class_inherits", [])],
            class_implements=[DependencyRelation.from_dict(r) for r in data.get("class_implements", [])],
            file_uses=[DependencyRelation.from_dict(r) for r in data.get("file_uses", [])],
        )


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
            neo4j: GraphDatabaseClient = get_neo4j_client()
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
