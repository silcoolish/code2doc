"""HTTP请求工具类."""

import json
from typing import Any, Dict, Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
        """发送GET请求.

        Args:
            url: 请求URL
            params: URL参数
            headers: 请求头
            timeout: 超时时间（秒）

        Returns:
            响应数据（已解析为JSON）

        Raises:
            httpx.HTTPError: HTTP请求失败
            json.JSONDecodeError: 响应解析失败
        """
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            default_headers.update(headers)

        logger.info(
            "http_get_request",
            url=url,
            params=params,
            headers=default_headers,
        )

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
                logger.debug(
                    "http_get_success",
                    url=url,
                    status_code=response.status_code,
                )
                return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "http_get_failed",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error(
                "http_get_error",
                url=url,
                error=str(e),
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
        """发送POST请求.

        Args:
            url: 请求URL
            json_data: JSON请求体
            data: 表单数据
            headers: 请求头
            timeout: 超时时间（秒）

        Returns:
            响应数据（已解析为JSON）

        Raises:
            httpx.HTTPError: HTTP请求失败
            json.JSONDecodeError: 响应解析失败
        """
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            default_headers.update(headers)

        if json_data and "Content-Type" not in default_headers:
            default_headers["Content-Type"] = "application/json"

        logger.debug(
            "http_post_request",
            url=url,
            has_json=json_data is not None,
            has_form=data is not None,
        )

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

                data = response.json()
                logger.debug(
                    "http_post_success",
                    url=url,
                    status_code=response.status_code,
                )
                return data

        except httpx.HTTPStatusError as e:
            logger.error(
                "http_post_failed",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error(
                "http_post_error",
                url=url,
                error=str(e),
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
        """发送multipart/form-data POST请求（用于文件上传）.

        Args:
            url: 请求URL
            files: 文件字典，格式为 {field_name: (filename, file_content, content_type)}
            data: 额外的表单数据
            headers: 请求头（注意：不要设置Content-Type，httpx会自动设置）
            timeout: 超时时间（秒）

        Returns:
            响应数据（已解析为JSON）

        Raises:
            httpx.HTTPError: HTTP请求失败
            json.JSONDecodeError: 响应解析失败
        """
        default_headers = {
            "Accept": "application/json",
            "User-Agent": "doc-handle-agent/1.0",
        }
        if headers:
            # 移除Content-Type，让httpx自动设置multipart边界
            headers.pop("Content-Type", None)
            default_headers.update(headers)

        logger.debug(
            "http_multipart_request",
            url=url,
            file_fields=list(files.keys()),
        )

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
                logger.debug(
                    "http_multipart_success",
                    url=url,
                    status_code=response.status_code,
                )
                return result

        except httpx.HTTPStatusError as e:
            logger.error(
                "http_multipart_failed",
                url=url,
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise
        except Exception as e:
            logger.error(
                "http_multipart_error",
                url=url,
                error=str(e),
            )
            raise
