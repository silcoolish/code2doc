"""依赖分析阶段处理器."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional

from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.parser.code_parser import ParseResult, MethodSymbol, ClassSymbol

logger = logging.getLogger(__name__)


@dataclass
class DependencyRelation:
    """依赖关系."""
    source_id: str
    target_id: str
    rel_type: str  # CALL, INHERIT, IMPLEMENT, USE
    metadata: Dict = field(default_factory=dict)


@dataclass
class DependencyResult:
    """依赖分析结果."""
    method_calls: List[DependencyRelation] = field(default_factory=list)
    class_inherits: List[DependencyRelation] = field(default_factory=list)
    class_implements: List[DependencyRelation] = field(default_factory=list)
    file_uses: List[DependencyRelation] = field(default_factory=list)


class DependencyAnalysisStage(PipelineStageHandler):
    """依赖分析阶段处理器.

    Input (context.data):
        - parsed_results: Dict[str, ParseResult] - 代码解析结果，包含 classes, methods, imports, calls

    Output (context.data):
        - dependencies: DependencyResult - 依赖分析结果，包含:
          - method_calls: List[DependencyRelation] - 方法调用关系
          - class_inherits: List[DependencyRelation] - 类继承关系
          - class_implements: List[DependencyRelation] - 接口实现关系
          - file_uses: List[DependencyRelation] - 文件使用关系
    """

    stage = PipelineStage.DEPENDENCY_ANALYSIS

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行依赖分析.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            parsed_results: Dict[str, ParseResult] = context.data.get("parsed_results", {})
            repo_name = context.repo_name

            dependencies = DependencyResult()

            # 构建符号索引用于查找
            method_index = self._build_method_index(parsed_results, repo_name)
            class_index = self._build_class_index(parsed_results, repo_name)

            # 分析方法调用
            for file_path, parse_result in parsed_results.items():
                file_id = f"file_{repo_name}_{file_path}"

                # 分析类中的方法调用
                for class_symbol in parse_result.classes:
                    class_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"

                    # 分析继承关系
                    if class_symbol.base_classes:
                        for base_class in class_symbol.base_classes:
                            if base_class in class_index:
                                target_id = class_index[base_class]
                                dependencies.class_inherits.append(
                                    DependencyRelation(
                                        source_id=class_id,
                                        target_id=target_id,
                                        rel_type="INHERIT",
                                    )
                                )

                    # 分析方法调用
                    for method_symbol in class_symbol.methods:
                        method_id = f"method_{repo_name}_{file_path}_{class_symbol.name}_{method_symbol.name}"

                        for call in method_symbol.calls:
                            # 查找被调用的方法
                            if call in method_index:
                                target_ids = method_index[call]
                                for target_id in target_ids:
                                    if target_id != method_id:  # 避免自调用
                                        dependencies.method_calls.append(
                                            DependencyRelation(
                                                source_id=method_id,
                                                target_id=target_id,
                                                rel_type="CALL",
                                                metadata={"caller": method_symbol.name},
                                            )
                                        )

                # 分析独立方法调用
                for method_symbol in parse_result.methods:
                    method_id = f"method_{repo_name}_{file_path}_{method_symbol.name}"

                    for call in method_symbol.calls:
                        if call in method_index:
                            target_ids = method_index[call]
                            for target_id in target_ids:
                                if target_id != method_id:
                                    dependencies.method_calls.append(
                                        DependencyRelation(
                                            source_id=method_id,
                                            target_id=target_id,
                                            rel_type="CALL",
                                        )
                                    )

                # 分析文件使用关系（基于 import）
                for import_stmt in parse_result.imports:
                    # 简单匹配：查找可能相关的文件
                    related_files = self._find_related_files(import_stmt, parsed_results, file_path)
                    for related_file in related_files:
                        related_id = f"file_{repo_name}_{related_file}"
                        dependencies.file_uses.append(
                            DependencyRelation(
                                source_id=file_id,
                                target_id=related_id,
                                rel_type="USE",
                            )
                        )

            # 保存结果
            context.data["dependencies"] = dependencies

            metadata = {
                "method_calls": len(dependencies.method_calls),
                "class_inherits": len(dependencies.class_inherits),
                "file_uses": len(dependencies.file_uses),
            }

            logger.info(f"Dependency analysis completed: {metadata}")

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Dependency analysis completed",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"Dependency analysis failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    def _build_method_index(
        self,
        parsed_results: Dict[str, ParseResult],
        repo_name: str,
    ) -> Dict[str, List[str]]:
        """构建方法名到ID的索引.

        Args:
            parsed_results: 解析结果
            repo_name: 仓库名

        Returns:
            方法索引
        """
        index: Dict[str, List[str]] = {}

        for file_path, parse_result in parsed_results.items():
            # 类中的方法
            for class_symbol in parse_result.classes:
                for method in class_symbol.methods:
                    method_id = f"method_{repo_name}_{file_path}_{class_symbol.name}_{method.name}"
                    if method.name not in index:
                        index[method.name] = []
                    index[method.name].append(method_id)

            # 独立方法
            for method in parse_result.methods:
                method_id = f"method_{repo_name}_{file_path}_{method.name}"
                if method.name not in index:
                    index[method.name] = []
                index[method.name].append(method_id)

        return index

    def _build_class_index(
        self,
        parsed_results: Dict[str, ParseResult],
        repo_name: str,
    ) -> Dict[str, str]:
        """构建类名到ID的索引.

        Args:
            parsed_results: 解析结果
            repo_name: 仓库名

        Returns:
            类索引
        """
        index: Dict[str, str] = {}

        for file_path, parse_result in parsed_results.items():
            for class_symbol in parse_result.classes:
                class_id = f"class_{repo_name}_{file_path}_{class_symbol.name}"
                index[class_symbol.name] = class_id

        return index

    def _find_related_files(
        self,
        import_stmt: str,
        parsed_results: Dict[str, ParseResult],
        current_file: str,
    ) -> List[str]:
        """根据 import 语句查找相关文件.

        Args:
            import_stmt: import 语句
            parsed_results: 解析结果
            current_file: 当前文件

        Returns:
            相关文件列表
        """
        related = []

        # 提取可能的模块名
        import_parts = import_stmt.replace(".", "/").split("/")
        if not import_parts:
            return related

        # 尝试匹配文件名
        for file_path in parsed_results.keys():
            if file_path == current_file:
                continue

            # 简单匹配：import 中包含文件名
            file_name = file_path.split("/")[-1].replace(".py", "").replace(".java", "")
            for part in import_parts:
                if part and file_name.lower() in part.lower():
                    related.append(file_path)
                    break

        return related[:5]  # 限制相关文件数量
