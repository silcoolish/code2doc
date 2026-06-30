import json

import pytest

from app.domain.static_list_provider import StaticListProvider


class _MCPClient:
    def __init__(self, nodes):
        self.nodes = nodes
        self.calls = []

    async def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return json.dumps({"nodes": self.nodes}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_get_all_methods_adds_function_line_range_to_source_refs():
    client = _MCPClient([
        {
            "node_id": "method-test-case-16",
            "name": "testCase16",
            "node_type": "Method",
            "file_path": "TinySTL/Test/StringTest.cpp",
            "start_line": 149,
            "end_line": 178,
        }
    ])
    provider = StaticListProvider(client)

    items = await provider.get_list_items("get_all_methods", "repo-1")

    assert client.calls == [(
        "get_all_nodes",
        {
            "repo_id": "repo-1",
            "node_types": ["Method"],
            "returns": [
                "node_id",
                "name",
                "node_type",
                "file_path",
                "start_line",
                "end_line",
            ],
        },
    )]
    assert items[0].source_refs == [{
        "sourceId": "method-test-case-16",
        "symbolName": "testCase16",
        "symbolType": "Method",
        "filePath": "TinySTL/Test/StringTest.cpp",
        "lineStart": 149,
        "lineEnd": 178,
    }]


@pytest.mark.asyncio
async def test_get_all_classes_keeps_source_refs_without_function_line_range():
    client = _MCPClient([
        {
            "node_id": "class-string-test",
            "name": "StringTest",
            "node_type": "Class",
            "file_path": "TinySTL/Test/StringTest.cpp",
            "start_line": 1,
            "end_line": 220,
        }
    ])
    provider = StaticListProvider(client)

    items = await provider.get_list_items("get_all_classes", "repo-1")

    assert client.calls == [(
        "get_all_nodes",
        {"repo_id": "repo-1", "node_types": ["Class"]},
    )]
    assert items[0].source_refs == [{
        "sourceId": "class-string-test",
        "symbolName": "StringTest",
        "symbolType": "Class",
        "filePath": "TinySTL/Test/StringTest.cpp",
    }]
