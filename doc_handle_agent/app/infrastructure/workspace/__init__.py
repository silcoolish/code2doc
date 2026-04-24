"""Workspace服务适配器模块."""

from app.domain.model.block import TemplateBlock
from app.infrastructure.workspace.workspace_adapter import (
    SaveDocumentRequest,
    SaveDocumentResponse,
    SaveResourceRequest,
    SaveResourceResponse,
    UploadResourceResponse,
    WorkspaceServiceAdapter,
)

__all__ = [
    "WorkspaceServiceAdapter",
    "TemplateBlock",
    "SaveDocumentRequest",
    "SaveDocumentResponse",
    "SaveResourceRequest",
    "SaveResourceResponse",
    "UploadResourceResponse",
]
