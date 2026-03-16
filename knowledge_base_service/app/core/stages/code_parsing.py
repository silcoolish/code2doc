"""代码解析阶段处理器."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.domain.parser.tree_sitter_parser import get_parser_for_file, ParseResult

logger = logging.getLogger(__name__)


class CodeParsingStage(PipelineStageHandler):
    """代码解析阶段处理器."""

    stage = PipelineStage.CODE_PARSING

    def __init__(self):
        self.settings = get_settings()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行代码解析.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            # 获取遍历结果
            files = context.data.get("files", [])
            repo_path = context.repo_path

            # 过滤出代码文件
            code_files = [
                f for f in files
                if f.file_type == "code" and self._is_supported_language(f.suffix)
            ]

            total_files = len(code_files)
            parsed_results: Dict[str, ParseResult] = {}
            errors = []

            logger.info(f"Parsing {total_files} code files...")

            # 批量解析文件
            batch_size = 50  # 每批处理文件数
            for i in range(0, total_files, batch_size):
                batch = code_files[i:i + batch_size]

                # 并发解析
                tasks = [
                    self._parse_file(repo_path, file_node)
                    for file_node in batch
                ]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for file_node, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        logger.warning(f"Failed to parse {file_node.path}: {result}")
                        errors.append({"file": file_node.path, "error": str(result)})
                    elif result.success:
                        parsed_results[file_node.path] = result
                    else:
                        errors.append({"file": file_node.path, "error": result.error})

                # 更新进度日志
                progress = min(100, int((i + len(batch)) / total_files * 100))
                logger.info(f"Parsing progress: {progress}% ({i + len(batch)}/{total_files})")

            # 保存结果到上下文
            context.data["parsed_results"] = parsed_results

            # 统计信息
            success_count = len(parsed_results)
            error_count = len(errors)

            metadata = {
                "total_files": total_files,
                "success_count": success_count,
                "error_count": error_count,
                "languages": self._get_language_distribution(parsed_results),
            }

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Parsed {success_count}/{total_files} files successfully",
                metadata=metadata,
            )

        except Exception as e:
            logger.exception(f"Code parsing failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _parse_file(self, repo_path: str, file_node) -> ParseResult:
        """解析单个文件.

        Args:
            repo_path: 仓库路径
            file_node: 文件节点

        Returns:
            解析结果
        """
        file_path = Path(repo_path) / file_node.path

        # 读取文件内容
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return ParseResult(
                file_path=file_node.path,
                language="unknown",
                success=False,
                error=f"Failed to read file: {e}",
            )

        # 获取解析器
        parser = get_parser_for_file(file_node.path)
        if not parser:
            return ParseResult(
                file_path=file_node.path,
                language="unknown",
                success=False,
                error=f"Unsupported language: {file_node.suffix}",
            )

        # 解析文件
        return parser.parse(file_node.path, content)

    def _is_supported_language(self, suffix: str) -> bool:
        """检查是否支持该语言.

        Args:
            suffix: 文件后缀

        Returns:
            是否支持
        """
        from app.domain.parser.tree_sitter_parser import TreeSitterParser
        return suffix.lower() in TreeSitterParser.LANGUAGE_MAP

    def _get_language_distribution(self, results: Dict[str, ParseResult]) -> Dict[str, int]:
        """获取语言分布统计.

        Args:
            results: 解析结果

        Returns:
            语言分布
        """
        distribution: Dict[str, int] = {}
        for result in results.values():
            lang = result.language
            distribution[lang] = distribution.get(lang, 0) + 1
        return distribution
