"""语义分析阶段处理器."""

import logging
from typing import Dict, List, Set

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.graph import Class, Method, File
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.llm.client import get_llm_service
from app.infrastructure.db import get_neo4j_client

logger = logging.getLogger(__name__)


class SemanticAnalysisStage(PipelineStageHandler):
    """语义分析阶段处理器 - 使用 LLM 生成代码摘要."""

    stage = PipelineStage.SEMANTIC_ANALYSIS

    def __init__(self):
        self.settings = get_settings()
        self.llm_service = get_llm_service()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行语义分析.

        策略：
        1. 先为所有方法生成摘要（自底向上）
        2. 使用方法的摘要生成类的摘要
        3. 使用类的摘要生成文件的摘要

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            parsed_results = context.data.get("parsed_results", {})
            repo_name = context.repo_name

            # 统计
            stats = {
                "methods_processed": 0,
                "classes_processed": 0,
                "files_processed": 0,
                "errors": 0,
            }

            # 1. 处理方法摘要（从依赖图叶子节点开始）
            logger.info("Generating method summaries...")
            method_summaries = await self._process_methods(parsed_results, repo_name)
            stats["methods_processed"] = len(method_summaries)

            # 2. 处理类摘要
            logger.info("Generating class summaries...")
            class_summaries = await self._process_classes(
                parsed_results, method_summaries, repo_name
            )
            stats["classes_processed"] = len(class_summaries)

            # 3. 处理文件摘要
            logger.info("Generating file summaries...")
            file_summaries = await self._process_files(
                parsed_results, class_summaries, method_summaries, repo_name
            )
            stats["files_processed"] = len(file_summaries)

            # 保存摘要到上下文
            context.data["method_summaries"] = method_summaries
            context.data["class_summaries"] = class_summaries
            context.data["file_summaries"] = file_summaries

            logger.info(f"Semantic analysis completed: {stats}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message="Semantic analysis completed",
                metadata=stats,
            )

        except Exception as e:
            logger.exception(f"Semantic analysis failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _process_methods(
        self,
        parsed_results: Dict,
        repo_name: str,
    ) -> Dict[str, str]:
        """处理方法摘要生成.

        Args:
            parsed_results: 解析结果
            repo_name: 仓库名

        Returns:
            方法ID到摘要的映射
        """
        method_summaries = {}
        neo4j = get_neo4j_client()

        for file_path, parse_result in parsed_results.items():
            language = parse_result.language

            # 处理类中的方法
            for class_symbol in parse_result.classes:
                class_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

                for method_symbol in class_symbol.methods:
                    method_id = f"method_{repo_name}_{file_path}_{class_symbol.name}_{method_symbol.name}"

                    # 获取被调用方法的摘要
                    callee_summaries = await self._get_callee_summaries(
                        method_symbol, method_summaries
                    )

                    try:
                        summary = await self.llm_service.generate_summary(
                            code=method_symbol.code,
                            docstring=method_symbol.docstring,
                            callee_summaries=callee_summaries,
                            node_type="method",
                            language=language,
                        )

                        method_summaries[method_id] = summary

                        # 更新 Neo4j 节点
                        await neo4j.execute_query(
                            "MATCH (m:Method {id: $id}) SET m.summary = $summary",
                            {"id": method_id, "summary": summary},
                        )

                    except Exception as e:
                        logger.warning(f"Failed to generate summary for {method_id}: {e}")
                        method_summaries[method_id] = f"Method {method_symbol.name}"

            # 处理独立方法
            for method_symbol in parse_result.methods:
                method_id = f"method_{repo_name}_{file_path}_{method_symbol.name}"

                callee_summaries = await self._get_callee_summaries(
                    method_symbol, method_summaries
                )

                try:
                    summary = await self.llm_service.generate_summary(
                        code=method_symbol.code,
                        docstring=method_symbol.docstring,
                        callee_summaries=callee_summaries,
                        node_type="method",
                        language=language,
                    )

                    method_summaries[method_id] = summary

                    # 更新 Neo4j 节点
                    await neo4j.execute_query(
                        "MATCH (m:Method {id: $id}) SET m.summary = $summary",
                        {"id": method_id, "summary": summary},
                    )

                except Exception as e:
                    logger.warning(f"Failed to generate summary for {method_id}: {e}")
                    method_summaries[method_id] = f"Method {method_symbol.name}"

        return method_summaries

    async def _process_classes(
        self,
        parsed_results: Dict,
        method_summaries: Dict[str, str],
        repo_name: str,
    ) -> Dict[str, str]:
        """处理类摘要生成.

        Args:
            parsed_results: 解析结果
            method_summaries: 方法摘要
            repo_name: 仓库名

        Returns:
            类ID到摘要的映射
        """
        class_summaries = {}
        neo4j = get_neo4j_client()

        for file_path, parse_result in parsed_results.items():
            language = parse_result.language

            for class_symbol in parse_result.classes:
                class_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

                # 收集方法的摘要
                method_summary_list = []
                for method in class_symbol.methods:
                    method_id = f"method_{repo_name}_{file_path}_{class_symbol.name}_{method.name}"
                    if method_id in method_summaries:
                        method_summary_list.append(method_summaries[method_id])

                try:
                    summary = await self.llm_service.generate_summary(
                        code=class_symbol.code,
                        docstring=class_symbol.docstring,
                        callee_summaries=method_summary_list,
                        node_type="class",
                        language=language,
                    )

                    class_summaries[class_id] = summary

                    # 更新 Neo4j 节点
                    await neo4j.execute_query(
                        "MATCH (c:Class {id: $id}) SET c.summary = $summary",
                        {"id": class_id, "summary": summary},
                    )

                except Exception as e:
                    logger.warning(f"Failed to generate summary for {class_id}: {e}")
                    class_summaries[class_id] = f"Class {class_symbol.name}"

        return class_summaries

    async def _process_files(
        self,
        parsed_results: Dict,
        class_summaries: Dict[str, str],
        method_summaries: Dict[str, str],
        repo_name: str,
    ) -> Dict[str, str]:
        """处理文件摘要生成.

        Args:
            parsed_results: 解析结果
            class_summaries: 类摘要
            method_summaries: 方法摘要
            repo_name: 仓库名

        Returns:
            文件ID到摘要的映射
        """
        file_summaries = {}
        neo4j = get_neo4j_client()

        for file_path, parse_result in parsed_results.items():
            file_id = f"file_{repo_name}_{file_path}"
            language = parse_result.language

            # 收集组件摘要
            component_summaries = []

            for class_symbol in parse_result.classes:
                class_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"
                if class_id in class_summaries:
                    component_summaries.append(
                        f"Class {class_symbol.name}: {class_summaries[class_id]}"
                    )

            for method in parse_result.methods:
                method_id = f"method_{repo_name}_{file_path}_{method.name}"
                if method_id in method_summaries:
                    component_summaries.append(
                        f"Method {method.name}: {method_summaries[method_id]}"
                    )

            try:
                # 构建文件代码（限制长度）
                file_code = "\n\n".join([
                    c.code[:500] for c in parse_result.classes[:5]
                ])

                summary = await self.llm_service.generate_summary(
                    code=file_code,
                    callee_summaries=component_summaries,
                    node_type="file",
                    language=language,
                )

                file_summaries[file_id] = summary

                # 更新 Neo4j 节点
                await neo4j.execute_query(
                    "MATCH (f:File {id: $id}) SET f.summary = $summary",
                    {"id": file_id, "summary": summary},
                )

            except Exception as e:
                logger.warning(f"Failed to generate summary for {file_id}: {e}")
                file_summaries[file_id] = f"File {file_path}"

        return file_summaries

    async def _get_callee_summaries(
        self,
        method,
        method_summaries: Dict[str, str],
    ) -> List[str]:
        """获取被调用方法的摘要.

        Args:
            method: 方法符号
            method_summaries: 已生成的方法摘要

        Returns:
            被调用方法的摘要列表
        """
        callee_summaries = []
        for call in method.calls:
            # 查找已生成摘要的被调用方法
            for method_id, summary in method_summaries.items():
                if call in method_id and summary:
                    callee_summaries.append(summary)
                    break

            # 限制数量
            if len(callee_summaries) >= 5:
                break

        return callee_summaries
