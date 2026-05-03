"""日志配置."""

import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import structlog
from pythonjsonlogger import jsonlogger

from app.config import get_settings


def setup_logging() -> None:
    """配置结构化日志."""
    settings = get_settings()

    # 创建日志目录
    log_dir = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.log_level.upper())

    # 清除已有的 handlers（避免重复配置）
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 配置文件日志处理器（记录所有配置的级别）
    file_handler = logging.FileHandler(
        log_dir / "doc_handle_agent.log",
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)

    # JSON格式
    json_formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    file_handler.setFormatter(json_formatter)

    # 控制台处理器：debug 模式使用 log_level，否则只输出 WARNING+
    console_level = log_level if settings.debug else logging.WARNING
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    # 配置structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置根日志器
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name: str):
    """获取结构化日志记录器."""
    return structlog.get_logger(name)


@contextmanager
def bind_log_context(**kwargs: Any) -> Generator[None, None, None]:
    """绑定日志上下文变量.

    在上下文范围内，所有日志自动携带绑定的字段。

    Usage:
        with bind_log_context(trace_id=flow_id, repo_id=repo_id):
            logger.info("event")  # 自动包含 trace_id 和 repo_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*kwargs.keys())


def clear_log_context() -> None:
    """清除所有日志上下文变量."""
    structlog.contextvars.clear_contextvars()
