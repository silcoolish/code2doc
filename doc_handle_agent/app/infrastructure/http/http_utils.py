"""HTTP请求工具类."""

import asyncio
import random
import time
from typing import Any, Callable, Dict, Optional

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
    内置指数退避重试机制，对网络错误和5xx状态码自动重试。
    """

    DEFAULT_TIMEOUT = 30.0
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 1.0
    MAX_RETRY_DELAY = 10.0

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        """判断错误是否可重试.

        可重试的错误类型：
        - 5xx 服务器错误
        - 网络错误（连接断开、DNS失败等）
        - 超时错误
        - 连接错误

        Args:
            error: 异常实例

        Returns:
            是否可重试
        """
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code >= 500
        return isinstance(
            error,
            (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError),
        )

    @staticmethod
    def _calculate_retry_delay(attempt: int) -> float:
        """计算重试延迟（指数退避 + 随机抖动）.

        Args:
            attempt: 当前重试次数（从0开始）

        Returns:
            延迟秒数
        """
        delay = HttpUtils.BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
        return min(delay, HttpUtils.MAX_RETRY_DELAY)

    @staticmethod
    async def _execute_request(
        method: str,
        url: str,
        request_fn: Callable[[httpx.AsyncClient], Any],
        max_retries: int = MAX_RETRIES,
    ) -> Dict[str, Any]:
        """执行HTTP请求并带重试.

        Args:
            method: HTTP方法名（用于日志）
            url: 请求URL
            request_fn: 接收httpx.AsyncClient并返回Response的协程函数
            max_retries: 最大重试次数

        Returns:
            解析后的JSON响应

        Raises:
            httpx.HTTPError: 请求最终失败时抛出
        """
        trace_id = _get_trace_id()
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                async with httpx.AsyncClient(
                    timeout=HttpUtils.DEFAULT_TIMEOUT,
                    follow_redirects=True,
                    http1=True,
                    http2=False,
                    trust_env=False,
                ) as client:
                    response = await request_fn(client)
                    response.raise_for_status()

                    data = response.json()
                    elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                    logger.info(
                        "http_request",
                        method=method,
                        url=url,
                        status_code=response.status_code,
                        elapsed_ms=elapsed_ms,
                        trace_id=trace_id,
                        attempt=attempt,
                    )
                    return data

            except Exception as e:
                elapsed_ms = round((time.monotonic() - start) * 1000, 2)
                last_error = e

                if HttpUtils._is_retryable_error(e) and attempt < max_retries:
                    delay = HttpUtils._calculate_retry_delay(attempt)
                    logger.warning(
                        "http_request_retry",
                        method=method,
                        url=url,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=round(delay, 2),
                        error_type=type(e).__name__,
                        error=str(e)[:200],
                        trace_id=trace_id,
                    )
                    await asyncio.sleep(delay)
                    continue

                if isinstance(e, httpx.HTTPStatusError):
                    logger.error(
                        "http_request_failed",
                        method=method,
                        url=url,
                        status_code=e.response.status_code,
                        response=e.response.text[:500],
                        elapsed_ms=elapsed_ms,
                        trace_id=trace_id,
                        attempt=attempt,
                        exc_info=True,
                    )
                else:
                    logger.error(
                        "http_request_error",
                        method=method,
                        url=url,
                        elapsed_ms=elapsed_ms,
                        error_type=type(e).__name__,
                        error=str(e),
                        trace_id=trace_id,
                        attempt=attempt,
                        exc_info=True,
                    )
                raise

        raise last_error if last_error else RuntimeError("Request failed")

    @staticmethod
    async def get(
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送GET请求（带指数退避重试）."""
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            default_headers.update(headers)

        trace_id = _get_trace_id()
        if trace_id:
            default_headers["X-Request-ID"] = trace_id

        async def _request(client: httpx.AsyncClient) -> httpx.Response:
            return await client.get(
                url,
                params=params,
                headers=default_headers,
                timeout=timeout,
            )

        return await HttpUtils._execute_request("GET", url, _request)

    @staticmethod
    async def post(
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送POST请求（带指数退避重试）."""
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

        async def _request(client: httpx.AsyncClient) -> httpx.Response:
            if json_data is not None:
                return await client.post(
                    url,
                    json=json_data,
                    headers=default_headers,
                    timeout=timeout,
                )
            return await client.post(
                url,
                data=data,
                headers=default_headers,
                timeout=timeout,
            )

        return await HttpUtils._execute_request("POST", url, _request)

    @staticmethod
    async def post_multipart(
        url: str,
        files: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """发送multipart/form-data POST请求（带指数退避重试）."""
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

        async def _request(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                url,
                files=files,
                data=data or {},
                headers=default_headers,
                timeout=timeout,
            )

        return await HttpUtils._execute_request("POST_MULTIPART", url, _request)
