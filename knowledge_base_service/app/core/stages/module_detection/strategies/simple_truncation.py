"""简单截断策略 - 原方案实现."""

import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.domain.models.graph import Module, Workflow
from app.domain.models.pipeline import PipelineContext
from app.infrastructure.db import GraphDatabaseClient

from .base import ModuleDetectionResult, ModuleDetectionStrategy

logger = logging.getLogger(__name__)


class SimpleTruncationStrategy(ModuleDetectionStrategy):
    """简单截断策略 - 原方案实现.

    特点:
    - 限制最大文件数（默认100）
    - 简单切片截断
    - 单次LLM调用
    - 适合小型仓库（<100文件）

    Example:
        ```python
        strategy = SimpleTruncationStrategy(max_files=100)
        result = await strategy.detect_modules(
            context=context,
            repo_id="repo_123",
            file_summaries=file_summaries,
            neo4j_client=neo4j,
            llm_service=llm,
        )
        ```
    """

    def __init__(self, max_files: int = 100):
        """初始化策略.

        Args:
            max_files: 最大处理文件数，默认100
        """
        self.max_files = max_files

    @property
    def name(self) -> str:
        """策略名称."""
        return "simple"

    @property
    def description(self) -> str:
        """策略描述."""
        return f"简单截断策略 - 限制最大{self.max_files}个文件，适合小型仓库"

    def validate_config(self) -> bool:
        """验证配置.

        Returns:
            True if max_files > 0
        """
        return self.max_files > 0

    async def detect_modules(
        self,
        context: PipelineContext,
        repo_id: str,
        file_summaries: Dict[str, str],
        neo4j_client: GraphDatabaseClient,
        llm_service: Any,
    ) -> ModuleDetectionResult:
        """执行模块检测.

        Args:
            context: Pipeline上下文
            repo_id: 仓库ID
            file_summaries: 文件ID到摘要的映射
            neo4j_client: Neo4j客户端
            llm_service: LLM服务

        Returns:
            ModuleDetectionResult: 检测结果
        """
        # 获取遍历结果
        traversal_result = context.data.get("traversal_result")
        files = traversal_result.files if traversal_result else []

        context.stage_msg = "正在构建代码结构信息..."

        # 构建结构JSON
        structure_json = self._build_structure_json(
            files, file_summaries, repo_id
        )

        context.stage_msg = "正在使用 LLM 检测模块..."
        logger.info("Detecting modules using LLM (simple strategy)...")

        # 调用LLM检测模块
        modules_data = await llm_service.detect_modules(structure_json)

        # 创建Module和Workflow节点
        context.stage_msg = "正在创建模块节点..."

        created_modules = []
        created_workflows = []

        for idx, module_data in enumerate(modules_data):
            context.stage_msg = f"正在创建模块节点: {idx + 1}/{len(modules_data)}"
            module_id = f"module_{repo_id}_{uuid4().hex[:8]}"

            module = Module(
                id=module_id,
                name=module_data.get("name", "Unknown Module"),
                type="Module",
                repo_id=repo_id,
                description=module_data.get("description", ""),
                summary=module_data.get("description", ""),
                detail=module_data.get("detail", module_data.get("description", "")),
                keywords=module_data.get("files", []),
                confidence=module_data.get("confidence", 0.8),
            )

            # 创建Module节点
            module_props = module.to_dict()
            module_props["repo"] = repo_id
            await neo4j_client.merge_node(
                label="Module",
                key_property="id",
                key_value=module_id,
                properties=module_props,
            )
            created_modules.append(module)

            # 关联文件到Module
            for file_path in module_data.get("files", []):
                file_id = f"file_{repo_id}_{file_path}"
                await neo4j_client.create_relationship(
                    from_label="File",
                    from_key="id",
                    from_value=file_id,
                    to_label="Module",
                    to_key="id",
                    to_value=module_id,
                    rel_type="BELONG_TO",
                )

            # 创建Workflow节点
            for workflow_data in module_data.get("workflows", []):
                workflow_id = f"workflow_{repo_id}_{uuid4().hex[:8]}"

                workflow = Workflow(
                    id=workflow_id,
                    name=workflow_data.get("name", "Unknown Workflow"),
                    type="Workflow",
                    repo_id=repo_id,
                    description=workflow_data.get("description", ""),
                    summary=workflow_data.get("description", ""),
                    detail=workflow_data.get(
                        "detail", workflow_data.get("description", "")
                    ),
                    keywords=workflow_data.get("files", []),
                    confidence=workflow_data.get("confidence", 0.8),
                    module_id=module_id,
                )

                # 创建Workflow节点
                workflow_props = workflow.to_dict()
                workflow_props["repo"] = repo_id
                await neo4j_client.merge_node(
                    label="Workflow",
                    key_property="id",
                    key_value=workflow_id,
                    properties=workflow_props,
                )
                created_workflows.append(workflow)

                # 关联Workflow到Module
                await neo4j_client.create_relationship(
                    from_label="Workflow",
                    from_key="id",
                    from_value=workflow_id,
                    to_label="Module",
                    to_key="id",
                    to_value=module_id,
                    rel_type="BELONG_TO",
                )

                # 关联文件到Workflow
                for file_path in workflow_data.get("files", []):
                    file_id = f"file_{repo_id}_{file_path}"
                    await neo4j_client.create_relationship(
                        from_label="File",
                        from_key="id",
                        from_value=file_id,
                        to_label="Workflow",
                        to_key="id",
                        to_value=workflow_id,
                        rel_type="BELONG_TO",
                    )

        # 构建语义图关系
        created_relations = await self._build_semantic_graph(
            neo4j_client, created_workflows
        )

        stats = {
            "modules_detected": len(created_modules),
            "workflows_detected": len(created_workflows),
            "semantic_relations_created": created_relations["workflow_contain"],
            "truncated": len(files) > self.max_files,
            "total_files": len(files),
            "processed_files": min(len(files), self.max_files),
        }

        context.stage_msg = (
            f"模块检测完成: {len(created_modules)} 个模块, "
            f"{len(created_workflows)} 个工作流"
        )
        logger.info(f"Module detection completed: {stats}")

        return ModuleDetectionResult(
            module_ids=[m.id for m in created_modules],
            workflow_ids=[w.id for w in created_workflows],
            metadata=stats,
        )

    def _build_structure_json(
        self,
        files: List,
        file_summaries: Dict[str, str],
        repo_id: str,
    ) -> Dict[str, Any]:
        """构建代码结构JSON.

        Args:
            files: 文件列表
            file_summaries: 文件摘要
            repo_id: 仓库ID

        Returns:
            结构JSON字典
        """
        structure = {
            "repository": repo_id,
            "files": [],
        }

        for file_node in files:
            if file_node.file_type != "code":
                continue

            file_id = f"file_{repo_id}_{file_node.path}"
            summary = file_summaries.get(file_id, "")

            file_info = {
                "path": file_node.path,
                "name": file_node.name,
                "type": file_node.suffix,
                "summary": summary[:200] if summary else "",
            }

            structure["files"].append(file_info)

        # 限制文件数量，避免超出LLM上下文
        if len(structure["files"]) > self.max_files:
            structure["files"] = structure["files"][: self.max_files]
            structure["note"] = f"Truncated to {self.max_files} files"
            logger.warning(
                f"Files truncated: {len(files)} -> {self.max_files}"
            )

        return structure

    async def _build_semantic_graph(
        self,
        neo4j: GraphDatabaseClient,
        workflows: List[Workflow],
    ) -> Dict[str, int]:
        """构建语义图关系.

        Args:
            neo4j: 图数据库客户端
            workflows: 工作流列表

        Returns:
            创建的关系统计
        """
        created_relations = {"workflow_contain": 0}

        for workflow in workflows:
            # 根据workflow.keywords中的文件路径查找相关的Class和Method
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
