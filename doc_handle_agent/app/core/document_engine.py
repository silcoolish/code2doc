"""文档生成引擎."""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.config import get_settings
from app.core.generator import DocumentGenerator
from app.core.state import AgentState, GenerationStatus, create_initial_state
from app.infrastructure.llm_client import LLMClientFactory
from app.infrastructure.workspace import WorkspaceServiceAdapter
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger, bind_log_context
from app.utils.timing import log_timing

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
                exc_info=True,
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
        self.workspace_adapter = WorkspaceServiceAdapter()

        # 运行中的任务
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._task_states: Dict[str, AgentState] = {}

        settings = get_settings()
        logger.info(
            "document_engine_initialized",
            mcp_server_url=settings.mcp_server_url,
        )

    async def start_generation(
        self,
        repo_id: str,
        template_id: str,
        output_filename: Optional[str] = None,
    ) -> str:
        """启动文档生成流程.

        Args:
            repo_id: 仓库ID
            template_id: 文档模板ID
            output_filename: 输出文件名（向后兼容，不再使用）

        Returns:
            流程ID

        Raises:
            ValueError: 参数无效
        """
        # 生成流程ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        flow_id = f"doc_{repo_id}_{timestamp}"

        logger.info(
            "start_generation",
            flow_id=flow_id,
            repo_id=repo_id,
            template_id=template_id,
        )

        # 初始化状态
        initial_state = create_initial_state(
            repo_id=repo_id,
            template_id=template_id,
        )
        initial_state["status"] = GenerationStatus.PARSING.value
        initial_state["message"] = "等待开始生成..."

        # 保存初始状态
        self._task_states[flow_id] = initial_state

        # 启动异步任务，在日志上下文中绑定 trace_id 和 repo_id
        task = asyncio.create_task(
            self._run_generation_with_context(flow_id, initial_state),
            name=f"generation_{flow_id}",
        )
        self._running_tasks[flow_id] = task

        return flow_id

    async def _run_generation_with_context(self, flow_id: str, initial_state: AgentState):
        """在日志上下文中运行生成任务."""
        with bind_log_context(trace_id=flow_id, repo_id=initial_state["repo_id"]):
            await self._run_generation(flow_id, initial_state)

    async def _run_generation(self, flow_id: str, initial_state: AgentState):
        """执行生成工作流.

        Args:
            flow_id: 流程ID
            initial_state: 初始状态
        """
        logger.info(
            "run_generation_start",
            flow_id=flow_id,
            repo_id=initial_state["repo_id"],
            template_id=initial_state["template_id"],
        )

        try:
            # 建立MCP连接
            async with MCPClient(get_settings().mcp_server_url) as mcp_client:
                # 创建LLM客户端
                llm_client = LLMClientFactory.create()

                # 创建内容生成器
                from app.domain.content_generator import ContentGenerator

                content_generator = ContentGenerator(
                    mcp_client=mcp_client,
                    llm_client=llm_client,
                )
                await content_generator.initialize()

                # 创建workspace适配器
                workspace_adapter = WorkspaceServiceAdapter()

                # 创建文档生成器
                def on_state_change(state: AgentState):
                    """每次节点执行后将状态同步回 _task_states，确保进度实时可见."""
                    self._task_states[flow_id] = state

                document_generator = DocumentGenerator(
                    mcp_client=mcp_client,
                    content_generator=content_generator,
                    workspace_adapter=workspace_adapter,
                    on_state_change=on_state_change,
                )

                # 执行工作流
                final_state = await document_generator.run(initial_state)

                # 工作流正常结束后统一标记为完成（仅当未失败时）
                if final_state.get("status") != GenerationStatus.FAILED.value:
                    final_state["status"] = GenerationStatus.COMPLETED.value
                    final_state["message"] = "文档生成完成"

                # 保存最终状态
                self._task_states[flow_id] = final_state

                logger.info(
                    "run_generation_complete",
                    flow_id=flow_id,
                    status=final_state["status"],
                    document_id=final_state.get("document_id"),
                )

        except Exception as e:
            logger.error(
                "run_generation_failed",
                flow_id=flow_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
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

    # 节点顺序定义（与 generator.py 工作流保持一致）
    _NODE_ORDER = [
        "list_template_block",
        "outline_confirmation",
        "select_strategy",
        "generate_blocks",
        "create_document",
        "process_image_blocks",
        "store_block_list",
    ]

    # 节点中文名称映射
    _NODE_NAME_MAP = {
        "list_template_block": "获取模板内容块列表",
        "outline_confirmation": "确认文档大纲",
        "select_strategy": "选择内容生成策略",
        "generate_blocks": "生成文档内容",
        "create_document": "创建文档",
        "process_image_blocks": "处理图片资源",
        "store_block_list": "保存最终文档",
    }

    # 节点进度百分比映射
    _NODE_PROGRESS_MAP = {
        "list_template_block": 10,
        "outline_confirmation": 25,
        "select_strategy": 40,
        "generate_blocks": 55,
        "create_document": 70,
        "process_image_blocks": 85,
        "store_block_list": 95,
    }

    _NODE_WEIGHTS = {
        "list_template_block": 0.05,
        "outline_confirmation": 0.05,
        "select_strategy": 0.05,
        "generate_blocks": 0.55,
        "create_document": 0.10,
        "process_image_blocks": 0.15,
        "store_block_list": 0.05,
    }

    def get_progress(self, flow_id: str) -> Dict:
        """获取生成进度.

        根据当前执行的节点计算 current_step、total_steps、progress，
        并生成中文 message 明确告知当前所处节点。

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

        status = state["status"]
        current_node = state.get("current_node")
        error = state.get("error")

        # 终态直接返回
        if status == GenerationStatus.COMPLETED.value:
            return {
                "flow_id": flow_id,
                "repo_id": state["repo_id"],
                "status": status,
                "progress": 100,
                "current_step": len(self._NODE_ORDER),
                "total_steps": len(self._NODE_ORDER),
                "message": "文档生成完成",
                "document_id": state.get("document_id"),
                "error": None,
            }

        if status == GenerationStatus.FAILED.value:
            return {
                "flow_id": flow_id,
                "repo_id": state["repo_id"],
                "status": status,
                "progress": 0,
                "current_step": 0,
                "total_steps": len(self._NODE_ORDER),
                "message": f"文档生成失败: {error}" if error else "文档生成失败",
                "document_id": state.get("document_id"),
                "error": error,
            }

        # 根据当前节点计算进度
        total_steps = len(self._NODE_ORDER)

        if "progress" in state and state["progress"] is not None:
            current_step = self._NODE_ORDER.index(current_node) + 1 if current_node else 0
            progress = state["progress"]
            message = state.get("message", "")
        else:
            if current_node and current_node in self._NODE_ORDER:
                current_step = self._NODE_ORDER.index(current_node) + 1
                progress = self._NODE_PROGRESS_MAP.get(current_node, 0)
                node_name_cn = self._NODE_NAME_MAP.get(current_node, current_node)
                message = f"正在{node_name_cn}..."
            else:
                current_step = 0
                progress = 0
                message = state.get("message", "等待开始生成...")

        return {
            "flow_id": flow_id,
            "repo_id": state["repo_id"],
            "status": status,
            "progress": progress,
            "current_step": current_step,
            "total_steps": total_steps,
            "message": message,
            "document_id": state.get("document_id"),
            "error": error,
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
