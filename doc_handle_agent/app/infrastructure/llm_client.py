"""LLM客户端工厂."""

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class LLMClientFactory:
    """LLM客户端工厂类."""

    @staticmethod
    def create() -> ChatOpenAI:
        """创建LLM客户端实例.

        Returns:
            ChatOpenAI实例
        """
        settings = get_settings()
        base_url = settings.dashscope_base_url.replace(
            "/api/v1", "/compatible-mode/v1"
        )

        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=base_url,
            temperature=0.7,
            max_retries=3,
            timeout=settings.llm_request_timeout,
        )

        logger.info(
            "llm_client_created",
            model=settings.llm_model,
            base_url=base_url,
        )

        return llm
