"""内容生成器 - LangChain Agent实现 (使用langchain-mcp-adapters)."""

import re
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.core.state import ContentBlock, ContentBlockType, ListBlockResult, ListItemContent
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Agent系统提示词
CONTENT_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家，正在为一款软件系统撰写设计说明文档。

## 你的任务
根据提供的代码知识库信息，生成高质量的技术文档内容。

## 可用工具
你可以使用以下工具获取代码信息：
- get_project_structure: 获取项目目录结构
- search_nodes: 根据关键字语义查询节点
- get_modules: 获取项目的模块列表
- get_module_workflows: 获取模块对应的工作流列表
- get_node_by_id: 根据节点ID获取详细信息
- get_node_dependencies: 获取节点的依赖关系
- get_file_content: 获取文件内容
- search_code: 语义搜索代码

## 生成要求
1. 内容必须准确，基于代码实际情况
2. 语言专业、简洁、清晰
3. 符合技术文档写作规范
4. 标题内容要精炼，一般不超过20个字
5. 正文内容要有条理，分点说明

## 工作流程
1. 首先使用工具了解项目整体结构
2. 根据主题搜索相关代码和模块信息
3. 综合分析后生成文档内容
4. 确保内容完整且准确

生成完成后，直接输出最终内容，不需要解释过程。"""

# 列表生成专用提示词
LIST_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家。你的任务是根据主题生成一个简洁的列表。

## 生成要求
1. 列表项应该简洁明了，每个项不超过15个字
2. 列表项应该是同一级别的并列关系
3. 直接输出列表，每行一个项目
4. 不要输出编号或解释

格式示例：
用户管理
订单管理
商品管理
支付系统
消息通知"""


