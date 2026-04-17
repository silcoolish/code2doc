"""Workspace服务适配器模块."""

from app.infrastructure.workspace.workspace_adapter import (
    SaveDocumentRequest,
    SaveDocumentResponse,
    TemplateBlock,
    UploadResourceResponse,
    WorkspaceServiceAdapter,
)

__all__ = [
    "WorkspaceServiceAdapter",
    "TemplateBlock",
    "SaveDocumentRequest",
    "SaveDocumentResponse",
    "UploadResourceResponse",
]
