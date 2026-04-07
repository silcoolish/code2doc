"""重置初始化 API 路由."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.pipeline import get_orchestrator
from app.core.pipeline_logger import get_pipeline_log_manager
from app.infrastructure.csv_storage import get_repo_status_storage
from app.infrastructure.db import get_graph_db_client, get_vector_db_client

logger = logging.getLogger(__name__)

router = APIRouter()


class ResetResponse(BaseModel):
    """重置响应."""

    repo_id: str
    success: bool
    message: str
    details: Dict[str, Any]


@router.post("/{repo_id}/reset", response_model=ResetResponse)
async def reset_initialization(repo_id: str) -> ResetResponse:
    """重置仓库初始化状态.

    执行以下操作：
    1. 删除图数据库中对应仓库所有节点数据
    2. 删除向量数据库中对应仓库所有数据
    3. 在 repo_initialization.csv 文件中删除对应仓库数据
    4. 清除仓库 log 目录下的上下文 json 文件，若有执行日志，移入 history 文件夹

    Args:
        repo_id: 仓库ID

    Returns:
        重置结果
    """
    details = {
        "graph_db_deleted": False,
        "vector_db_deleted": False,
        "csv_record_deleted": False,
        "logs_reset": False,
    }

    try:
        # 1. 删除图数据库中对应仓库所有节点数据
        try:
            graph_db = get_graph_db_client()
            deleted_count = await graph_db.delete_repo_data(repo_id)
            details["graph_db_deleted"] = True
            details["graph_db_deleted_count"] = deleted_count
            logger.info(f"Deleted {deleted_count} nodes from graph DB for repo: {repo_id}")
        except Exception as e:
            logger.error(f"Failed to delete graph DB data for repo {repo_id}: {e}")
            details["graph_db_error"] = str(e)

        # 2. 删除向量数据库中对应仓库所有数据
        try:
            vector_db = get_vector_db_client()
            logger.info(f"Deleting vector data for repo_id: {repo_id!r}")
            if not repo_id:
                logger.error("repo_id is empty or None")
                details["vector_db_error"] = "repo_id is empty"
            else:
                deleted_stats = await vector_db.delete_repo_data(repo_id)
                details["vector_db_deleted"] = True
                details["vector_db_deleted_stats"] = deleted_stats
                logger.info(f"Deleted vectors from DB for repo: {repo_id}, stats: {deleted_stats}")
        except Exception as e:
            logger.error(f"Failed to delete vector DB data for repo {repo_id}: {e}")
            details["vector_db_error"] = str(e)

        # 3. 在 CSV 文件中删除对应仓库数据
        try:
            repo_storage = get_repo_status_storage()
            csv_deleted = repo_storage.delete_record(repo_id)
            details["csv_record_deleted"] = csv_deleted
            if csv_deleted:
                logger.info(f"Deleted CSV record for repo: {repo_id}")
        except Exception as e:
            logger.error(f"Failed to delete CSV record for repo {repo_id}: {e}")
            details["csv_error"] = str(e)

        # 4. 清除仓库 log 目录下的上下文 json 文件，若有执行日志，移入 history 文件夹
        try:
            log_manager = get_pipeline_log_manager()
            log_manager.reset_repo_logs(repo_id)
            details["logs_reset"] = True
            logger.info(f"Reset logs for repo: {repo_id}")
        except Exception as e:
            logger.error(f"Failed to reset logs for repo {repo_id}: {e}")
            details["logs_error"] = str(e)

        # 如果所有关键操作都成功，返回成功
        success = (
            details["graph_db_deleted"]
            and details["vector_db_deleted"]
            and details["csv_record_deleted"]
            and details["logs_reset"]
        )

        if success:
            message = f"仓库 {repo_id} 初始化状态已重置"
        else:
            message = f"仓库 {repo_id} 初始化状态部分重置，请查看 details 了解详情"

        return ResetResponse(
            repo_id=repo_id,
            success=success,
            message=message,
            details=details,
        )

    except Exception as e:
        logger.exception(f"Reset initialization failed for repo {repo_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"重置初始化失败: {str(e)}",
        )
