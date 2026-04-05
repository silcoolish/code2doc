"""日志配置."""

import logging
import sys
from pathlib import Path

import structlog
from pythonjsonlogger import jsonlogger

from app.config import get_settings


def setup_logging() -> None:
    """配置结构化日志."""
    settings = get_settings()

    # 创建日志目录
    log_dir = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    # 配置标准库日志
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    # 配置文件日志处理器
    file_handler = logging.FileHandler(
        log_dir / "doc_handle_agent.log",
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, settings.log_level.upper()))

    # JSON格式
    json_formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    file_handler.setFormatter(json_formatter)

    # 配置structlog
    structlog.configure(
        processors=[
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

    # 添加文件处理器到根日志器
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)


def get_logger(name: str):
    """获取结构化日志记录器."""
    return structlog.get_logger(name)
