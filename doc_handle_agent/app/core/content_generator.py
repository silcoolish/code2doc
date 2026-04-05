"""内容生成器."""

import json
from typing import Any, Dict, List

from app.core.state import ContentBlock, ContentBlockType
from app.infrastructure.llm_client import BaseLLMClient, LLMClientFactory
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 内容生成系统提示词
CONTENT_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家，正在为一款软件系统撰写设计说明文档。

## 你的任务
根据提供的代码知识库信息，生成高质量的技术文档内容。

## 可用工具
你可以使用以下工具获取代码信息：
- get_project_structure(repo_id): 获取项目目录结构
- search_nodes(repo_id, query, node_types, top_k): 根据关键字语义查询节点
- get_modules(repo_id): 获取项目的模块列表
- get_module_workflows(repo_id, module_id): 获取模块对应的工作流列表
- get_node_by_id(node_id): 根据节点ID获取详细信息
- get_node_dependencies(node_id, depth): 获取节点的依赖关系
- get_file_content(file_id): 获取文件内容
- search_code(repo_id, query, top_k): 语义搜索代码

## 生成要求
1. 内容必须准确，基于代码实际情况
2. 语言专业、简洁、清晰
3. 符合技术文档写作规范
4. 如有长度限制，请严格遵守
5. 标题内容要精炼，一般不超过20个字
6. 正文内容要有条理，分点说明

## 工作流程
1. 首先使用工具了解项目整体结构
2. 根据主题搜索相关代码和模块信息
3. 综合分析后生成文档内容
4. 确保内容完整且准确
"""


class ContentGenerator:
    """内容生成器."""

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: Optional[BaseLLMClient] = None,
    ):
        """初始化内容生成器.

        Args:
            mcp_client: MCP客户端
            llm_client: LLM客户端，默认创建新实例
        """
        self.mcp_client = mcp_client
        self.llm_client = llm_client or LLMClientFactory.create()

    async def generate(
        self,
        block: ContentBlock,
        repo_id: str,
    ) -> str:
        """生成单个内容块的内容.

        Args:
            block: 内容块
            repo_id: 仓库ID

        Returns:
            生成的内容
        """
        logger.info(
            "generate_content_start",
            block_id=block.id,
            block_type=block.type.value,
            prompt=block.prompt,
        )

        # 构建提示词
        prompt = self._build_prompt(block, repo_id)

        try:
            # 第一次调用，可能触发工具调用
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=CONTENT_GENERATION_SYSTEM_PROMPT,
                tools=self.mcp_client.get_available_tools(),
            )

            # 处理工具调用循环
            max_iterations = 10
            iteration = 0

            while response.has_tool_calls and iteration < max_iterations:
                iteration += 1
                logger.info(
                    "processing_tool_calls",
                    iteration=iteration,
                    tool_count=len(response.tool_calls),
                )

                # 执行工具调用
                tool_results = await self._execute_tool_calls(
                    response.tool_calls, repo_id
                )

                # 构建跟进提示词
                follow_up_prompt = self._build_follow_up_prompt(
                    prompt, response, tool_results
                )

                # 再次调用LLM
                response = await self.llm_client.generate(
                    prompt=follow_up_prompt,
                    system_prompt=CONTENT_GENERATION_SYSTEM_PROMPT,
                    tools=self.mcp_client.get_available_tools(),
                )

            logger.info(
                "generate_content_success",
                block_id=block.id,
                content_length=len(response.content),
            )

            return response.content

        except Exception as e:
            logger.error(
                "generate_content_failed",
                block_id=block.id,
                error=str(e),
            )
            raise

    def _build_prompt(self, block: ContentBlock, repo_id: str) -> str:
        """构建生成提示词.

        Args:
            block: 内容块
            repo_id: 仓库ID

        Returns:
            提示词
        """
        type_desc = "标题" if block.type == ContentBlockType.HEADLINE else "正文"

        prompt_parts = [
            f"仓库ID: {repo_id}",
            f"",
            f"请为以下内容生成{type_desc}:",
            f"主题: {block.prompt}",
        ]

        if block.is_list:
            prompt_parts.append(f"\n要求生成列表形式的内容")
            if block.min_length:
                prompt_parts.append(f"最少{block.min_length}项")
            if block.max_length:
                prompt_parts.append(f"最多{block.max_length}项")

        prompt_parts.extend([
            "\n请遵循以下步骤:",
            "1. 使用 get_project_structure 了解项目整体结构",
            "2. 使用 search_nodes 或 search_code 搜索相关信息",
            "3. 根据需要获取更多详细信息",
            "4. 生成最终内容",
            "\n请直接生成内容，不需要解释过程。",
        ])

        return "\n".join(prompt_parts)

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict],
        repo_id: str,
    ) -> List[Dict[str, Any]]:
        """执行工具调用.

        Args:
            tool_calls: 工具调用列表
            repo_id: 仓库ID

        Returns:
            工具执行结果列表
        """
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])

            # 确保repo_id在参数中
            if "repo_id" not in arguments:
                arguments["repo_id"] = repo_id

            logger.info(
                "execute_tool_call",
                tool_name=tool_name,
                arguments=arguments,
            )

            try:
                result = await self.mcp_client.call_tool(tool_name, arguments)
                results.append({
                    "tool_call_id": tool_call.get("id", ""),
                    "tool_name": tool_name,
                    "result": result,
                })
            except Exception as e:
                logger.error(
                    "tool_call_failed",
                    tool_name=tool_name,
                    error=str(e),
                )
                results.append({
                    "tool_call_id": tool_call.get("id", ""),
                    "tool_name": tool_name,
                    "error": str(e),
                })

        return results

    def _build_follow_up_prompt(
        self,
        original_prompt: str,
        response: Any,
        tool_results: List[Dict],
    ) -> str:
        """构建跟进提示词.

        Args:
            original_prompt: 原始提示词
            response: LLM响应
            tool_results: 工具执行结果

        Returns:
            跟进提示词
        """
        lines = [
            original_prompt,
            "\n## 工具调用结果",
        ]

        for result in tool_results:
            if "error" in result:
                lines.append(
                    f"\n工具 {result['tool_name']} 调用失败: {result['error']}"
                )
            else:
                # 截断过长的结果
                result_text = result["result"]
                if len(result_text) > 2000:
                    result_text = result_text[:2000] + "..."
                lines.append(f"\n工具 {result['tool_name']} 返回:")
                lines.append(result_text)

        lines.extend([
            "\n## 请继续",
            "根据工具返回的信息，继续生成内容或调用更多工具。",
        ])

        return "\n".join(lines)
