import asyncio
import time
from unittest.mock import patch

import pytest
import httpx

from app.core.nodes import process_image_blocks_node
from app.core.nodes.process_image_blocks_node import ProcessImageBlocksNode


class _WorkspaceAdapter:
    pass


class _UploadResponse:
    success = True
    resource_id = "asset-1"
    error = None


class _UploadResponseWithId:
    def __init__(self, resource_id):
        self.success = True
        self.resource_id = resource_id
        self.error = None


class _Reporter:
    def __init__(self):
        self.calls = []

    async def report_step(self, current, total, message=None):
        self.calls.append((current, total, message))


class _McpClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return self.result


class _SequencedMcpClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if not self.results:
            raise AssertionError("unexpected MCP call")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.mark.asyncio
async def test_process_image_blocks_runs_with_bounded_parallelism_and_keeps_order():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.download_parallelism = 3
    node.upload_parallelism = 3
    download_client = object()
    upload_client = object()
    received_clients = []

    async def process_image_block(
        block,
        document_id,
        repo_id,
        download_client=None,
        upload_client=None,
        download_semaphore=None,
        upload_semaphore=None,
    ):
        received_clients.append((download_client, upload_client))
        await asyncio.sleep(0.05)
        return {**block, "contentText": f"done-{block['id']}"}

    node._process_image_block = process_image_block
    reporter = _Reporter()
    blocks = [
        {"id": "p1", "blockType": "paragraph", "contentText": "intro"},
        {"id": "i1", "blockType": "image", "contentText": "a.svg"},
        {"id": "i2", "blockType": "image", "contentText": "b.svg"},
        {"id": "p2", "blockType": "paragraph", "contentText": "middle"},
        {"id": "i3", "blockType": "image", "contentText": "c.svg"},
    ]

    start = time.perf_counter()
    result = await node._process_blocks(
        blocks,
        "doc-1",
        "repo-1",
        reporter,
        download_client=download_client,
        upload_client=upload_client,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.12
    assert [block["id"] for block in result] == ["p1", "i1", "i2", "p2", "i3"]
    assert [block["contentText"] for block in result] == [
        "intro",
        "done-i1",
        "done-i2",
        "middle",
        "done-i3",
    ]
    assert received_clients == [
        (download_client, upload_client),
        (download_client, upload_client),
        (download_client, upload_client),
    ]
    assert reporter.calls[-1][0:2] == (3, 3)


@pytest.mark.asyncio
async def test_process_image_blocks_propagates_function_refs_before_filtering_missing_image():
    source_refs = [{
        "sourceId": "method_repo_src/system.c_System_Init",
        "symbolName": "System_Init",
        "filePath": "src/system.c",
        "lineStart": 3,
        "lineEnd": 13,
    }]
    node = ProcessImageBlocksNode(
        _WorkspaceAdapter(),
        _McpClient({
            "images": [{
                "node_id": source_refs[0]["sourceId"],
                "success": False,
                "error": "No image available",
            }],
        }),
    )
    blocks = [
        {
            "id": "heading-1",
            "blockType": "heading",
            "headingLevel": 3,
            "contentText": "System_Init",
            "sourceRefs": [],
        },
        {
            "id": "table-1",
            "blockType": "table",
            "contentText": {"rows": []},
            "sourceRefs": [],
        },
        {
            "id": "image-1",
            "blockType": "image",
            "contentText": None,
            "sourceRefs": source_refs,
        },
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["id"] for block in result] == ["heading-1", "table-1"]
    assert result[0]["sourceRefs"] == source_refs
    assert result[1]["sourceRefs"] == source_refs
    assert result[0]["sourceRefs"] is not source_refs
    assert result[1]["sourceRefs"] is not source_refs


def test_function_ref_propagation_stops_at_non_matching_nearest_heading():
    source_refs = [{
        "sourceId": "method_repo_src/system.c_System_Init",
        "symbolName": "System_Init",
        "filePath": "src/system.c",
        "lineStart": 3,
        "lineEnd": 13,
    }]
    blocks = [
        {
            "id": "heading-1",
            "blockType": "heading",
            "headingLevel": 3,
            "contentText": "System_Init",
            "sourceRefs": [],
        },
        {
            "id": "heading-2",
            "blockType": "heading",
            "headingLevel": 3,
            "contentText": "System_RunCycle",
            "sourceRefs": [],
        },
        {
            "id": "image-1",
            "blockType": "image",
            "contentText": "system-init.svg",
            "sourceRefs": source_refs,
        },
    ]

    ProcessImageBlocksNode._propagate_function_source_refs(blocks)

    assert blocks[0]["sourceRefs"] == []
    assert blocks[1]["sourceRefs"] == []


@pytest.mark.asyncio
async def test_process_image_blocks_limits_upload_parallelism_independently():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.download_parallelism = 4
    node.upload_parallelism = 1
    node.process_drawio = False
    active_uploads = 0
    max_active_uploads = 0

    async def download_file(url, max_retries=3, client=None):
        return b"image"

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        nonlocal active_uploads, max_active_uploads
        active_uploads += 1
        max_active_uploads = max(max_active_uploads, active_uploads)
        await asyncio.sleep(0.01)
        active_uploads -= 1
        return _UploadResponse()

    node._download_file = download_file
    node._upload_resource = upload_resource
    blocks = [
        {"id": f"i{index}", "blockType": "image", "contentText": f"{index}.svg"}
        for index in range(4)
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert len(result) == 4
    assert max_active_uploads == 1


@pytest.mark.asyncio
async def test_process_image_blocks_filters_block_when_one_image_fails():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.download_parallelism = 2
    node.upload_parallelism = 2

    async def process_image_block(
        block,
        document_id,
        repo_id,
        download_client=None,
        upload_client=None,
        download_semaphore=None,
        upload_semaphore=None,
    ):
        if block["id"] == "i2":
            raise RuntimeError("boom")
        return {**block, "contentText": f"done-{block['id']}"}

    node._process_image_block = process_image_block
    blocks = [
        {"id": "i1", "blockType": "image", "contentText": "a.svg"},
        {"id": "i2", "blockType": "image", "contentText": "b.svg"},
        {"id": "i3", "blockType": "image", "contentText": "c.svg"},
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["contentText"] for block in result] == ["done-i1", "done-i3"]


@pytest.mark.asyncio
async def test_download_http_does_not_retry_missing_resource():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        result = await node._download_http("http://test/missing.drawio", client=client)

    assert result is None
    assert calls == 1


@pytest.mark.asyncio
async def test_download_http_rejects_stream_larger_than_limit_without_content_length():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())

    async def handler(request):
        return httpx.Response(200, content=b"abcdef")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        with patch.object(process_image_blocks_node, "MAX_FILE_SIZE", 3):
            result = await node._download_http("http://test/large.svg", client=client)

    assert result is None


@pytest.mark.asyncio
async def test_process_image_blocks_fills_missing_image_refs_from_source_refs():
    node = ProcessImageBlocksNode(
        _WorkspaceAdapter(),
        _McpClient({
            "images": [{
                "node_id": "method-main",
                "success": True,
                "image_id": "main.flowchart.svg",
            }],
        }),
    )

    async def process_image_block(
        block,
        document_id,
        repo_id,
        download_client=None,
        upload_client=None,
        download_semaphore=None,
        upload_semaphore=None,
    ):
        return {**block, "attrs": {**block.get("attrs", {}), "assetId": "asset-1"}}

    node._process_image_block = process_image_block
    blocks = [{
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert result[0]["contentText"] == "main.flowchart.svg"
    assert result[0]["attrs"]["assetId"] == "asset-1"
    assert node.mcp_client.calls == [
        ("batch_get_image_ids", {"repo_id": "repo-1", "node_ids": ["method-main"]})
    ]


@pytest.mark.asyncio
async def test_image_ref_lookup_retries_transport_and_empty_results_before_success():
    mcp_client = _SequencedMcpClient([
        RuntimeError("temporary MCP outage"),
        {"images": []},
        {
            "images": [{
                "node_id": "method-main",
                "success": True,
                "image_id": "main.flowchart.svg",
            }],
        },
    ])
    node = ProcessImageBlocksNode(_WorkspaceAdapter(), mcp_client)
    blocks = [{
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }]

    with patch.object(process_image_blocks_node, "IMAGE_REF_LOOKUP_RETRY_DELAY", 0):
        result = await node._fill_missing_image_refs_from_source_refs(blocks, "repo-1")

    assert result[0]["contentText"] == "main.flowchart.svg"
    assert len(mcp_client.calls) == 3
    assert all(
        arguments == {"repo_id": "repo-1", "node_ids": ["method-main"]}
        for _, arguments in mcp_client.calls
    )


@pytest.mark.asyncio
async def test_missing_image_reference_is_filtered_without_confirmation():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    block = {
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result is None


@pytest.mark.asyncio
async def test_template_asset_id_does_not_skip_current_document_upload():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.process_drawio = False
    uploads = []

    async def download_file(url, max_retries=3, client=None):
        return b"image"

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        uploads.append((document_id, block_id, file_name))
        return _UploadResponseWithId("asset-current-document")

    node._download_file = download_file
    node._upload_resource = upload_resource
    block = {
        "id": "img-1",
        "blockType": "image",
        "contentText": "main.flowchart.svg",
        "assetId": "top-level-asset-from-template",
        "asset_id": "snake-top-level-asset-from-template",
        "attrs": {
            "assetId": "asset-from-template",
            "svgAssetId": "svg-from-template",
            "svg_asset_id": "snake-svg-from-template",
            "drawioAssetId": "drawio-from-template",
            "editableAssetId": "editable-from-template",
            "editable_asset_id": "snake-editable-from-template",
            "exportImageAssetId": "export-from-template",
            "export_image_asset_id": "snake-export-from-template",
        },
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert "assetId" not in result
    assert "asset_id" not in result
    assert result["attrs"]["assetId"] == "asset-current-document"
    assert set(result["attrs"]) == {"assetId", "caption", "alt"}
    assert uploads == [("doc-1", "img-1", "main.flowchart.svg")]


@pytest.mark.asyncio
async def test_template_asset_id_without_image_reference_is_filtered():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    block = {
        "id": "img-1",
        "blockType": "image",
        "contentText": "已有图片",
        "attrs": {"assetId": "asset-from-template"},
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result is None


@pytest.mark.asyncio
async def test_process_image_block_preserves_explicit_caption():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.process_drawio = False

    async def download_file(url, max_retries=3, client=None):
        return b"image"

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        return _UploadResponse()

    node._download_file = download_file
    node._upload_resource = upload_resource
    block = {
        "id": "img-1",
        "blockType": "image",
        "contentText": "main.flowchart.svg",
        "attrs": {"caption": "main函数流程图"},
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result["contentText"] == "main函数流程图"
    assert result["attrs"]["caption"] == "main函数流程图"
    assert result["attrs"]["alt"] == "main函数流程图"


@pytest.mark.asyncio
async def test_process_drawio_architecture_block_uploads_drawio_asset():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    uploads = []

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        uploads.append((file_name, file_content, resource_type, block_id))
        return _UploadResponseWithId(f"asset-{len(uploads)}")

    node._upload_resource = upload_resource
    block = {
        "id": "architecture-1",
        "blockType": "image",
        "contentText": {
            "title": "StarCodeDoc 项目架构图",
            "layers": [
                {
                    "id": "desktop",
                    "label": "L1",
                    "name": "桌面工作台",
                    "items": [{"id": "editor", "name": "文档编辑"}],
                },
                {
                    "id": "workspace",
                    "label": "L2",
                    "name": "工作空间服务",
                    "items": [{"id": "document", "name": "文档中心"}],
                },
            ],
            "connections": [{"from": "editor", "to": "document", "label": "HTTP API"}],
            "pipeline": [{"name": "代码仓库"}, {"name": "生成文档"}],
        },
        "attrs": {"format": "drawio_architecture"},
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result["blockType"] == "image"
    assert result["contentText"] == "StarCodeDoc 项目架构图"
    assert result["attrs"]["drawioAssetId"] == "asset-1"
    assert result["attrs"]["editableAssetId"] == "asset-1"
    assert result["attrs"]["renderKind"] == "drawio"
    assert "assetId" not in result["attrs"]
    assert "svgAssetId" not in result["attrs"]
    assert uploads[0][0].endswith(".drawio")
    assert uploads[0][2] == "drawio"
    assert b"mxGraphModel" in uploads[0][1]


@pytest.mark.asyncio
async def test_process_drawio_architecture_block_preserves_explicit_caption():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        return _UploadResponseWithId("asset-drawio")

    node._upload_resource = upload_resource
    block = {
        "id": "architecture-1",
        "blockType": "image",
        "contentText": {
            "title": "模型生成的架构图名称",
            "layers": [
                {"id": "entry", "name": "入口层", "items": [{"id": "main", "name": "主入口"}]},
                {"id": "core", "name": "核心层", "items": [{"id": "run", "name": "核心处理"}]},
            ],
        },
        "attrs": {"format": "drawio_architecture", "caption": "项目总体架构图"},
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result["contentText"] == "项目总体架构图"
    assert result["attrs"]["caption"] == "项目总体架构图"
    assert result["attrs"]["alt"] == "项目总体架构图"


@pytest.mark.asyncio
async def test_process_drawio_architecture_block_uses_title_from_fenced_json():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        return _UploadResponseWithId("asset-drawio")

    node._upload_resource = upload_resource
    block = {
        "id": "architecture-1",
        "blockType": "image",
        "contentText": (
            "```json\n"
            '{"title":"订单系统架构图","layers":['
            '{"id":"service","name":"服务层","items":[]}]}'
            "\n```"
        ),
        "asset_id": "snake-top-level-image-from-template",
        "attrs": {
            "format": "drawio_architecture",
            "assetId": "image-from-template",
            "svgAssetId": "svg-from-template",
            "exportImageAssetId": "export-from-template",
            "drawioAssetId": "asset-from-template",
            "editableAssetId": "asset-from-template",
        },
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result["contentText"] == "订单系统架构图"
    assert "asset_id" not in result
    assert result["attrs"]["caption"] == "订单系统架构图"
    assert result["attrs"]["drawioAssetId"] == "asset-drawio"
    assert result["attrs"]["editableAssetId"] == "asset-drawio"
    assert "assetId" not in result["attrs"]
    assert "svgAssetId" not in result["attrs"]
    assert "exportImageAssetId" not in result["attrs"]


@pytest.mark.asyncio
async def test_process_drawio_architecture_block_filters_block_when_drawio_upload_fails():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    uploads = []

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        uploads.append((file_name, file_content, resource_type, block_id))
        response = _UploadResponseWithId("")
        response.success = False
        response.error = "upload failed"
        return response

    node._upload_resource = upload_resource
    block = {
        "id": "architecture-1",
        "blockType": "image",
        "contentText": {
            "title": "StarCodeDoc 项目架构图",
            "layers": [
                {
                    "id": "desktop",
                    "label": "L1",
                    "name": "桌面工作台",
                    "items": [{"id": "editor", "name": "文档编辑"}],
                },
                {
                    "id": "workspace",
                    "label": "L2",
                    "name": "工作空间服务",
                    "items": [{"id": "document", "name": "文档中心"}],
                },
            ],
        },
        "attrs": {"format": "drawio_architecture"},
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result is None
    assert [upload[2] for upload in uploads] == ["drawio"]


@pytest.mark.asyncio
async def test_process_image_blocks_filters_confirmed_missing_image_reference():
    node = ProcessImageBlocksNode(
        _WorkspaceAdapter(),
        _McpClient({
            "images": [{
                "node_id": "method-main",
                "success": False,
                "error": "No image available",
            }],
        }),
    )
    node.download_parallelism = 2
    node.upload_parallelism = 2
    blocks = [
        {"id": "p1", "blockType": "paragraph", "contentText": "intro"},
        {
            "id": "img-1",
            "blockType": "image",
            "contentText": None,
            "attrs": {},
            "sourceRefs": [{"sourceId": "method-main"}],
        },
        {"id": "p2", "blockType": "paragraph", "contentText": "outro"},
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["id"] for block in result] == ["p1", "p2"]
    assert node.mcp_client.calls == [
        ("batch_get_image_ids", {"repo_id": "repo-1", "node_ids": ["method-main"]})
    ]


@pytest.mark.asyncio
async def test_process_image_blocks_filters_unconfirmed_missing_image_reference():
    mcp_client = _McpClient({"images": []})
    node = ProcessImageBlocksNode(_WorkspaceAdapter(), mcp_client)
    blocks = [{
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }]

    with patch.object(process_image_blocks_node, "IMAGE_REF_LOOKUP_RETRY_DELAY", 0):
        result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert result == []
    assert len(mcp_client.calls) == 3
    assert blocks[0]["attrs"][process_image_blocks_node.IMAGE_LOOKUP_FAILED_ATTR] is True


@pytest.mark.asyncio
async def test_process_image_blocks_filters_download_failed_image_reference():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.process_drawio = False

    async def download_file(url, max_retries=3, client=None):
        return None

    node._download_file = download_file
    blocks = [
        {"id": "p1", "blockType": "paragraph", "contentText": "intro"},
        {"id": "img-1", "blockType": "image", "contentText": "missing.flowchart.svg"},
        {"id": "p2", "blockType": "paragraph", "contentText": "outro"},
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["id"] for block in result] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_process_image_blocks_filters_upload_failed_image_reference():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    node.process_drawio = False

    async def download_file(url, max_retries=3, client=None):
        return b"image"

    async def upload_resource(
        file_name,
        file_content,
        document_id,
        resource_type,
        block_id=None,
        client=None,
    ):
        response = _UploadResponseWithId("")
        response.success = False
        response.error = "upload failed"
        return response

    node._download_file = download_file
    node._upload_resource = upload_resource
    blocks = [
        {"id": "p1", "blockType": "paragraph", "contentText": "intro"},
        {"id": "img-1", "blockType": "image", "contentText": "broken.flowchart.svg"},
        {"id": "p2", "blockType": "paragraph", "contentText": "outro"},
    ]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["id"] for block in result] == ["p1", "p2"]
