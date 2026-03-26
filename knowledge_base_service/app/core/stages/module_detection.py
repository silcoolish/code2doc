"""模块检测阶段处理器."""

import json
import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Module, Workflow
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.llm.client import get_llm_service
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)


class ModuleDetectionStage(PipelineStageHandler):
    """模块检测阶段处理器 - 使用 LLM 识别功能模块和业务流程，并构建语义图.

    Input (context.data):
        - traversal_result: TraversalResult - 遍历结果，从中读取 files 列表
        - file_summaries: Dict[str, str] - 文件ID到摘要的映射

    Output (context.data):
        - modules: List[Module] - 检测到的模块列表
        - workflows: List[Workflow] - 检测到的业务流程列表

    Side Effects:
        - 在 Neo4j 中创建 Module 和 Workflow 节点
        - 创建 File -> Module, File -> Workflow, Workflow -> Module 的 BELONG_TO 关系
        - 创建 Workflow -> Class/Method 的 CONTAIN 关系（语义图构建）
    """

    stage = PipelineStage.MODULE_DETECTION

    def __init__(self):
        self.llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行模块检测.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            # 获取文件和摘要信息（从 traversal_result 中读取）
            traversal_result = context.data.get("traversal_result")
            files = traversal_result.files if traversal_result else []
            file_summaries = context.data.get("file_summaries", {})
            repo_name = context.repo_name

            # 构建结构 JSON
            structure_json = self._build_structure_json(
                files, file_summaries, repo_name
            )

            logger.info("Detecting modules using LLM...")

            # 调用 LLM 检测模块
            modules_data = await self.llm_service.detect_modules(structure_json)

            # 创建 Module 和 Workflow 节点
            neo4j: GraphDatabaseClient = get_graph_db_client()
            created_modules = []
            created_workflows = []

            for module_data in modules_data:
                module_id = f"module_{repo_name}_{uuid4().hex[:8]}"

                module = Module(
                    id=module_id,
                    name=module_data.get("name", "Unknown Module"),
                    type="Module",
                    description=module_data.get("description", ""),
                    summary=module_data.get("description", ""),
                    keywords=module_data.get("files", []),
                    confidence=module_data.get("confidence", 0.8),
                )

                # 创建 Module 节点
                await neo4j.merge_node(
                    label="Module",
                    key_property="id",
                    key_value=module_id,
                    properties=module.to_dict(),
                )
                created_modules.append(module)

                # 关联文件到 Module
                for file_path in module_data.get("files", []):
                    file_id = f"file_{repo_name}_{file_path}"
                    await neo4j.create_relationship(
                        from_label="File",
                        from_key="id",
                        from_value=file_id,
                        to_label="Module",
                        to_key="id",
                        to_value=module_id,
                        rel_type="BELONG_TO",
                    )

                # 创建 Workflow 节点
                for workflow_data in module_data.get("workflows", []):
                    workflow_id = f"workflow_{repo_name}_{uuid4().hex[:8]}"

                    workflow = Workflow(
                        id=workflow_id,
                        name=workflow_data.get("name", "Unknown Workflow"),
                        type="Workflow",
                        description=workflow_data.get("description", ""),
                        summary=workflow_data.get("description", ""),
                        keywords=workflow_data.get("files", []),
                        confidence=workflow_data.get("confidence", 0.8),
                        module_id=module_id,
                    )

                    # 创建 Workflow 节点
                    await neo4j.merge_node(
                        label="Workflow",
                        key_property="id",
                        key_value=workflow_id,
                        properties=workflow.to_dict(),
                    )
                    created_workflows.append(workflow)

                    # 关联 Workflow 到 Module
                    await neo4j.create_relationship(
                        from_label="Workflow",
                        from_key="id",
                        from_value=workflow_id,
                        to_label="Module",
                        to_key="id",
                        to_value=module_id,
                        rel_type="BELONG_TO",
                    )

                    # 关联文件到 Workflow
                    for file_path in workflow_data.get("files", []):
                        file_id = f"file_{repo_name}_{file_path}"
                        await neo4j.create_relationship(
                            from_label="File",
                            from_key="id",
                            from_value=file_id,
                            to_label="Workflow",
                            to_key="id",
                            to_value=workflow_id,
                            rel_type="BELONG_TO",
                        )

            # 保存到上下文
            context.data["modules"] = created_modules
            context.data["workflows"] = created_workflows

            # 构建语义图关系 (从 semantic_graph_build 阶段合并过来)
            created_relations = await self._build_semantic_graph(
                neo4j, created_workflows
            )

            stats = {
                "modules_detected": len(created_modules),
                "workflows_detected": len(created_workflows),
                "semantic_relations_created": created_relations["workflow_contain"],
            }

            logger.info(f"Module detection completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Module detection and semantic graph build completed",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Module detection failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    def _build_structure_json(
        self,
        files: List,
        file_summaries: Dict[str, str],
        repo_name: str,
    ) -> Dict[str, Any]:
        """构建代码结构 JSON.

        Args:
            files: 文件列表
            file_summaries: 文件摘要
            repo_name: 仓库名

        Returns:
            结构 JSON
        """
        structure = {
            "repository": repo_name,
            "files": [],
        }

        for file_node in files:
            if file_node.file_type != "code":
                continue

            file_id = f"file_{repo_name}_{file_node.path}"
            summary = file_summaries.get(file_id, "")

            file_info = {
                "path": file_node.path,
                "name": file_node.name,
                "type": file_node.suffix,
                "summary": summary[:200] if summary else "",  # 限制长度
            }

            structure["files"].append(file_info)

        # 限制文件数量，避免超出 LLM 上下文
        if len(structure["files"]) > 100:
            structure["files"] = structure["files"][:100]
            structure["note"] = "Truncated to 100 files"

        return structure

    async def _build_semantic_graph(
        self, neo4j: GraphDatabaseClient, workflows: List[Workflow]
    ) -> Dict[str, int]:
        """构建语义图关系 - 创建 Workflow 到 Class/Method 的 CONTAIN 关系.

        Args:
            neo4j: 图数据库客户端
            workflows: 工作流列表

        Returns:
            创建的关系统计
        """
        created_relations = {"workflow_contain": 0}

        for workflow in workflows:
            # 根据 workflow.keywords 中的文件路径查找相关的 Class 和 Method
            for keyword in workflow.keywords:
                results = await neo4j.find_nodes_by_file_path(keyword)

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

        return created_relations
