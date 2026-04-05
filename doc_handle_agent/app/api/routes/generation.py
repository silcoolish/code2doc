"""文档生成API路由."""

from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from app.api.models.schemas import (
    GenerateDocumentRequest,
    GenerateDocumentResponse,
    PreviewTemplateRequest,
    PreviewTemplateResponse,
    ContentBlockInfo,
    ActiveGenerationInfo,
    SystemStatusResponse,
)
from app.core.document_engine import get_document_engine
from app.core.template_parser import TemplateParser
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/generate", response_model=GenerateDocumentResponse)
async def generate_document(
    request: GenerateDocumentRequest,
) -> GenerateDocumentResponse:
    """启动文档生成流程.

    Args:
        request: 生成请求

    Returns:
        生成响应

    Raises:
        HTTPException: 参数无效或文件不存在
    """
    logger.info(
        "api_generate_document",
        repo_id=request.repo_id,
        template_path=request.template_path,
    )

    # 验证模板文件存在
    template_path = Path(request.template_path)
    if not template_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Template file not found: {request.template_path}",
        )

    try:
        engine = get_document_engine()

        flow_id = await engine.start_generation(
            repo_id=request.repo_id,
            template_path=request.template_path,
            output_filename=request.output_filename,
        )

        # 获取初始状态
        state = engine.get_state(flow_id)

        return GenerateDocumentResponse(
            flow_id=flow_id,
            status=state["status"],
            repo_id=request.repo_id,
            template_path=request.template_path,
            output_path=state["output_path"],
            created_at=datetime.now().isoformat(),
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "generate_document_failed",
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start generation: {str(e)}",
        )


@router.post("/preview-template", response_model=PreviewTemplateResponse)
async def preview_template(
    request: PreviewTemplateRequest,
) -> PreviewTemplateResponse:
    """预览模板内容块.

    Args:
        request: 预览请求

    Returns:
        预览响应
    """
    logger.info(
        "api_preview_template",
        template_path=request.template_path,
    )

    parser = TemplateParser()

    # 验证模板
    is_valid, message = parser.validate_template(request.template_path)

    if not is_valid:
        return PreviewTemplateResponse(
            template_path=request.template_path,
            valid=False,
            message=message,
            blocks=[],
        )

    try:
        # 解析内容块
        blocks = parser.preview_blocks(request.template_path)

        block_infos = [
            ContentBlockInfo(
                id=block["id"],
                type=block["type"],
                prompt=block["prompt"],
                is_list=block.get("is_list", False),
                min_length=block.get("min_length"),
                max_length=block.get("max_length"),
            )
            for block in blocks
        ]

        return PreviewTemplateResponse(
            template_path=request.template_path,
            valid=True,
            message=message,
            blocks=block_infos,
        )

    except Exception as e:
        logger.error(
            "preview_template_failed",
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview template: {str(e)}",
        )


@router.get("/active", response_model=List[ActiveGenerationInfo])
async def list_active_generations() -> List[ActiveGenerationInfo]:
    """列出所有活动的生成任务.

    Returns:
        活动生成任务列表
    """
    engine = get_document_engine()
    active = engine.list_active_generations()

    return [
        ActiveGenerationInfo(
            flow_id=item["flow_id"],
            status=item.get("status"),
        )
        for item in active
    ]


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """获取系统状态.

    Returns:
        系统状态响应
    """
    engine = get_document_engine()
    active_count = len(engine.list_active_generations())

    return SystemStatusResponse(
        status="running" if active_count > 0 else "idle",
        active_generations=active_count,
    )