class ContentGenerator:
    """内容生成器 - 基于LangChain Agent."""

    def __init__(self, mcp_client: MCPClient):
        """初始化内容生成器."""
        self.mcp_client = mcp_client

        settings = get_settings()
        base_url = settings.dashscope_base_url.replace(
            "/api/v1", "/compatible-mode/v1"
        )

        self.llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=base_url,
            temperature=0.7,
            max_retries=3,
            timeout=120,
        )

        logger.info(
            "content_generator_initialized",
            model=settings.llm_model,
        )

    async def _load_langchain_tools(self) -> List[Any]:
        """加载MCP工具."""
        if not self.mcp_client.client:
            raise RuntimeError("MCP client not connected")
        return await self.mcp_client.client.get_tools()

    async def generate(
        self,
        block: ContentBlock,
        repo_id: str,
    ) -> Union[str, ListBlockResult]:
        """生成单个内容块的内容.

        当 is_list=False 时，返回单个字符串。
        当 is_list=True 时，返回 ListBlockResult，包含：
        - 生成的列表项
        - 每个列表项下子段落的生成内容

        Args:
            block: 内容块
            repo_id: 仓库ID

        Returns:
            生成的内容 (str 或 ListBlockResult)
        """
        logger.info(
            "generate_content_start",
            block_id=block.id,
            block_type=block.type.value,
            prompt=block.prompt,
            is_list=block.is_list,
            has_children=block.list_children is not None,
        )

        try:
            if block.is_list:
                return await self._generate_list_with_children(block, repo_id)
            else:
                return await self._generate_single_content(block, repo_id)

        except Exception as e:
            logger.error(
                "generate_content_failed",
                block_id=block.id,
                error=str(e),
            )
            raise

    async def _generate_list_with_children(
        self,
        block: ContentBlock,
        repo_id: str,
    ) -> ListBlockResult:
        """生成列表及其子段落内容.

        第1阶段：生成标题列表
        第2阶段：为每个列表项生成子段落内容

        Args:
            block: 内容块（is_list=True）
            repo_id: 仓库ID

        Returns:
            ListBlockResult
        """
        from app.core.state import ListTemplateChild

        # 阶段1：生成列表
        logger.info(
            "generate_list_phase1",
            block_id=block.id,
            prompt=block.prompt,
        )

        list_items = await self._generate_list_items(block, repo_id)

        logger.info(
            "generate_list_phase1_complete",
            block_id=block.id,
            item_count=len(list_items),
            items=list_items,
        )

        # 阶段2：为每个列表项生成子段落内容
        list_item_contents = []

        for i, item in enumerate(list_items):
            logger.info(
                "generate_list_item_start",
                block_id=block.id,
                list_index=i,
                item=item,
            )

            # 收集子段落生成结果
            child_contents: Dict[str, str] = {}

            if block.list_children:
                for child_template in block.list_children:
                    child_id = child_template.id

                    if child_template.template_block:
                        # 动态子段落：需要生成内容
                        child_block = child_template.template_block

                        # 使用列表项作为上下文
                        prompt_with_context = f"关于'{item}'，{child_block.prompt}"
                        child_block_with_context = ContentBlock(
                            id=f"{child_id}_item_{i}",
                            type=child_block.type,
                            prompt=prompt_with_context,
                            min_length=child_block.min_length,
                            max_length=child_block.max_length,
                        )

                        try:
                            generated = await self._generate_single_content(
                                child_block_with_context, repo_id
                            )
                            child_contents[child_id] = generated

                            logger.info(
                                "generate_child_content_success",
                                block_id=block.id,
                                list_index=i,
                                child_id=child_id,
                                content_length=len(generated),
                            )
                        except Exception as e:
                            logger.warning(
                                "generate_child_content_failed",
                                block_id=block.id,
                                list_index=i,
                                child_id=child_id,
                                error=str(e),
                            )
                            child_contents[child_id] = ""
                    else:
                        # 纯静态子段落：无需生成
                        child_contents[child_id] = ""

            list_item_contents.append(ListItemContent(
                headline=item,
                child_contents=child_contents,
            ))

            logger.info(
                "generate_list_item_complete",
                block_id=block.id,
                list_index=i,
                item=item,
            )

        logger.info(
            "generate_list_complete",
            block_id=block.id,
            item_count=len(list_item_contents),
        )

        return ListBlockResult(
            items=list_item_contents,
            list_children_template=block.list_children or [],
        )

    async def _generate_list_items(
        self,
        block: ContentBlock,
        repo_id: str,
    ) -> List[str]:
        """生成列表项.

        Args:
            block: 内容块
            repo_id: 仓库ID

        Returns:
            列表项字符串列表
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=LIST_GENERATION_SYSTEM_PROMPT),
            HumanMessage(content=self._build_list_task_message(block, repo_id)),
        ]

        max_iterations = 10
        for i in range(max_iterations):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    if "repo_id" not in tool_args:
                        tool_args["repo_id"] = repo_id

                    try:
                        result = await self.mcp_client.call_tool(tool_name, tool_args)
                        if len(result) > 2000:
                            result = result[:2000] + "\n... (内容已截断)"
                    except Exception as e:
                        result = f"工具调用失败: {str(e)}"

                    messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call.get("id", ""),
                        name=tool_name,
                    ))
            else:
                break

        final_response = messages[-1]
        raw_content = final_response.content if hasattr(final_response, "content") else str(final_response)

        return self._parse_list_content(raw_content)

    async def _generate_single_content(
        self,
        block: ContentBlock,
        repo_id: str,
    ) -> str:
        """生成单个内容.

        Args:
            block: 内容块
            repo_id: 仓库ID

        Returns:
            生成的内容字符串
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=CONTENT_GENERATION_SYSTEM_PROMPT),
        ]

        type_desc = "标题" if block.type == ContentBlockType.HEADLINE else "正文"
        task_msg = self._build_task_message(block, repo_id, type_desc)
        messages.append(HumanMessage(content=task_msg))

        max_iterations = 10
        for i in range(max_iterations):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    if "repo_id" not in tool_args:
                        tool_args["repo_id"] = repo_id

                    try:
                        result = await self.mcp_client.call_tool(tool_name, tool_args)
                        if len(result) > 2000:
                            result = result[:2000] + "\n... (内容已截断)"
                    except Exception as e:
                        result = f"工具调用失败: {str(e)}"

                    messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call.get("id", ""),
                        name=tool_name,
                    ))
            else:
                break

        final_response = messages[-1]
        raw_content = final_response.content if hasattr(final_response, "content") else str(final_response)

        return self._apply_length_constraints(
            raw_content, block.min_length, block.max_length
        )

    def _parse_list_content(self, raw_content: str) -> List[str]:
        """解析列表格式的内容."""
        lines = raw_content.strip().split('\n')
        items = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            cleaned = re.sub(r'^(\d+[\.、]\s*|[-*•]\s+)', '', line)
            if cleaned:
                items.append(cleaned)

        if not items and raw_content.strip():
            items = [raw_content.strip()]

        return items

    def _apply_length_constraints(
        self,
        content: str,
        min_length: Optional[int],
        max_length: Optional[int],
    ) -> str:
        """应用长度限制."""
        if max_length and len(content) > max_length:
            content = content[:max_length] + "..."

        return content

    def _build_task_message(self, block: ContentBlock, repo_id: str, type_desc: str) -> str:
        """构建任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            f"请为以下内容生成{type_desc}:",
            f"主题: {block.prompt}",
        ]

        length_constraints = []
        if block.min_length:
            length_constraints.append(f"最少{block.min_length}字")
        if block.max_length:
            length_constraints.append(f"最多{block.max_length}字")

        if length_constraints:
            task_parts.append(f"\n字数要求: {', '.join(length_constraints)}")

        task_parts.append("\n请生成一段完整的内容。")
        task_parts.extend([
            "\n请开始生成。你可以使用工具来获取代码信息。",
        ])

        return "\n".join(task_parts)

    def _build_list_task_message(self, block: ContentBlock, repo_id: str) -> str:
        """构建列表生成任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            f"请为主题生成一个简洁的列表:",
            f"主题: {block.prompt}",
            "",
            "要求：",
            "1. 列表项应该简洁明了，每个项不超过15个字",
            "2. 列表项应该是同一级别的并列关系",
            "3. 直接输出列表，每行一个项目",
            "4. 不要输出编号或解释",
            "",
            "请开始生成。你可以使用工具来获取代码信息。",
        ]

        return "\n".join(task_parts)
