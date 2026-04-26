"""Agent 调用专用日志记录器.

用于记录 content_generator_agent 的详细调用过程，包括：
- 每次对 agent 请求的完整提示词
- agent 每次调用 tool 的参数以及响应
- 每次调用 LLM 的完整提示词以及响应

每个会话生成独立的 .jsonl 日志文件，避免单文件膨胀，且不影响系统日志/控制台输出。
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from app.config import get_settings

# 最多保留的 agent 会话日志文件数量
MAX_AGENT_LOG_FILES = 20


class AgentLogger:
    """Agent 调用专用日志记录器."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        log_dir: Optional[Path] = None,
    ):
        """初始化 Agent 日志记录器.

        Args:
            session_id: 会话唯一标识，用于生成独立日志文件名；为空则自动生成。
            log_dir: 日志目录，默认从配置读取并在其下创建 agent_sessions 子目录。
        """
        settings = get_settings()
        self.log_dir = log_dir or settings.log_path / "agent_sessions"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 生成或复用 session_id
        self.session_id = session_id or str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"agent_{self.session_id}_{timestamp}.jsonl"

        # 配置专用 logger，阻止向 root logger 传播（避免进入系统日志和控制台）
        self.logger = logging.getLogger(f"agent_calls.{self.session_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        # 文件处理器（每次新建实例都添加，因为 logger 名称含 session_id 不会重复）
        file_handler = logging.FileHandler(
            self.log_file,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)

        # JSON Lines 格式，每行一条 JSON
        formatter = logging.Formatter("%(message)s")
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)

        # 清理旧日志文件
        self._cleanup_old_logs()

    def _cleanup_old_logs(self) -> None:
        """按修改时间保留最新的 MAX_AGENT_LOG_FILES 个日志文件，删除其余旧文件."""
        try:
            log_files = sorted(
                self.log_dir.glob("agent_*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old_file in log_files[MAX_AGENT_LOG_FILES:]:
                old_file.unlink(missing_ok=True)
        except Exception:
            pass

    def _current_trace_id(self) -> Optional[str]:
        """获取当前日志上下文中的 trace_id."""
        try:
            ctx = structlog.contextvars.get_contextvars()
            return ctx.get("trace_id")
        except Exception:
            return None

    def _log_entry(self, entry: Dict[str, Any]) -> None:
        """写入日志条目.

        Args:
            entry: 日志条目字典
        """
        # 自动注入 trace_id 和时间戳
        entry["timestamp"] = datetime.now().isoformat()
        trace_id = self._current_trace_id()
        if trace_id:
            entry["trace_id"] = trace_id

        # 写入 JSON Lines 格式的日志（每行一条 JSON）
        self.logger.debug(json.dumps(entry, ensure_ascii=False, default=str))

    def log_agent_request(
        self,
        session_id: str,
        system_prompt: str,
        task_message: str,
        repo_id: str,
        max_iterations: int,
    ) -> None:
        """记录 agent 请求开始."""
        self._log_entry({
            "call_type": "agent_request",
            "session_id": session_id,
            "system_prompt": system_prompt,
            "task_message": task_message,
            "repo_id": repo_id,
            "max_iterations": max_iterations,
        })

    def log_llm_call(
        self,
        session_id: str,
        iteration: int,
        messages: List[Dict[str, Any]],
        model_name: str,
    ) -> None:
        """记录 LLM 调用请求."""
        self._log_entry({
            "call_type": "llm_call_request",
            "session_id": session_id,
            "iteration": iteration,
            "model_name": model_name,
            "messages": messages,
        })

    def log_llm_response(
        self,
        session_id: str,
        iteration: int,
        response_content: str,
        tool_calls: Optional[List[Dict[str, Any]]],
        model_name: str,
    ) -> None:
        """记录 LLM 响应."""
        entry: Dict[str, Any] = {
            "call_type": "llm_call_response",
            "session_id": session_id,
            "iteration": iteration,
            "model_name": model_name,
            "response_content": response_content,
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls
        self._log_entry(entry)

    def log_tool_call(
        self,
        session_id: str,
        iteration: int,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> None:
        """记录工具调用请求."""
        self._log_entry({
            "call_type": "tool_call_request",
            "session_id": session_id,
            "iteration": iteration,
            "tool_name": tool_name,
            "arguments": arguments,
        })

    def log_tool_response(
        self,
        session_id: str,
        iteration: int,
        tool_name: str,
        response: str,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """记录工具调用响应."""
        entry: Dict[str, Any] = {
            "call_type": "tool_call_response",
            "session_id": session_id,
            "iteration": iteration,
            "tool_name": tool_name,
            "response": response,
            "success": success,
        }
        if error:
            entry["error"] = error
        self._log_entry(entry)

    def log_agent_completion(
        self,
        session_id: str,
        total_iterations: int,
        final_content: str,
        reason: str,
    ) -> None:
        """记录 agent 请求完成."""
        self._log_entry({
            "call_type": "agent_completion",
            "session_id": session_id,
            "total_iterations": total_iterations,
            "final_content": final_content,
            "reason": reason,
        })


def get_agent_logger(session_id: Optional[str] = None) -> AgentLogger:
    """获取 AgentLogger 实例.

    每次调用均创建新实例，对应独立的会话日志文件。

    Args:
        session_id: 可选的会话唯一标识，为空则自动生成 UUID。

    Returns:
        AgentLogger 新实例。
    """
    return AgentLogger(session_id=session_id)
