"""流程图生成阶段处理器.

该阶段为Method节点生成流程图：
1. 查询所有C/CPP语言的Method节点，按文件分组
2. 调用批量流程图生成服务API
3. 从archive_url下载压缩包并解压到 data/{repo_id}/image 目录
4. 更新Method节点的image属性

当前仅支持C/CPP语言，使用HTTP调用流程图生成服务。
"""

import asyncio
import logging
import os
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiohttp

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)

# 获取项目根目录（基于当前文件位置：app/core/stages/flowchart_generation/）
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


class FlowchartGenerationStage(PipelineStageHandler):
    """流程图生成阶段处理器.

    为C/CPP语言的Method节点批量生成流程图。

    Input (context.data):
        - repo_id: str - 仓库ID

    Output (context.data):
        - flowchart_generation: Dict - 生成的流程图统计
          {total_methods: int, generated_count: int, skipped_count: int, failed_count: int}

    Side Effects:
        - 在图数据库中更新Method节点的image属性
        - 在data/{repo_id}/image目录下保存流程图图片
    """

    stage = PipelineStage.FLOWCHART_GENERATION
    weight = 1.0  # 流程图生成

    def __init__(self):
        self.graph_db: GraphDatabaseClient = get_graph_db_client()
        self.settings = get_settings()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行流程图生成.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            repo_id = getattr(context, 'repo_id', context.repo_name)

            # 确保图片目录存在
            # 使用相对于项目根目录的路径
            flowchart_dir = self.settings.flowchart_image_dir
            if flowchart_dir.startswith("./"):
                flowchart_dir = flowchart_dir[2:]
            if flowchart_dir.startswith("/"):
                image_base = Path(flowchart_dir)
            else:
                image_base = BASE_DIR / flowchart_dir

            image_dir = image_base / repo_id / "image"
            image_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Flowchart image directory: {image_dir}")

            # 获取支持的语言
            supported_languages = self.settings.flowchart_supported_languages
            context.stage_msg = f"正在查询 {','.join(supported_languages)} 语言的Method节点..."

            # 获取指定语言的Method节点，按文件分组
            file_methods = await self._get_methods_grouped_by_file(repo_id, supported_languages)
            if not file_methods:
                context.stage_msg = "没有找到需要生成流程图的Method节点"
                logger.info("No methods found for flowchart generation")
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                    message="No methods found for flowchart generation",
                    metadata={
                        "total_methods": 0,
                        "generated_count": 0,
                        "skipped_count": 0,
                        "failed_count": 0,
                    },
                )

            # 获取所有文件路径
            file_paths = list(file_methods.keys())
            total_methods = sum(len(methods) for methods in file_methods.values())
            generated_count = 0
            skipped_count = 0
            failed_count = 0

            context.stage_msg = f"找到 {len(file_paths)} 个文件，共 {total_methods} 个Method节点，开始批量生成流程图..."
            logger.info(f"Found {len(file_paths)} files with {total_methods} methods for flowchart generation")

            # 获取所有文件的完整代码
            file_contents = await self._get_file_contents(repo_id, file_paths)

            # 过滤掉没有代码内容的文件
            valid_files = {fp: content for fp, content in file_contents.items() if content}
            if not valid_files:
                context.stage_msg = "没有找到有效的文件内容"
                logger.warning("No valid file contents found")
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                    message="No valid file contents found",
                    metadata={
                        "total_methods": total_methods,
                        "generated_count": 0,
                        "skipped_count": 0,
                        "failed_count": total_methods,
                    },
                )

            # 检查断点续传：过滤掉所有方法都已有图片的文件
            files_to_process = {}
            for file_path, content in valid_files.items():
                methods = file_methods.get(file_path, [])
                methods_need_generation = []
                path_slug = self._generate_path_slug(file_path)

                for method in methods:
                    existing_image = method.get("image", "")
                    if existing_image:
                        # 检查是否存在已生成的图片（多种可能的命名格式，包括svg和png）
                        possible_paths = [
                            image_dir / f"{existing_image}.svg",
                            image_dir / f"{existing_image}.png",
                            image_dir / f"{path_slug}_{method.get('name', '')}__L{method.get('start_line', 0)}.svg",
                            image_dir / f"{path_slug}_{method.get('name', '')}__L{method.get('start_line', 0)}.png",
                        ]
                        if any(p.exists() for p in possible_paths):
                            skipped_count += 1
                            continue
                    methods_need_generation.append(method)

                if methods_need_generation:
                    files_to_process[file_path] = {
                        "content": content,
                        "methods": methods_need_generation,
                    }
                else:
                    logger.debug(f"Skipping file {file_path}, all methods have flowcharts")

            if not files_to_process:
                context.stage_msg = f"所有流程图都已存在，跳过生成 ({skipped_count} 个)"
                logger.info(f"All flowcharts already exist, skipped {skipped_count} methods")
                return StageResult(
                    stage=self.stage,
                    status=PipelineStatus.COMPLETED,
                    message=f"All flowcharts already exist, skipped {skipped_count} methods",
                    metadata={
                        "total_methods": total_methods,
                        "generated_count": 0,
                        "skipped_count": skipped_count,
                        "failed_count": 0,
                    },
                )

            # 批量生成流程图
            context.stage_msg = f"正在批量生成 {len(files_to_process)} 个文件的流程图..."
            batch_result = await self._generate_flowcharts_batch(
                files_to_process, image_dir, repo_id, context
            )

            generated_count = batch_result.get("generated_count", 0)
            failed_count = batch_result.get("failed_count", 0)

            # 保存结果到上下文
            context.data["flowchart_generation"] = {
                "total_methods": total_methods,
                "generated_count": generated_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            }

            context.stage_msg = (
                f"流程图生成完成：{generated_count} 个成功, "
                f"{skipped_count} 个跳过, {failed_count} 个失败"
            )
            logger.info(
                f"Flowchart generation completed: {generated_count} generated, "
                f"{skipped_count} skipped, {failed_count} failed"
            )

            return StageResult(
                stage=self.stage,
                status=PipelineStatus.COMPLETED,
                message=f"Flowchart generation completed: {generated_count} generated, "
                        f"{skipped_count} skipped, {failed_count} failed",
                metadata={
                    "total_methods": total_methods,
                    "generated_count": generated_count,
                    "skipped_count": skipped_count,
                    "failed_count": failed_count,
                },
            )

        except Exception as e:
            logger.exception(f"Flowchart generation failed: {e}")
            return StageResult(
                stage=self.stage,
                status=PipelineStatus.FAILED,
                message=str(e),
            )

    async def _get_methods_grouped_by_file(
        self, repo_id: str, languages: List[str]
    ) -> Dict[str, List[Dict]]:
        """获取需要生成流程图的Method节点，按文件分组.

        Args:
            repo_id: 仓库ID
            languages: 语言列表

        Returns:
            按file_path分组的Method节点字典
        """
        methods = await self.graph_db.get_methods_by_languages(repo_id, languages)

        # 按file_path分组
        file_methods = defaultdict(list)
        for method in methods:
            file_path = method.get("file_path", "")
            if file_path:
                file_methods[file_path].append(method)

        return dict(file_methods)

    async def _get_file_contents(
        self, repo_id: str, file_paths: List[str]
    ) -> Dict[str, str]:
        """获取文件的完整代码内容.

        Args:
            repo_id: 仓库ID
            file_paths: 文件路径列表

        Returns:
            文件路径到代码内容的映射
        """
        return await self.graph_db.get_file_contents(repo_id, file_paths)

    async def _generate_flowcharts_batch(
        self,
        files_to_process: Dict[str, Dict],
        image_dir: Path,
        repo_id: str,
        context: PipelineContext,
    ) -> Dict[str, int]:
        """批量生成流程图.

        Args:
            files_to_process: 待处理的文件字典 {file_path: {content, methods}}
            image_dir: 图片保存目录
            repo_id: 仓库ID
            context: 流水线上下文

        Returns:
            统计结果 {generated_count, failed_count}
        """
        generated_count = 0
        failed_count = 0
        batch_size = self.settings.flowchart_batch_size

        try:
            # 构建请求项列表，并跟踪每个文件的方法数量
            file_items = []
            for file_path, file_data in files_to_process.items():
                file_name = Path(file_path).name
                file_items.append({
                    "file_name": file_name,
                    "source_path": file_path,
                    "code": file_data["content"],
                    "methods": file_data["methods"],
                })

            # 按方法数量分批处理
            batches = self._split_into_batches(file_items, batch_size)
            total_batches = len(batches)
            total_to_process = sum(len(f["methods"]) for f in files_to_process.values())

            logger.info(f"Split {len(file_items)} files into {total_batches} batches (max {batch_size} methods per batch)")

            # 逐批处理
            for batch_index, batch_items in enumerate(batches, 1):
                batch_methods_count = sum(len(item["methods"]) for item in batch_items)
                context.stage_msg = f"正在生成第 {batch_index}/{total_batches} 批流程图 ({batch_methods_count} 个方法)..."
                logger.info(f"Processing batch {batch_index}/{total_batches} with {len(batch_items)} files ({batch_methods_count} methods)")

                # 构建当前批次的请求数据（移除methods字段，不发送到API）
                api_items = [
                    {
                        "file_name": item["file_name"],
                        "source_path": item["source_path"],
                        "code": item["code"],
                    }
                    for item in batch_items
                ]

                # 构建当前批次的文件映射
                batch_files = {
                    item["source_path"]: {
                        "content": item["code"],
                        "methods": item["methods"],
                    }
                    for item in batch_items
                }

                # 调用批量生成接口
                batch_result = await self._process_single_batch(
                    api_items, batch_files, image_dir, repo_id, batch_index, total_batches
                )

                generated_count += batch_result.get("generated_count", 0)
                failed_count += batch_result.get("failed_count", 0)

                # 更新进度
                processed_count = generated_count + failed_count
                progress_ratio = processed_count / total_to_process if total_to_process > 0 else 0
                context.stage_msg = f"批量生成进度: {processed_count}/{total_to_process} (第 {batch_index}/{total_batches} 批完成)"
                self.advance_progress(context, progress_ratio, context.stage_msg)

                # 批次间短暂延迟，避免服务器过载
                if batch_index < total_batches:
                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.exception(f"Error in batch flowchart generation: {e}")
            # 已处理的部分不重复计数，只将未处理的部分标记为失败
            remaining_methods = total_to_process - generated_count - failed_count
            failed_count += remaining_methods

        return {"generated_count": generated_count, "failed_count": failed_count}

    def _split_into_batches(self, file_items: List[Dict], batch_size: int) -> List[List[Dict]]:
        """将文件列表按方法数量分批.

        Args:
            file_items: 文件项列表，每项包含methods字段
            batch_size: 每批最大方法数量

        Returns:
            分批后的列表
        """
        batches = []
        current_batch = []
        current_batch_method_count = 0

        for item in file_items:
            method_count = len(item.get("methods", []))

            # 如果当前批次已满，开始新批次
            if current_batch and current_batch_method_count + method_count > batch_size:
                batches.append(current_batch)
                current_batch = []
                current_batch_method_count = 0

            current_batch.append(item)
            current_batch_method_count += method_count

            # 如果当前批次正好达到上限，立即封存
            if current_batch_method_count >= batch_size:
                batches.append(current_batch)
                current_batch = []
                current_batch_method_count = 0

        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)

        return batches

    async def _process_single_batch(
        self,
        api_items: List[Dict[str, str]],
        batch_files: Dict[str, Dict],
        image_dir: Path,
        repo_id: str,
        batch_index: int,
        total_batches: int,
    ) -> Dict[str, int]:
        """处理单批流程图生成.

        Args:
            api_items: API请求用的文件列表
            batch_files: 当前批次的文件信息（含methods）
            image_dir: 图片保存目录
            repo_id: 仓库ID
            batch_index: 当前批次索引
            total_batches: 总批次数

        Returns:
            统计结果 {generated_count, failed_count}
        """
        generated_count = 0
        failed_count = 0

        try:
            # 调用批量生成接口
            service_result = await self._call_flowchart_service_batch(api_items)

            if not service_result or not service_result.get("success"):
                error_msg = service_result.get("message", "Unknown error") if service_result else "Failed to call flowchart service"
                logger.error(f"Batch {batch_index} failed: {error_msg}")
                failed_count = sum(len(f["methods"]) for f in batch_files.values())
                return {"generated_count": 0, "failed_count": failed_count}

            # 获取archive_url
            archive_url = service_result.get("archive_url", "")

            # 下载并解压压缩包
            if archive_url:
                actual_files = await self._download_and_extract_archive(
                    archive_url, image_dir, batch_files, repo_id
                )
                if actual_files > 0:
                    # 根据结果更新数据库
                    result_updates = self._parse_batch_results(
                        service_result.get("results", []),
                        batch_files,
                    )

                    # 构建基础URL
                    base_url = self.settings.public_base_url.rstrip('/')
                    static_url = self.settings.static_files_url.strip('/')

                    # 验证文件实际存在后再更新数据库
                    for method_id, image_id in result_updates.items():
                        # 优先检查svg，然后检查png
                        svg_path = image_dir / f"{image_id}.svg"
                        png_path = image_dir / f"{image_id}.png"

                        if svg_path.exists():
                            try:
                                # 构建完整URL: {base_url}/{static_url}/{repo_id}/image/{image_id}.svg
                                image_url = f"{base_url}/{static_url}/{repo_id}/image/{image_id}.svg"
                                await self.graph_db.update_method_image(method_id, image_url)
                                generated_count += 1
                            except Exception as e:
                                logger.error(f"Failed to update method {method_id} image: {e}")
                                failed_count += 1
                        elif png_path.exists():
                            try:
                                # 构建完整URL: {base_url}/{static_url}/{repo_id}/image/{image_id}.png
                                image_url = f"{base_url}/{static_url}/{repo_id}/image/{image_id}.png"
                                await self.graph_db.update_method_image(method_id, image_url)
                                generated_count += 1
                            except Exception as e:
                                logger.error(f"Failed to update method {method_id} image: {e}")
                                failed_count += 1
                        else:
                            logger.warning(f"Image file not found for method {method_id}: {svg_path} or {png_path}")
                            failed_count += 1

                    # 记录差异
                    if generated_count != actual_files:
                        logger.warning(f"Batch {batch_index} mismatch: {actual_files} files saved, but only {generated_count} database records updated")
                else:
                    # 下载失败或没有文件
                    logger.error(f"Batch {batch_index}: Download returned {actual_files} files, marking all as failed")
                    failed_count = sum(len(f["methods"]) for f in batch_files.values())
            else:
                logger.error(f"Batch {batch_index}: No archive_url in response")
                failed_count = sum(len(f["methods"]) for f in batch_files.values())

        except Exception as e:
            logger.exception(f"Error processing batch {batch_index}: {e}")
            failed_count = sum(len(f["methods"]) for f in batch_files.values())

        logger.info(f"Batch {batch_index}/{total_batches} completed: {generated_count} generated, {failed_count} failed")
        return {"generated_count": generated_count, "failed_count": failed_count}

    async def _call_flowchart_service_batch(
        self, items: List[Dict[str, str]]
    ) -> Optional[Dict[str, Any]]:
        """调用批量流程图生成服务.

        Args:
            items: 文件列表，每个包含 file_name, source_path, code

        Returns:
            服务响应JSON，失败返回None
        """
        service_url = self.settings.flowchart_service_url
        timeout = self.settings.flowchart_service_timeout * 10  # 批量接口可能需要更长时间

        url = f"{service_url}/api/flowchart/generate/batch"

        payload = {
            "output_format": "both",
            "show_legend": False,
            "llvm_path": None,
            "items": items,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        logger.error(f"Flowchart service returned {response.status}: {error_text}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error calling flowchart service: {e}")
            return None
        except asyncio.TimeoutError as e:
            logger.error(f"Timeout calling flowchart service after {timeout}s: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling flowchart service: {type(e).__name__}: {e}")
            return None

    async def _download_and_extract_archive(
        self,
        archive_url: str,
        image_dir: Path,
        files_to_process: Dict[str, Dict],
        repo_id: str,
    ) -> int:
        """下载并解压流程图压缩包.

        Args:
            archive_url: 压缩包下载URL
            image_dir: 图片保存目录
            files_to_process: 处理的文件信息（用于映射路径）
            repo_id: 仓库ID

        Returns:
            成功保存的文件数量
        """
        service_url = self.settings.flowchart_service_url
        timeout = self.settings.flowchart_service_timeout * 5  # 下载可能需要更长时间

        # 拼接完整URL
        if archive_url.startswith("http"):
            full_url = archive_url
        else:
            archive_path = archive_url.lstrip("/")
            full_url = f"{service_url}/{archive_path}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    full_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status == 200:
                        # 读取压缩包内容
                        zip_content = await response.read()
                        logger.info(f"Downloaded archive: {len(zip_content)} bytes")

                        # 解压到临时目录
                        temp_extract_dir = image_dir / "_temp"
                        temp_extract_dir.mkdir(parents=True, exist_ok=True)

                        with zipfile.ZipFile(BytesIO(zip_content)) as zf:
                            zf.extractall(temp_extract_dir)
                            logger.info(f"Extracted {len(zf.namelist())} files from archive")

                        # 移动并重命名图片文件
                        moved_count = self._organize_extracted_images(temp_extract_dir, image_dir)
                        logger.info(f"Organized {moved_count} images to {image_dir}")

                        # 清理临时目录
                        import shutil
                        shutil.rmtree(temp_extract_dir, ignore_errors=True)

                        return moved_count
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to download archive from {full_url}: {response.status} - {error_text}")
                        return 0

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error downloading archive from {full_url}: {e}")
            return 0
        except zipfile.BadZipFile as e:
            logger.error(f"Invalid zip file from {full_url}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error downloading archive from {full_url}: {e}")
            return 0

    def _organize_extracted_images(self, temp_dir: Path, image_dir: Path) -> int:
        """整理解压后的图片文件.

        将解压的子目录中的图片移动到主目录，并按function_id重命名.
        优先选择SVG格式，如果没有SVG则选择PNG格式.
        支持多层目录结构，如：Libraries/STM32F10x_StdPeriph_Driver/src/stm32f10x_tim_c/TIM_DeInit__L1.flowchart.svg

        Args:
            temp_dir: 临时解压目录
            image_dir: 最终图片目录

        Returns:
            移动的文件数量
        """
        moved_count = 0
        skipped_count = 0
        error_count = 0

        # 首先记录压缩包结构
        all_files = list(temp_dir.rglob("*"))
        svg_files = list(temp_dir.rglob("*.svg"))
        png_files = list(temp_dir.rglob("*.png"))
        logger.info(f"Archive contains {len(all_files)} items, {len(svg_files)} svg files, {len(png_files)} png files")

        # 优先使用SVG文件，收集每个方法对应的图片（避免重复）
        processed_methods = set()

        # 首先处理SVG文件
        for image_file in svg_files:
            if image_file.name == "manifest.json":
                continue

            result = self._process_image_file(image_file, temp_dir, image_dir, ".svg", processed_methods)
            if result == "moved":
                moved_count += 1
            elif result == "skipped":
                skipped_count += 1
            else:
                error_count += 1

        # 然后处理PNG文件（只处理没有SVG对应的方法）
        for image_file in png_files:
            if image_file.name == "manifest.json":
                continue

            # 检查是否已经有SVG版本
            method_key = self._get_method_key_from_image_path(image_file, temp_dir)
            if method_key in processed_methods:
                logger.debug(f"Skipping PNG for {method_key}, SVG already exists")
                skipped_count += 1
                continue

            result = self._process_image_file(image_file, temp_dir, image_dir, ".png", processed_methods)
            if result == "moved":
                moved_count += 1
            elif result == "skipped":
                skipped_count += 1
            else:
                error_count += 1

        logger.info(f"Image organization complete: {moved_count} copied, {skipped_count} skipped, {error_count} errors")
        return moved_count

    def _get_method_key_from_image_path(self, image_file: Path, temp_dir: Path) -> str:
        """从图片路径提取方法标识符（用于去重）.

        Args:
            image_file: 图片文件路径
            temp_dir: 临时解压目录

        Returns:
            方法标识符字符串
        """
        relative_path = image_file.relative_to(temp_dir)
        parts = relative_path.parts

        if len(parts) >= 2:
            path_dirs = parts[:-1]
            file_name = parts[-1]
            reconstructed = "/".join(path_dirs)
            path_slug = reconstructed.replace("/", "_").replace("\\", "_")
            base_name = file_name.replace(".flowchart.svg", "").replace(".flowchart.png", "")
            return f"{path_slug}_{base_name}"
        elif len(parts) == 1:
            file_name = parts[0]
            base_name = file_name.replace(".flowchart.svg", "").replace(".flowchart.png", "")
            return base_name
        return ""

    def _process_image_file(
        self,
        image_file: Path,
        temp_dir: Path,
        image_dir: Path,
        extension: str,
        processed_methods: set,
    ) -> str:
        """处理单个图片文件.

        Args:
            image_file: 图片文件路径
            temp_dir: 临时解压目录
            image_dir: 最终图片目录
            extension: 文件扩展名（.svg 或 .png）
            processed_methods: 已处理方法标识集合

        Returns:
            处理结果："moved", "skipped", "error"
        """
        try:
            # 从路径解析出function_id
            # 路径格式：temp_dir/{path_parts...}/{name}__L{line}.flowchart.{ext}
            relative_path = image_file.relative_to(temp_dir)
            parts = relative_path.parts

            if len(parts) >= 2:
                # 格式：{path_dir1}/{path_dir2}/.../{file_name}.flowchart.{ext}
                # 将所有目录部分组合成path_slug
                path_dirs = parts[:-1]  # 所有目录部分
                file_name = parts[-1]   # 文件名

                # 将目录路径转换为slug（用_替换路径分隔符）
                reconstructed = "/".join(path_dirs)
                # 如果在Windows上，path_dirs中的元素可能包含反斜杠（来自压缩包路径）
                # 统一替换为下划线
                path_slug = reconstructed.replace("/", "_").replace("\\", "_")

                # 移除.flowchart.{ext}后缀
                base_name = file_name.replace(f".flowchart{extension}", "")

                # 生成新的文件名：{path_slug}_{base_name}.{ext}
                new_name = f"{path_slug}_{base_name}{extension}"
            elif len(parts) == 1:
                # 格式：{file_name}.flowchart.{ext}（在根目录）
                file_name = parts[0]
                base_name = file_name.replace(f".flowchart{extension}", "")
                new_name = f"{base_name}{extension}"
            else:
                logger.warning(f"Unexpected path structure: {relative_path}")
                return "skipped"

            dest_path = image_dir / new_name

            # 复制文件
            import shutil
            shutil.copy2(image_file, dest_path)

            # 记录已处理方法
            method_key = self._get_method_key_from_image_path(image_file, temp_dir)
            if method_key:
                processed_methods.add(method_key)

            if len(processed_methods) <= 5 or len(processed_methods) % 50 == 0:
                logger.debug(f"Copied {image_file} to {dest_path}")

            return "moved"

        except Exception as e:
            logger.warning(f"Failed to process {image_file}: {e}")
            return "error"

    def _parse_batch_results(
        self,
        results: List[Dict],
        files_to_process: Dict[str, Dict],
    ) -> Dict[str, str]:
        """解析批量生成结果，映射method_id到image_id.

        Args:
            results: API返回的results数组
            files_to_process: 处理的文件信息

        Returns:
            method_id到image_id的映射
        """
        method_image_map = {}

        # 构建方法名到method_id的映射（按文件）
        file_method_map = {}
        for file_path, file_data in files_to_process.items():
            method_map = {}
            for method in file_data["methods"]:
                method_name = method.get("name", "")
                method_id = method.get("id", "")
                start_line = method.get("start_line", 0)
                if method_name and method_id:
                    method_map[(method_name, start_line)] = method_id
            file_method_map[file_path] = method_map

        # 解析结果
        for file_result in results:
            file_name = file_result.get("file_name", "")
            source_path = file_result.get("source_path", "")
            functions = file_result.get("functions", [])
            archive_paths = file_result.get("archive_paths", {})

            # 找到对应的文件路径
            file_path = source_path if source_path else file_name
            method_map = file_method_map.get(file_path, {})

            for func in functions:
                func_name = func.get("name", "")
                line_start = func.get("line_start", 0)

                # 查找匹配的method_id
                method_id = method_map.get((func_name, line_start))

                # 如果没找到，尝试只用函数名匹配
                if not method_id:
                    for (name, _), mid in method_map.items():
                        if name == func_name:
                            method_id = mid
                            break

                if method_id:
                    # 使用与_organize_extracted_images相同的命名规则生成image_id
                    # 从API返回的archive_paths获取路径信息
                    path_slug = self._generate_path_slug(file_path)
                    image_id = f"{path_slug}_{func_name}__L{line_start}"
                    method_image_map[method_id] = image_id
                    logger.debug(f"Mapped method {method_id} to image {image_id}")

        return method_image_map

    def _generate_path_slug(self, file_path: str) -> str:
        """生成路径slug（用于文件名）.

        将文件路径转换为合法的文件名部分，与压缩包中的路径结构保持一致。
        支持Windows和Linux路径格式。
        例如："Libraries/STM32F10x_StdPeriph_Driver/src/stm32f10x_tim.c" -> "Libraries_STM32F10x_StdPeriph_Driver_src_stm32f10x_tim_c"

        Args:
            file_path: 文件路径

        Returns:
            slug字符串
        """
        # 使用字符串操作而非Path对象，确保跨平台一致性
        # 因为Path在Windows和Linux上的行为不同
        normalized_path = file_path

        # 提取扩展名（最后一个.之后的部分）
        last_dot_idx = normalized_path.rfind(".")
        last_sep_idx_unix = normalized_path.rfind("/")
        last_sep_idx_win = normalized_path.rfind("\\")
        last_sep_idx = max(last_sep_idx_unix, last_sep_idx_win)

        if last_dot_idx > last_sep_idx and last_dot_idx != -1:
            # 有扩展名，将其转换为 _ext 格式
            suffix = normalized_path[last_dot_idx:]  # 例如: .c
            suffix_replacement = suffix.replace(".", "_")
            path_with_underscore_ext = normalized_path[:last_dot_idx] + suffix_replacement
        else:
            path_with_underscore_ext = normalized_path

        # 统一替换Windows和Linux路径分隔符为下划线
        slug = path_with_underscore_ext.replace("/", "_").replace("\\", "_")
        # 保留字母、数字、下划线
        slug = "".join(c for c in slug if c.isalnum() or c == "_")
        return slug
