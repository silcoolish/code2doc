"""HTTP请求工具类."""

import json
import time
from typing import Any, Dict, Optional

import httpx
import structlog

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_trace_id() -> Optional[str]:
    """从日志上下文中获取 trace_id."""
    try:
        ctx = structlog.contextvars.get_contextvars()
        return ctx.get("trace_id")
    except Exception:
        return None


class HttpUtils:
    """HTTP请求工具类.

    封装常用的HTTP请求操作，支持超时、错误处理和日志记录。
    """

    DEFAULT_TIMEOUT = 30.0
    MAX_RETRIES = 3

    @staticmethod
    async def get(
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送GET请求."""
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            default_headers.update(headers)

        trace_id = _get_trace_id()
        if trace_id:
            default_headers["X-Request-ID"] = trace_id

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                http1=True,
                http2=False,
                trust_env=False,
            ) as client:
                response = await client.get(
                    url,
                    params=params,
                    headers=default_headers,
                )
                response.raise_for_status()

                data = response.json()
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                logger.info(
                    "http_request",
                    method="GET",
                    url=url,
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    trace_id=trace_id,
                )
                return data

        except httpx.HTTPStatusError as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_failed",
                method="GET",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text[:500],
                elapsed_ms=elapsed_ms,
                trace_id=trace_id,
                exc_info=True,
            )
            raise
        except Exception as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_error",
                method="GET",
                url=url,
                elapsed_ms=elapsed_ms,
                error_type=type(e).__name__,
                error=str(e),
                trace_id=trace_id,
                exc_info=True,
            )
            raise

    @staticmethod
    async def post(
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送POST请求."""
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            default_headers.update(headers)

        if json_data and "Content-Type" not in default_headers:
            default_headers["Content-Type"] = "application/json"

        trace_id = _get_trace_id()
        if trace_id:
            default_headers["X-Request-ID"] = trace_id

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                http1=True,
                http2=False,
                trust_env=False,
            ) as client:
                if json_data is not None:
                    response = await client.post(
                        url,
                        json=json_data,
                        headers=default_headers,
                    )
                else:
                    response = await client.post(
                        url,
                        data=data,
                        headers=default_headers,
                    )

                response.raise_for_status()

                result = response.json()
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                logger.info(
                    "http_request",
                    method="POST",
                    url=url,
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    trace_id=trace_id,
                )
                return result

        except httpx.HTTPStatusError as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_failed",
                method="POST",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text[:500],
                elapsed_ms=elapsed_ms,
                trace_id=trace_id,
                exc_info=True,
            )
            raise
        except Exception as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_error",
                method="POST",
                url=url,
                elapsed_ms=elapsed_ms,
                error_type=type(e).__name__,
                error=str(e),
                trace_id=trace_id,
                exc_info=True,
            )
            raise

    @staticmethod
    async def post_multipart(
        url: str,
        files: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送multipart/form-data POST请求（用于文件上传）."""
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            headers.pop("Content-Type", None)
            default_headers.update(headers)

        trace_id = _get_trace_id()
        if trace_id:
            default_headers["X-Request-ID"] = trace_id

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                http1=True,
                http2=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    url,
                    files=files,
                    data=data or {},
                    headers=default_headers,
                )
                response.raise_for_status()

                result = response.json()
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                logger.info(
                    "http_request",
                    method="POST_MULTIPART",
                    url=url,
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                    trace_id=trace_id,
                )
                return result

        except httpx.HTTPStatusError as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_failed",
                method="POST_MULTIPART",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text[:500],
                elapsed_ms=elapsed_ms,
                trace_id=trace_id,
                exc_info=True,
            )
            raise
        except Exception as e:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "http_request_error",
                method="POST_MULTIPART",
                url=url,
                elapsed_ms=elapsed_ms,
                error_type=type(e).__name__,
                error=str(e),
                trace_id=trace_id,
                exc_info=True,
            )
            raise
