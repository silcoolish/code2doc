"""流程图生成阶段处理器.

该阶段为Method节点生成流程图：
1. 查询所有C/CPP语言的Method节点
2. 调用流程图生成服务API生成图片
3. 从image_url下载图片到 data/{repo_id}/image 目录
4. 更新Method节点的image属性

当前仅支持C/CPP语言，使用HTTP调用流程图生成服务。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiohttp

from app.config import get_settings
from app.core.pipeline import PipelineContext, PipelineStageHandler
from app.domain.models.pipeline import PipelineStage, PipelineStatus, StageResult
from app.infrastructure.db import GraphDatabaseClient, get_graph_db_client

logger = logging.getLogger(__name__)


class FlowchartGenerationStage(PipelineStageHandler):
    """流程图生成阶段处理器.

    为C/CPP语言的Method节点生成流程图。

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
        self.graph_db: Optional[GraphDatabaseClient] = None
        self.settings = get_settings()

    async def execute(self, context: PipelineContext) -> StageResult:
        """执行流程图生成.

        Args:
            context: 流水线上下文

        Returns:
            阶段执行结果
        """
        try:
            self.graph_db = get_graph_db_client()
            repo_id = getattr(context, 'repo_id', context.repo_name)

            # 确保图片目录存在
            image_dir = Path(self.settings.flowchart_image_dir) / repo_id / "image"
            image_dir.mkdir(parents=True, exist_ok=True)

            # 获取支持的语言
            supported_languages = self.settings.flowchart_supported_languages
            context.stage_msg = f"正在查询 {','.join(supported_languages)} 语言的Method节点..."

            # 获取指定语言的Method节点
            methods = await self._get_methods_for_flowchart(repo_id, supported_languages)
            if not methods:
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

            total_methods = len(methods)
            generated_count = 0
            skipped_count = 0
            failed_count = 0

            context.stage_msg = f"找到 {total_methods} 个Method节点，开始生成流程图..."
            logger.info(f"Found {total_methods} methods for flowchart generation")

            # 逐个处理方法节点
            for idx, method in enumerate(methods):
                method_id = method.get("id", "")
                method_name = method.get("name", "")

                # 每5个方法更新一次进度消息
                if idx % 5 == 0:
                    context.stage_msg = f"正在生成流程图: {idx}/{total_methods} ({method_name})"
                    # 更新进度
                    progress_ratio = idx / total_methods if total_methods > 0 else 0
                    self.advance_progress(context, progress_ratio, context.stage_msg)

                # 检查是否已有image（断点续传场景）
                existing_image = method.get("image", "")
                if existing_image:
                    # 检查图片文件是否存在
                    existing_image_path = image_dir / f"{existing_image}.png"
                    if existing_image_path.exists():
                        skipped_count += 1
                        continue

                # 生成流程图
                result = await self._generate_flowchart_for_method(
                    method, image_dir, repo_id
                )

                if result["success"]:
                    generated_count += 1
                    logger.debug(f"Generated flowchart for method {method_name}: {result['image_id']}")
                else:
                    failed_count += 1
                    logger.warning(f"Failed to generate flowchart for method {method_name}: {result['error']}")

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

    async def _get_methods_for_flowchart(
        self, repo_id: str, languages: List[str]
    ) -> List[Dict]:
        """获取需要生成流程图的Method节点.

        Args:
            repo_id: 仓库ID
            languages: 语言列表

        Returns:
            Method节点列表
        """
        return await self.graph_db.get_methods_by_languages(repo_id, languages)

    async def _generate_flowchart_for_method(
        self,
        method: Dict,
        image_dir: Path,
        repo_id: str,
    ) -> Dict[str, Any]:
        """为单个Method生成流程图.

        Args:
            method: Method节点数据
            image_dir: 图片保存目录
            repo_id: 仓库ID

        Returns:
            生成结果，包含 success, image_id, error 字段
        """
        method_id = method.get("id", "")
        method_name = method.get("name", "")
        code = method.get("code", "")

        if not code:
            return {"success": False, "error": "No code available", "image_id": ""}

        try:
            # 调用流程图生成服务
            service_result = await self._call_flowchart_service(code, method_name)
            if not service_result or not service_result.get("success"):
                error_msg = service_result.get("message", "Unknown error") if service_result else "Failed to call flowchart service"
                return {"success": False, "error": error_msg, "image_id": ""}

            # 获取流程图列表
            flowcharts = service_result.get("flowcharts", [])
            if not flowcharts:
                return {"success": False, "error": "No flowcharts returned", "image_id": ""}

            # 获取第一个流程图的image_url
            image_url = flowcharts[0].get("image_url", "")
            if not image_url:
                return {"success": False, "error": "No image_url in response", "image_id": ""}

            # 下载图片
            image_data = await self._download_image(image_url)
            if not image_data:
                return {"success": False, "error": "Failed to download image", "image_id": ""}

            # 生成唯一ID并保存图片
            image_id = str(uuid4())
            image_path = image_dir / f"{image_id}.png"

            # 保存图片文件
            with open(image_path, "wb") as f:
                f.write(image_data)

            # 更新数据库中的image属性
            await self.graph_db.update_method_image(method_id, image_id)

            return {"success": True, "image_id": image_id, "error": ""}

        except Exception as e:
            logger.error(f"Error generating flowchart for {method_name}: {e}")
            return {"success": False, "error": str(e), "image_id": ""}

    async def _call_flowchart_service(self, code: str, function_name: str) -> Optional[Dict[str, Any]]:
        """调用流程图生成服务.

        Args:
            code: 代码内容
            function_name: 函数名称

        Returns:
            服务响应JSON，失败返回None
        """
        service_url = self.settings.flowchart_service_url
        timeout = self.settings.flowchart_service_timeout

        url = f"{service_url}/api/flowchart/generate"

        payload = {
            "code": code,
            "function_name": function_name,
            "output_format": "png",
            "show_legend": False,
            "llvm_path": "",
            "source_path": "",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status == 200:
                        # 返回JSON响应
                        return await response.json()
                    else:
                        error_text = await response.text()
                        logger.error(f"Flowchart service returned {response.status}: {error_text}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error calling flowchart service: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling flowchart service: {e}")
            return None

    async def _download_image(self, image_url: str) -> Optional[bytes]:
        """从image_url下载图片.

        Args:
            image_url: 图片URL（相对路径，如 /api/flowchart/diagram/51526da3/main_flowchart.png）

        Returns:
            图片二进制数据，失败返回None
        """
        service_url = self.settings.flowchart_service_url
        timeout = self.settings.flowchart_service_timeout

        # 拼接完整URL
        if image_url.startswith("http"):
            full_url = image_url
        else:
            # 移除开头的斜杠，避免双斜杠
            image_path = image_url.lstrip("/")
            full_url = f"{service_url}/{image_path}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    full_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to download image from {full_url}: {response.status} - {error_text}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error downloading image from {full_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading image from {full_url}: {e}")
            return None
