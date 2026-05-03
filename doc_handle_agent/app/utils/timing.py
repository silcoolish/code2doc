"""性能计时工具."""

import time
from contextlib import contextmanager
from typing import Any, Generator, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@contextmanager
def log_timing(
    event: str,
    logger_instance: Optional[Any] = None,
    **extra: Any,
) -> Generator[None, None, None]:
    """记录代码块执行耗时.

    Usage:
        with log_timing("generate_content", strategy="full_context"):
            results = await strategy.execute(blocks, repo_id)

    输出日志:
        {"event": "generate_content_start", "strategy": "full_context", ...}
        {"event": "generate_content_complete", "strategy": "full_context", "elapsed_ms": 1234, ...}
    """
    log = logger_instance or logger
    start = time.monotonic()
    log.info(f"{event}_start", **extra)
    try:
        yield
    except Exception as e:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        log.error(
            f"{event}_failed",
            elapsed_ms=elapsed_ms,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
            **extra,
        )
        raise
    finally:
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        log.info(f"{event}_complete", elapsed_ms=elapsed_ms, **extra)
