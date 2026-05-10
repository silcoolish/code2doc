"""配置同步API路由."""

from typing import Any, Dict

from fastapi import APIRouter

from app.config import get_settings, update_env_file
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/settings/ai")
async def sync_ai_settings(payload: Dict[str, Any]) -> Dict[str, str]:
    """接收 workspace 推送的 AI 配置并热更新.

    Args:
        payload: 配置键值对字典

    Returns:
        更新结果
    """
    logger.info("ai_settings_sync_received", keys=list(payload.keys()))

    # 只保留字符串类型的值，避免写入复杂对象
    env_updates = {k: str(v) for k, v in payload.items() if v is not None}

    update_env_file(env_updates)

    # 验证更新已生效
    settings = get_settings()
    logger.info(
        "ai_settings_sync_completed",
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
    )

    return {"status": "success", "message": "AI settings updated"}
