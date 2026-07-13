from unittest.mock import AsyncMock

import pytest

from app.infrastructure.workspace.workspace_adapter import SaveDocumentRequest, WorkspaceServiceAdapter


@pytest.mark.asyncio
async def test_workspace_adapter_reads_repository_and_template_names():
    adapter = WorkspaceServiceAdapter(base_url="http://workspace")
    adapter.http.get = AsyncMock(
        side_effect=[
            {"success": True, "data": {"repoName": "飞行控制系统"}},
            {"success": True, "data": {"templateName": "DO178文档模板"}},
        ]
    )

    assert await adapter.get_repo_name("repo-1") == "飞行控制系统"
    assert await adapter.get_template_name("tpl-1") == "DO178文档模板"


@pytest.mark.asyncio
async def test_save_document_uses_long_timeout_for_block_payload(monkeypatch):
    monkeypatch.setenv("WORKSPACE_DOCUMENT_SAVE_TIMEOUT", "420")
    monkeypatch.setenv("WORKSPACE_DOCUMENT_SAVE_RETRIES", "0")
    adapter = WorkspaceServiceAdapter(base_url="http://workspace")
    adapter.http.post = AsyncMock(
        return_value={
            "success": True,
            "data": {"id": "doc-1"},
        }
    )

    await adapter.save_document(
        SaveDocumentRequest(
            repo_id="repo-1",
            doc_type="project",
            target_key="__project__",
            title="设计说明",
            blocks=[{"id": "", "blockType": "paragraph", "contentText": "正文"}],
        )
    )

    _, kwargs = adapter.http.post.call_args
    assert kwargs["timeout"] == 420
    assert kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_save_document_keeps_default_policy_for_placeholder_save(monkeypatch):
    monkeypatch.setenv("WORKSPACE_DOCUMENT_SAVE_TIMEOUT", "420")
    monkeypatch.setenv("WORKSPACE_DOCUMENT_SAVE_RETRIES", "0")
    adapter = WorkspaceServiceAdapter(base_url="http://workspace")
    adapter.http.post = AsyncMock(
        return_value={
            "success": True,
            "data": {"id": "doc-1"},
        }
    )

    await adapter.save_document(
        SaveDocumentRequest(
            repo_id="repo-1",
            doc_type="project",
            target_key="__project__",
            title="设计说明",
            blocks=[],
        )
    )

    _, kwargs = adapter.http.post.call_args
    assert kwargs["timeout"] == 30.0
    assert kwargs["max_retries"] == 3
