import pytest

from app.core.nodes.create_document_node import CreateDocumentNode
from app.core.state import create_initial_state
from app.domain.model import TemplateBlock


class _WorkspaceAdapter:
    def __init__(self, repo_name="飞行控制系统", template_name="DO178文档模板"):
        self.repo_name = repo_name
        self.template_name = template_name

    async def get_repo_name(self, repo_id):
        return self.repo_name

    async def get_template_name(self, template_id):
        return self.template_name


@pytest.mark.asyncio
async def test_document_title_combines_repository_and_template_names():
    node = CreateDocumentNode(_WorkspaceAdapter())
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")

    title = await node._resolve_title(state)

    assert title == "飞行控制系统 - DO178文档"


@pytest.mark.asyncio
async def test_document_title_falls_back_to_outline_when_metadata_is_missing():
    node = CreateDocumentNode(_WorkspaceAdapter(repo_name="", template_name=""))
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")
    state["blocks"] = [
        TemplateBlock(
            id="heading-1",
            parent_block_id=None,
            block_type="heading",
            heading_level=1,
            order_no="a",
            content_text="概述",
            attrs={},
        )
    ]

    title = await node._resolve_title(state)

    assert title == "概述"


class _FailingWorkspaceAdapter(_WorkspaceAdapter):
    async def get_repo_name(self, repo_id):
        raise RuntimeError("repo unavailable")

    async def get_template_name(self, template_id):
        raise RuntimeError("template unavailable")


@pytest.mark.asyncio
async def test_document_title_metadata_failure_does_not_block_generation():
    node = CreateDocumentNode(_FailingWorkspaceAdapter())
    state = create_initial_state(repo_id="repo-1", template_id="tpl-1")

    title = await node._resolve_title(state)

    assert title == "项目文档"
