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
async def test_process_image_blocks_keeps_original_block_when_one_image_fails():
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

    assert [block["contentText"] for block in result] == [
        "done-i1",
        "b.svg",
        "done-i3",
    ]


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
async def test_missing_image_reference_is_kept_without_confirmation():
    node = ProcessImageBlocksNode(_WorkspaceAdapter())
    block = {
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }

    result = await node._process_image_block(block, "doc-1", "repo-1")

    assert result == block


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
async def test_process_image_blocks_keeps_unconfirmed_missing_image_reference():
    node = ProcessImageBlocksNode(
        _WorkspaceAdapter(),
        _McpClient({"images": []}),
    )
    blocks = [{
        "id": "img-1",
        "blockType": "image",
        "contentText": None,
        "attrs": {},
        "sourceRefs": [{"sourceId": "method-main"}],
    }]

    result = await node._process_blocks(blocks, "doc-1", "repo-1")

    assert [block["id"] for block in result] == ["img-1"]
