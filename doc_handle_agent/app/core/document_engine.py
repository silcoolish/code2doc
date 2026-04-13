"""文档生成引擎."""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.config import get_settings
from app.core.generator import DocumentGenerator
from app.core.state import AgentState, GenerationStatus, create_initial_state
from app.infrastructure.docx_handler import DocxHandler
from app.infrastructure.llm_client import LLMClientFactory
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


def cleanup_temp_files(repo_id: str) -> None:
    """清理临时目录下对应仓库的文件.

    Args:
        repo_id: 仓库ID
    """
    settings = get_settings()
    temp_repo_dir = settings.temp_path / "flowcharts" / repo_id

    if temp_repo_dir.exists():
        try:
            shutil.rmtree(temp_repo_dir)
            logger.info(
                "temp_files_cleaned",
                repo_id=repo_id,
                temp_dir=str(temp_repo_dir),
            )
        except Exception as e:
            logger.warning(
                "temp_files_cleanup_failed",
                repo_id=repo_id,
                temp_dir=str(temp_repo_dir),
                error=str(e),
            )
    else:
        logger.debug(
            "temp_dir_not_exists",
            repo_id=repo_id,
            temp_dir=str(temp_repo_dir),
        )


class DocumentEngine:
    """文档生成引擎."""

    def __init__(self):
        """初始化文档生成引擎."""
        self.settings = get_settings()
        self.mcp_server_url = self.settings.mcp_server_url
        self.output_dir = self.settings.output_path

        # docx处理器
        self.docx_handler = DocxHandler()

        # 运行中的任务
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._task_states: Dict[str, AgentState] = {}

        logger.info(
            "document_engine_initialized",
            mcp_server_url=self.mcp_server_url,
            output_dir=str(self.output_dir),
        )

    async def start_generation(
        self,
        repo_id: str,
        template_path: str,
        output_filename: Optional[str] = None,
    ) -> str:
        """启动文档生成流程.

        Args:
            repo_id: 仓库ID
            template_path: 模板文件路径
            output_filename: 输出文件名，默认自动生成

        Returns:
            流程ID

        Raises:
            FileNotFoundError: 模板文件不存在
            ValueError: 参数无效
        """
        # 验证模板文件
        template_path_obj = Path(template_path)
        if not template_path_obj.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        # 生成流程ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        flow_id = f"doc_{repo_id}_{timestamp}"

        # 构建输出路径
        if not output_filename:
            output_filename = f"{flow_id}.docx"
        elif not output_filename.endswith(".docx"):
            output_filename = f"{output_filename}.docx"

        output_path = str(self.output_dir / output_filename)

        logger.info(
            "start_generation",
            flow_id=flow_id,
            repo_id=repo_id,
            template_path=template_path,
            output_path=output_path,
        )

        # 初始化状态
        initial_state = create_initial_state(
            repo_id=repo_id,
            template_path=template_path,
            output_path=output_path,
        )
        initial_state["status"] = GenerationStatus.PARSING.value
        initial_state["message"] = "等待开始生成..."

        # 保存初始状态
        self._task_states[flow_id] = initial_state

        # 启动异步任务
        task = asyncio.create_task(
            self._run_generation(flow_id, initial_state),
            name=f"generation_{flow_id}",
        )
        self._running_tasks[flow_id] = task

        return flow_id

    async def _run_generation(self, flow_id: str, initial_state: AgentState):
        """执行生成工作流.

        Args:
            flow_id: 流程ID
            initial_state: 初始状态
        """
        logger.info(
            "run_generation_start",
            flow_id=flow_id,
        )

        try:
            # 建立MCP连接
            async with MCPClient(self.mcp_server_url) as mcp_client:
                # 创建LLM客户端
                llm_client = LLMClientFactory.create()

                # 创建内容生成器
                from app.core.content_generator import ContentGenerator

                content_generator = ContentGenerator(
                    mcp_client=mcp_client,
                    llm_client=llm_client,
                )

                # 创建文档生成器
                document_generator = DocumentGenerator(
                    mcp_client=mcp_client,
                    content_generator=content_generator,
                    docx_handler=self.docx_handler,
                )

                # 执行工作流
                final_state = await document_generator.run(initial_state)

                # 保存最终状态
                self._task_states[flow_id] = final_state

                logger.info(
                    "run_generation_complete",
                    flow_id=flow_id,
                    status=final_state["status"],
                )

        except Exception as e:
            logger.error(
                "run_generation_failed",
                flow_id=flow_id,
                error=str(e),
            )

            # 更新失败状态
            failed_state = initial_state.copy()
            failed_state["status"] = GenerationStatus.FAILED.value
            failed_state["error"] = str(e)
            failed_state["message"] = f"生成失败: {str(e)}"
            self._task_states[flow_id] = failed_state

        finally:
            # 清理任务引用
            if flow_id in self._running_tasks:
                del self._running_tasks[flow_id]

            # 清理临时文件
            cleanup_temp_files(initial_state["repo_id"])

    def get_progress(self, flow_id: str) -> Dict:
        """获取生成进度.

        Args:
            flow_id: 流程ID

        Returns:
            进度信息字典
        """
        state = self._task_states.get(flow_id)

        if not state:
            return {
                "flow_id": flow_id,
                "status": "not_found",
                "error": "流程不存在",
            }

        total = state["total_paragraphs"]
        current = state["current_paragraph_index"]
        progress = (current / total * 100) if total > 0 else 0

        return {
            "flow_id": flow_id,
            "repo_id": state["repo_id"],
            "status": state["status"],
            "progress": round(progress, 2),
            "current_step": current,
            "total_steps": total,
            "message": state["message"],
            "output_path": state.get("output_path"),
            "error": state.get("error"),
        }

    def get_state(self, flow_id: str) -> Optional[AgentState]:
        """获取流程状态.

        Args:
            flow_id: 流程ID

        Returns:
            状态或None
        """
        return self._task_states.get(flow_id)

    def is_running(self, flow_id: str) -> bool:
        """检查流程是否正在运行.

        Args:
            flow_id: 流程ID

        Returns:
            是否运行中
        """
        return flow_id in self._running_tasks

    async def cancel_generation(self, flow_id: str) -> bool:
        """取消生成任务.

        Args:
            flow_id: 流程ID

        Returns:
            是否成功取消
        """
        task = self._running_tasks.get(flow_id)

        if not task:
            return False

        task.cancel()

        # 更新状态
        if flow_id in self._task_states:
            self._task_states[flow_id]["status"] = GenerationStatus.FAILED.value
            self._task_states[flow_id]["message"] = "生成已取消"

        logger.info(
            "generation_cancelled",
            flow_id=flow_id,
        )

        return True

    def list_active_generations(self) -> list[Dict]:
        """列出所有活动的生成任务.

        Returns:
            活动任务列表
        """
        return [
            {
                "flow_id": flow_id,
                "status": self._task_states.get(flow_id, {}).get("status"),
            }
            for flow_id in self._running_tasks.keys()
        ]


# 全局引擎实例
_engine: Optional[DocumentEngine] = None


def get_document_engine() -> DocumentEngine:
    """获取文档生成引擎单例.

    Returns:
        文档生成引擎实例
    """
    global _engine
    if _engine is None:
        _engine = DocumentEngine()
    return _engine
