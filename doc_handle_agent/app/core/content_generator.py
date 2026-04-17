"""内容生成器 - LangChain Agent实现 (使用langchain-mcp-adapters)."""

import base64
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.core.state import (
    GeneratedContentResult,
    ImageInfo,
    StaticParagraph,
    TemplateParagraph,
)
from app.infrastructure.mcp_client import MCPClient
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Agent系统提示词
BATCH_CONTENT_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家，正在为一款软件系统撰写设计说明文档。

## 你的任务
根据提供的代码知识库信息，一次性批量生成多个设计说明word文档的段落内容。

## 可用工具
你可以使用以下工具获取代码信息：
- get_project_structure: 获取项目目录结构
- search_code_nodes: 根据关键字语义查询代码节点（File, Class, Method）
- search_semantic_nodes: 根据关键字语义查询语义节点（Module, Workflow）
- get_modules: 获取项目的模块列表
- get_module_workflows: 获取模块对应的工作流列表
- get_node_dependencies: 获取节点的依赖关系
- batch_download_flowcharts: 批量下载方法流程图图片（仅用于下载代码流程图）

## 输出格式要求
**非常重要：必须按以下JSON格式输出所有段落内容：**
```json
{
  "paragraphs": [
    {
      "paragraph_id": "段落ID",
      "content": "生成的段落内容",
      "is_heading": true/false
    },
    ...
  ]
}
```

## 生成要求
1. 每个段落内容必须准确，基于代码实际情况
2. 语言专业、简洁、清晰，符合技术文档写作规范
3. 标题内容要精炼，一般不超过20个字
4. **正文内容必须是完整的段落式描述，不要简单的分点简述**
5. **正文内容要详细说明实现原理、处理逻辑、关键步骤等，200字以上**
6. **正文段落首行必须空两格（即段落开头添加两个全角空格"  "）**
7. 生成内容为word文档的内容
8. **重要：生成纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）**

## 格式示例
错误示例（简述）：
- 用户输入验证
- 业务逻辑处理
- 数据持久化存储

正确示例（完整段落）：
  本功能模块主要负责处理用户提交的订单数据。当用户在前端界面提交订单请求后，系统首先会对请求参数进行合法性验证，包括用户身份校验、商品库存检查以及价格计算核对等关键环节。验证通过后，订单数据将被写入数据库，同时触发库存扣减和消息通知等后续业务流程。系统采用事务机制确保数据一致性，并通过异步队列处理非核心业务流程，以提升整体响应性能。

## 工作流程
1. 根据所有段落的提示词确定是否需要调用工具
2. 如果需要则调用工具获取仓库信息
3. 综合分析后批量生成所有段落内容
4. 确保每个段落内容完整且准确
5. 按JSON格式输出所有段落

生成完成后，直接输出JSON格式的最终结果，不需要解释过程。"""

CONTENT_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家，正在为一款软件系统撰写设计说明文档。

## 你的任务
根据提供的代码知识库信息，以及用户提示词生成设计说明word文档的一个标题或者正文段落内容

## 可用工具
你可以使用以下工具获取代码信息：
- get_project_structure: 获取项目目录结构
- search_code_nodes: 根据关键字语义查询代码节点（File, Class, Method）
- search_semantic_nodes: 根据关键字语义查询语义节点（Module, Workflow）
- get_modules: 获取项目的模块列表
- get_module_workflows: 获取模块对应的工作流列表
- get_node_dependencies: 获取节点的依赖关系
- batch_download_flowcharts: 批量下载方法流程图图片（仅用于下载代码流程图）

## 生成要求
1. 内容必须准确，基于代码实际情况
2. 语言专业、简洁、清晰
3. 符合技术文档写作规范
4. 标题内容要精炼，一般不超过20个字
5. **正文内容必须是完整的段落式描述，不要简单的分点简述**
6. **正文内容要详细说明实现原理、处理逻辑、关键步骤等，200字以上**
7. **正文段落首行必须空两格（即段落开头添加两个全角空格"  "）**
8. 生成内容为word文档的内容
9. **重要：生成纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）**

## 格式示例
错误示例（简述）：
- 用户输入验证
- 业务逻辑处理
- 数据持久化存储

正确示例（完整段落）：
  本功能模块主要负责处理用户提交的订单数据。当用户在前端界面提交订单请求后，系统首先会对请求参数进行合法性验证，包括用户身份校验、商品库存检查以及价格计算核对等关键环节。验证通过后，订单数据将被写入数据库，同时触发库存扣减和消息通知等后续业务流程。系统采用事务机制确保数据一致性，并通过异步队列处理非核心业务流程，以提升整体响应性能。

## 工作流程
1. 根据提示词确定是否需要调用工具
2. 如果需要则调用工具获取仓库信息
3. 综合分析后生成文档内容
4. 确保内容完整且准确

生成完成后，直接输出最终内容，不需要解释过程。"""

# 列表生成专用提示词
LIST_GENERATION_SYSTEM_PROMPT = """你是一个专业的技术文档撰写专家。你的任务是根据主题生成一个简洁的标题列表。

## 生成要求
1. 标题列表项应该简洁明了，每个项不超过15个字
2. 标题列表项应该是同一级别的并列关系
3. 直接输出列表，每行一个项目
4. 不要输出编号或解释
5. **重要：生成纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）**

格式示例：
用户管理
订单管理
商品管理
支付系统
消息通知"""

# 图片下载专用提示词
IMAGE_DOWNLOAD_SYSTEM_PROMPT = """你是一个专业的代码流程图获取助手。你的任务是根据文档段落内容和图片搜索提示词，搜索并下载相关的代码流程图。

## 你的任务
1. 分析文档段落内容，理解其描述的功能模块或处理流程
2. 根据图片搜索提示词，搜索相关的方法节点
3. 下载这些方法的流程图图片

## 可用工具
- search_code_nodes: 根据关键字语义查询代码节点（File, Class, Method）
- batch_download_flowcharts: 批量下载方法流程图图片

## 工作流程
1. 分析文档内容，确定需要获取哪些流程图
2. 使用 search_code_nodes 搜索相关的方法节点（node_types 指定为 ["Method"]）
3. 提取搜索结果的 node_id 作为 method_ids
4. 使用 batch_download_flowcharts 批量下载流程图

## 输出要求
完成图片下载后，输出以下格式的结果：
```
已下载图片数量: N
图片详情:
- 图片ID: xxx, 方法名: xxx
...
```

## 注意事项
- 只搜索 Method 类型的节点
- 搜索时 top_k 建议设置为 5
- 如果搜索不到相关方法，请说明原因
- 下载完成后报告成功下载的图片数量"""


class ContentGenerator:
    """内容生成器 - 基于LangChain Agent."""

    def __init__(self, mcp_client: MCPClient, llm_client: Any = None):
        """初始化内容生成器.

        Args:
            mcp_client: MCP客户端实例
            llm_client: 可选的LLM客户端，如果为None则创建默认客户端
        """
        self.mcp_client = mcp_client

        if llm_client:
            self.llm = llm_client
            logger.info("content_generator_initialized", model="custom_llm_client")
        else:
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
        return self.mcp_client.get_available_tools()

    async def generate(
        self,
        paragraph: TemplateParagraph,
        repo_id: str,
    ) -> List[GeneratedContentResult]:
        """生成单个模板段落的内容.

        这是一个可递归的方法，负责生成单个段落模板内容。
        返回 List[GeneratedContentResult]，每个元素代表一个生成结果。

        对于列表段落（is_list=True），返回多个结果（每个列表项一个）。
        对于单一段落（is_list=False），返回单个结果的列表。

        Args:
            paragraph: 模板段落
            repo_id: 仓库ID

        Returns:
            GeneratedContentResult 列表
        """
        logger.info(
            "generate_content_start",
            paragraph_id=paragraph.id,
            is_heading=paragraph.is_heading,
            prompt=paragraph.prompt,
            is_list=paragraph.is_list,
            has_children=len(paragraph.children) > 0,
            has_img=bool(paragraph.img),
        )

        try:
            # 根据段落类型生成内容
            if paragraph.is_list:
                # 列表段落：生成标题列表及其子段落内容，返回多个结果
                return await self._generate_list_with_children(paragraph, repo_id)
            else:
                # 单一段落：生成单个内容，包装为列表返回
                result = await self._generate_single_content(paragraph, repo_id)
                return [result]

        except Exception as e:
            logger.error(
                "generate_content_failed",
                paragraph_id=paragraph.id,
                error=str(e),
            )
            raise

    async def generate_batch(
        self,
        paragraphs: List[TemplateParagraph],
        repo_id: str,
    ) -> Dict[str, GeneratedContentResult]:
        """批量生成多个独立段落的内容.

        将多个独立的非列表段落打包到单次LLM调用中批量生成，
        提高LLM调用利用率，减少调用次数。

        Args:
            paragraphs: 模板段落列表（必须是独立的非列表段落，无children）
            repo_id: 仓库ID

        Returns:
            {段落ID: GeneratedContentResult} 映射

        Raises:
            RuntimeError: 批量生成失败且无法降级时
        """
        if not paragraphs:
            return {}

        logger.info(
            "generate_batch_start",
            paragraph_count=len(paragraphs),
            paragraph_ids=[p.id for p in paragraphs],
            repo_id=repo_id,
        )

        try:
            # 执行批量生成
            results = await self._execute_batch_generation(paragraphs, repo_id)

            logger.info(
                "generate_batch_complete",
                paragraph_count=len(paragraphs),
                result_count=len(results),
            )

            return results

        except Exception as e:
            logger.error(
                "generate_batch_failed",
                paragraph_count=len(paragraphs),
                error=str(e),
            )
            # 降级为逐个生成
            return await self._fallback_to_individual_generation(paragraphs, repo_id)

    async def _execute_batch_generation(
        self,
        paragraphs: List[TemplateParagraph],
        repo_id: str,
    ) -> Dict[str, GeneratedContentResult]:
        """执行批量生成.

        Args:
            paragraphs: 段落列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=BATCH_CONTENT_GENERATION_SYSTEM_PROMPT),
            HumanMessage(content=self._build_batch_task_message(paragraphs, repo_id)),
        ]

        # 执行LLM调用（带工具）
        max_iterations = 15
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

        # 解析最终响应
        final_response = messages[-1]
        raw_content = final_response.content if hasattr(final_response, "content") else str(final_response)

        return self._parse_batch_response(raw_content, paragraphs)

    async def _fallback_to_individual_generation(
        self,
        paragraphs: List[TemplateParagraph],
        repo_id: str,
    ) -> Dict[str, GeneratedContentResult]:
        """降级为逐个生成.

        当批量生成失败时，逐个生成段落作为备用方案。

        Args:
            paragraphs: 段落列表
            repo_id: 仓库ID

        Returns:
            生成结果映射
        """
        logger.warning(
            "fallback_to_individual_generation",
            paragraph_count=len(paragraphs),
        )

        results: Dict[str, GeneratedContentResult] = {}

        for paragraph in paragraphs:
            try:
                result_list = await self.generate(paragraph, repo_id)
                if result_list:
                    results[paragraph.id] = result_list[0]
            except Exception as e:
                logger.error(
                    "individual_generation_failed",
                    paragraph_id=paragraph.id,
                    error=str(e),
                )
                # 创建一个错误结果
                results[paragraph.id] = GeneratedContentResult(
                    is_heading=paragraph.is_heading,
                    content=f"[生成失败: {str(e)}]",
                    children=[],
                    images=[],
                )

        return results

    def _build_batch_task_message(
        self,
        paragraphs: List[TemplateParagraph],
        repo_id: str,
    ) -> str:
        """构建批量生成任务消息.

        Args:
            paragraphs: 段落列表
            repo_id: 仓库ID

        Returns:
            任务消息
        """
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            "## 需要生成的段落列表",
            f"共 {len(paragraphs)} 个段落，请依次为每个段落生成内容。",
            "",
        ]

        for i, paragraph in enumerate(paragraphs, 1):
            type_desc = "标题" if paragraph.is_heading else "正文"
            task_parts.append(f"### 段落{i}")
            task_parts.append(f"- 段落ID: {paragraph.id}")
            task_parts.append(f"- 类型: {type_desc}")
            task_parts.append(f"- 主题: {paragraph.prompt}")

            # 添加长度限制
            length_constraints = []
            if paragraph.min_length:
                length_constraints.append(f"最少{paragraph.min_length}字")
            if paragraph.max_length:
                length_constraints.append(f"最多{paragraph.max_length}字")

            if length_constraints:
                task_parts.append(f"- 字数要求: {', '.join(length_constraints)}")

            # 添加参考示例
            if paragraph.example:
                task_parts.append(f"- 参考示例: {paragraph.example}")

            task_parts.append("")

        task_parts.extend([
            "## 输出要求",
            "请按照以下JSON格式输出所有段落内容：",
            "```json",
            "{",
            '  "paragraphs": [',
        ])

        for paragraph in paragraphs:
            task_parts.extend([
                "    {",
                f'      "paragraph_id": "{paragraph.id}",',
                '      "content": "生成的段落内容",',
                f'      "is_heading": {str(paragraph.is_heading).lower()}',
                "    },",
            ])

        task_parts.extend([
            "  ]",
            "}",
            "```",
            "",
            "## 格式要求",
            "- 使用纯文本格式，不要包含任何Markdown标记",
            "- 正文必须是完整的段落式描述，不要分点简述",
            "- 正文首行必须空两格（添加两个全角空格）",
            "- 标题不要添加数字序号",
            "",
            "请开始生成。你可以使用工具来获取代码信息。",
        ])

        return "\n".join(task_parts)

    def _parse_batch_response(
        self,
        raw_content: str,
        paragraphs: List[TemplateParagraph],
    ) -> Dict[str, GeneratedContentResult]:
        """解析批量生成的响应.

        Args:
            raw_content: 原始响应内容
            paragraphs: 原始段落列表（用于构建默认结果）

        Returns:
            生成结果映射
        """
        results: Dict[str, GeneratedContentResult] = {}

        # 尝试提取JSON内容
        json_content = self._extract_json_from_response(raw_content)

        if json_content:
            try:
                data = json.loads(json_content)
                paragraph_list = data.get("paragraphs", [])

                # 构建段落ID到段落的映射
                paragraph_map = {p.id: p for p in paragraphs}

                for item in paragraph_list:
                    paragraph_id = item.get("paragraph_id")
                    content = item.get("content", "")
                    is_heading = item.get("is_heading", False)

                    if paragraph_id and paragraph_id in paragraph_map:
                        paragraph = paragraph_map[paragraph_id]

                        # 应用长度限制
                        content = self._apply_length_constraints(
                            content,
                            paragraph.min_length,
                            paragraph.max_length,
                        )

                        results[paragraph_id] = GeneratedContentResult(
                            is_heading=is_heading,
                            content=content,
                            children=[],
                            images=[],
                        )

                        logger.info(
                            "batch_paragraph_parsed",
                            paragraph_id=paragraph_id,
                            content_length=len(content),
                        )

            except json.JSONDecodeError as e:
                logger.error("batch_response_json_parse_failed", error=str(e))

        # 为未解析到的段落创建默认结果
        for paragraph in paragraphs:
            if paragraph.id not in results:
                logger.warning(
                    "batch_paragraph_missing",
                    paragraph_id=paragraph.id,
                    fallback_to_default=True,
                )
                results[paragraph.id] = GeneratedContentResult(
                    is_heading=paragraph.is_heading,
                    content=f"[批量生成中段落 '{paragraph.id}' 内容缺失]",
                    children=[],
                    images=[],
                )

        return results

    def _extract_json_from_response(self, raw_content: str) -> Optional[str]:
        """从响应中提取JSON内容.

        Args:
            raw_content: 原始响应

        Returns:
            提取的JSON字符串，如果没有则返回None
        """
        # 尝试直接解析
        raw_content = raw_content.strip()

        # 查找JSON代码块
        if "```json" in raw_content:
            start = raw_content.find("```json") + 7
            end = raw_content.find("```", start)
            if end > start:
                return raw_content[start:end].strip()

        # 查找普通代码块
        if "```" in raw_content:
            start = raw_content.find("```") + 3
            end = raw_content.find("```", start)
            if end > start:
                return raw_content[start:end].strip()

        # 尝试查找JSON对象边界
        json_start = raw_content.find("{")
        json_end = raw_content.rfind("}")
        if json_start >= 0 and json_end > json_start:
            return raw_content[json_start:json_end + 1]

        return None

    async def _generate_list_with_children(
        self,
        paragraph: TemplateParagraph,
        repo_id: str,
    ) -> List[GeneratedContentResult]:
        """生成列表及其子段落内容.

        第1阶段：生成标题列表
        第2阶段：为每个列表项生成子段落内容

        返回列表中每个元素对应一个列表项，包含：
        - is_heading=True（标题）
        - content=列表项标题
        - children=子段落生成的结果列表

        Args:
            paragraph: 模板段落（is_list=True）
            repo_id: 仓库ID

        Returns:
            GeneratedContentResult 列表，每个元素对应一个列表项
        """
        # 阶段1：生成列表
        logger.info(
            "generate_list_phase1",
            paragraph_id=paragraph.id,
            prompt=paragraph.prompt,
        )

        list_items = await self._generate_list_items(paragraph, repo_id)

        logger.info(
            "generate_list_phase1_complete",
            paragraph_id=paragraph.id,
            item_count=len(list_items),
            items=list_items,
        )

        # 阶段2：为每个列表项生成子段落内容
        results: List[GeneratedContentResult] = []

        for i, item in enumerate(list_items):
            logger.info(
                "generate_list_item_start",
                paragraph_id=paragraph.id,
                list_index=i,
                item=item,
            )

            # 收集子段落生成结果
            child_results: List[GeneratedContentResult] = []

            if paragraph.children:
                for child in paragraph.children:
                    if isinstance(child, TemplateParagraph):
                        # 模板子段落：需要生成内容
                        # 使用列表项作为上下文
                        prompt_with_context = f"关于'{item}'，{child.prompt}"

                        # 创建临时段落用于生成
                        temp_paragraph = TemplateParagraph(
                            id=f"{child.id}_item_{i}",
                            is_template=True,
                            text=child.text,
                            style_name=child.style_name,
                            is_heading=child.is_heading,
                            prompt=prompt_with_context,
                            is_list=child.is_list,
                            min_length=child.min_length,
                            max_length=child.max_length,
                            children=child.children,
                            img=child.img,
                        )

                        try:
                            # 递归生成（如果子段落也是列表，会继续递归）
                            # 返回的是列表，需要展开
                            child_result_list = await self.generate(temp_paragraph, repo_id)
                            child_results.extend(child_result_list)

                            content_count = len(child_result_list)
                            image_count = sum(len(r.images) for r in child_result_list)
                            logger.info(
                                "generate_child_content_success",
                                paragraph_id=paragraph.id,
                                list_index=i,
                                child_id=child.id,
                                result_count=content_count,
                                image_count=image_count,
                            )
                        except Exception as e:
                            logger.warning(
                                "generate_child_content_failed",
                                paragraph_id=paragraph.id,
                                list_index=i,
                                child_id=child.id,
                                error=str(e),
                            )
                    elif isinstance(child, StaticParagraph):
                        # 静态子段落：直接创建结果对象，保留原始样式
                        # 但需要递归处理其 children（可能包含模板段落）
                        static_children_results: List[GeneratedContentResult] = []

                        # 处理 StaticParagraph 的 children
                        if child.children:
                            for static_child in child.children:
                                if isinstance(static_child, TemplateParagraph):
                                    # 模板子段落需要生成内容
                                    try:
                                        # 使用列表项作为上下文
                                        prompt_with_context = f"关于'{item}'，{static_child.prompt}"
                                        temp_paragraph = TemplateParagraph(
                                            id=f"{static_child.id}_item_{i}",
                                            is_template=True,
                                            text=static_child.text,
                                            style_name=static_child.style_name,
                                            is_heading=static_child.is_heading,
                                            prompt=prompt_with_context,
                                            is_list=static_child.is_list,
                                            min_length=static_child.min_length,
                                            max_length=static_child.max_length,
                                            children=static_child.children,
                                            img=static_child.img,
                                        )
                                        static_child_results = await self.generate(temp_paragraph, repo_id)
                                        static_children_results.extend(static_child_results)
                                    except Exception as e:
                                        logger.warning(
                                            "generate_static_child_content_failed",
                                            paragraph_id=paragraph.id,
                                            list_index=i,
                                            static_child_id=static_child.id,
                                            error=str(e),
                                        )
                                elif isinstance(static_child, StaticParagraph):
                                    # 嵌套的静态段落
                                    nested_static_result = GeneratedContentResult(
                                        is_heading=static_child.is_heading,
                                        content=static_child.content,
                                        children=[],
                                        images=[],
                                        style_name=static_child.style_name,
                                    )
                                    static_children_results.append(nested_static_result)

                        static_result = GeneratedContentResult(
                            is_heading=child.is_heading,
                            content=child.content,
                            children=static_children_results,
                            images=[],
                            style_name=child.style_name,
                        )
                        child_results.append(static_result)

            # 创建列表项的结果（标题项）
            item_result = GeneratedContentResult(
                is_heading=True,  # 列表项是标题
                content=item,
                children=child_results,
                images=[],  # 列表项本身没有图片
                style_name=paragraph.style_name,  # 保留原始段落样式
            )
            results.append(item_result)

            logger.info(
                "generate_list_item_complete",
                paragraph_id=paragraph.id,
                list_index=i,
                item=item,
                child_count=len(child_results),
            )

        logger.info(
            "generate_list_complete",
            paragraph_id=paragraph.id,
            item_count=len(results),
        )

        return results

    async def _generate_single_content(
        self,
        paragraph: TemplateParagraph,
        repo_id: str,
    ) -> GeneratedContentResult:
        """生成单个内容并处理图片下载.

        只有正文段落（is_heading=False）才可能有 img 属性，需要下载图片。
        标题段落（is_heading=True）不需要下载图片。

        Args:
            paragraph: 模板段落
            repo_id: 仓库ID

        Returns:
            GeneratedContentResult，包含生成的内容和图片（如果有）
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=CONTENT_GENERATION_SYSTEM_PROMPT),
        ]

        type_desc = "标题" if paragraph.is_heading else "正文"
        task_msg = self._build_task_message(paragraph, repo_id, type_desc)
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

        content = self._apply_length_constraints(
            raw_content, paragraph.min_length, paragraph.max_length
        )

        # 下载图片（只有正文段落才可能有 img 属性）
        images = []
        if paragraph.img:
            # 结合 img 属性和生成的正文内容，使用 Agent 方式下载图片
            images = await self._download_images_with_agent(
                img_prompt=paragraph.img,
                generated_content=content,
                repo_id=repo_id,
            )
            if images:
                logger.info(
                    "images_downloaded_for_paragraph",
                    paragraph_id=paragraph.id,
                    image_count=len(images),
                )

        return GeneratedContentResult(
            is_heading=paragraph.is_heading,
            content=content,
            children=[],  # 单一段落没有子段落
            images=images,
        )

    async def _download_images_with_agent(
        self,
        img_prompt: str,
        generated_content: str,
        repo_id: str,
    ) -> List[ImageInfo]:
        """使用 Agent 方式下载图片.

        Agent 会根据文档内容和图片搜索提示词，自行调用工具搜索和下载流程图。

        Args:
            img_prompt: 图片搜索提示词（模板段落的 img 属性）
            generated_content: 生成的文档正文内容
            repo_id: 仓库ID

        Returns:
            图片信息列表（包含临时文件路径）
        """
        logger.info(
            "download_images_with_agent_start",
            img_prompt=img_prompt,
            repo_id=repo_id,
            content_length=len(generated_content),
        )

        # 创建临时目录
        temp_dir = Path(get_settings().temp_dir) / "flowcharts" / repo_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 构建完整的任务提示词
        task_message = self._build_image_download_task_message(
            img_prompt=img_prompt,
            generated_content=generated_content,
            repo_id=repo_id,
        )

        # 加载工具并创建 Agent
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=IMAGE_DOWNLOAD_SYSTEM_PROMPT),
            HumanMessage(content=task_message),
        ]

        # 运行 Agent，最多 15 轮迭代（图片下载可能需要更多步骤）
        max_iterations = 15
        method_ids = []

        for i in range(max_iterations):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    # 确保 repo_id 存在
                    if "repo_id" not in tool_args:
                        tool_args["repo_id"] = repo_id

                    try:
                        result = await self.mcp_client.call_tool(tool_name, tool_args)

                        # 如果是搜索工具，尝试提取 method_ids
                        if tool_name == "search_code_nodes":
                            method_ids = self._extract_method_ids_from_search_result(result)
                            logger.info(
                                "agent_search_code_nodes",
                                method_count=len(method_ids),
                                method_ids=method_ids,
                            )

                        # 截断过长的结果
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
                # Agent 完成思考，没有更多工具调用
                break

        # 如果 Agent 没有搜索到方法，尝试直接使用 img_prompt 搜索
        if not method_ids:
            logger.info(
                "agent_no_method_ids_found, fallback to direct search",
                img_prompt=img_prompt,
            )
            method_ids = await self._search_methods_directly(img_prompt, repo_id)

        if not method_ids:
            logger.info("no_methods_found_for_download", img_prompt=img_prompt)
            return []

        # 下载流程图
        return await self._download_flowcharts(method_ids, temp_dir)

    def _build_image_download_task_message(
        self,
        img_prompt: str,
        generated_content: str,
        repo_id: str,
    ) -> str:
        """构建图片下载的任务提示词.

        结合 img_prompt 和 generated_content 生成完整的提示词。

        Args:
            img_prompt: 图片搜索提示词
            generated_content: 生成的文档正文内容
            repo_id: 仓库ID

        Returns:
            完整的任务提示词
        """
        # 截取正文内容的前 500 字，避免提示词过长
        content_summary = generated_content[:500] if len(generated_content) > 500 else generated_content

        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            "## 文档段落内容",
            content_summary,
            "",
            "## 图片搜索提示词",
            img_prompt,
            "",
            "## 任务",
            "请根据上述文档内容和图片搜索提示词，完成以下任务：",
            "1. 分析文档段落描述的功能模块或处理流程",
            "2. 使用 search_code_nodes 工具搜索相关的方法节点",
            "   - query 参数结合图片搜索提示词和文档内容关键词",
            "   - node_types 必须包含 [\"Method\"]",
            "   - top_k 建议设置为 5",
            "3. 从搜索结果中提取 Method 类型的 node_id",
            "4. 使用 batch_download_flowcharts 工具批量下载这些方法的流程图",
            "",
            "## 注意事项",
            "- 优先搜索与文档内容最相关的核心方法",
            "- 如果搜索不到相关方法，请说明原因",
            "- 下载完成后报告成功下载的图片数量",
            "",
            "请开始执行图片下载任务。",
        ]

        return "\n".join(task_parts)

    def _extract_method_ids_from_search_result(self, search_result: str) -> List[str]:
        """从搜索结果中提取 Method 类型的 node_id.

        Args:
            search_result: 搜索结果字符串

        Returns:
            method_id 列表
        """
        try:
            search_data = json.loads(search_result)
            results = search_data.get("results", [])
        except json.JSONDecodeError:
            try:
                import ast
                search_data = ast.literal_eval(search_result)
                if isinstance(search_data, dict):
                    results = search_data.get("results", [])
                else:
                    return []
            except (ValueError, SyntaxError):
                return []

        method_ids = []
        for result in results:
            if result.get("type") == "Method":
                node_id = result.get("node_id")
                if node_id:
                    method_ids.append(node_id)

        return method_ids

    async def _search_methods_directly(self, img_prompt: str, repo_id: str) -> List[str]:
        """直接使用 img_prompt 搜索方法（备用方案）.

        Args:
            img_prompt: 图片搜索提示词
            repo_id: 仓库ID

        Returns:
            method_id 列表
        """
        try:
            search_result = await self.mcp_client.call_tool(
                "search_code_nodes",
                {"repo_id": repo_id, "query": img_prompt, "node_types": ["Method"], "top_k": 5}
            )
            return self._extract_method_ids_from_search_result(search_result)
        except Exception as e:
            logger.warning("direct_search_failed", error=str(e))
            return []

    async def _download_flowcharts(
        self,
        method_ids: List[str],
        temp_dir: Path,
    ) -> List[ImageInfo]:
        """下载流程图并保存到临时目录.

        Args:
            method_ids: 方法ID列表
            temp_dir: 临时目录路径

        Returns:
            图片信息列表
        """
        logger.info(
            "downloading_flowcharts",
            method_count=len(method_ids),
            method_ids=method_ids,
        )

        try:
            download_result = await self.mcp_client.call_tool(
                "batch_download_flowcharts",
                {"method_ids": method_ids}
            )

            # 解析下载结果
            try:
                download_data = json.loads(download_result)
                images_data = download_data.get("images", [])
            except json.JSONDecodeError:
                try:
                    import ast
                    download_data = ast.literal_eval(download_result)
                    if isinstance(download_data, dict):
                        images_data = download_data.get("images", [])
                    else:
                        logger.warning("download_result_not_dict", result=download_result)
                        return []
                except (ValueError, SyntaxError) as e:
                    logger.warning("download_result_parse_failed", result=download_result, error=str(e))
                    return []

            # 提取成功的图片并保存到临时目录
            images = []
            for img_data in images_data:
                if img_data.get("success"):
                    try:
                        image_base64 = img_data.get("image_data", "")
                        image_bytes = base64.b64decode(image_base64)
                        image_format = img_data.get("image_format", "png")
                        method_id = img_data.get("method_id", "")
                        method_name = img_data.get("method_name", "")
                        image_id = img_data.get("image_id") or str(uuid.uuid4())

                        # 保存到临时文件
                        image_filename = f"{image_id}.{image_format}"
                        image_path = temp_dir / image_filename
                        with open(image_path, "wb") as f:
                            f.write(image_bytes)

                        image_info = ImageInfo(
                            image_id=image_id,
                            image_path=str(image_path),
                            image_format=image_format,
                            method_id=method_id,
                            method_name=method_name,
                        )
                        images.append(image_info)

                        logger.info(
                            "image_saved_to_temp",
                            image_id=image_id,
                            image_path=str(image_path),
                            method_name=method_name,
                        )
                    except Exception as e:
                        logger.warning(
                            "image_save_failed",
                            method_id=img_data.get("method_id"),
                            error=str(e),
                        )

            logger.info(
                "download_flowcharts_complete",
                requested=len(method_ids),
                downloaded=len(images),
                temp_dir=str(temp_dir),
            )

            return images

        except Exception as e:
            logger.error("download_flowcharts_failed", error=str(e))
            return []

    async def _generate_list_items(
        self,
        paragraph: TemplateParagraph,
        repo_id: str,
    ) -> List[str]:
        """生成列表项.

        Args:
            paragraph: 模板段落
            repo_id: 仓库ID

        Returns:
            列表项字符串列表
        """
        tools = await self._load_langchain_tools()
        llm_with_tools = self.llm.bind_tools(tools)

        messages = [
            SystemMessage(content=LIST_GENERATION_SYSTEM_PROMPT),
            HumanMessage(content=self._build_list_task_message(paragraph, repo_id)),
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
        """应用长度限制.

        注意：此方法不再粗暴截断内容，而是依赖LLM在生成时遵循字数要求。
        如果需要强制限制，应通过提示词要求LLM精炼内容。
        """
        if max_length and len(content) > max_length * 1.2:
            logger.warning(
                "content_exceeds_max_length",
                actual_length=len(content),
                max_length=max_length,
            )

        return content

    def _build_task_message(self, paragraph: TemplateParagraph, repo_id: str, type_desc: str) -> str:
        """构建任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            f"请根据以下主题生成{type_desc}内容:",
            f"主题: {paragraph.prompt}",
        ]

        length_constraints = []
        if paragraph.min_length:
            length_constraints.append(f"最少{paragraph.min_length}字")
        if paragraph.max_length:
            length_constraints.append(f"最多{paragraph.max_length}字")

        if length_constraints:
            task_parts.append(f"\n字数要求: {', '.join(length_constraints)}")
            if paragraph.max_length:
                task_parts.append(f"\n重要：如果内容超出字数限制，请精炼信息而非简单截断。")

        # 添加参考示例（如果存在）
        if paragraph.example:
            task_parts.extend([
                "\n参考示例:",
                paragraph.example,
            ])

        task_parts.append("\n请生成一段完整的内容。")
        task_parts.extend([
            "\n格式要求：",
            "- 使用纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）",
            "- 直接输出内容，不要使用代码块包裹",
        ])

        if paragraph.is_heading:
            task_parts.append("- 标题应为纯文本，不要添加数字序号（如1. 2. 3.）")
        else:
            task_parts.extend([
                "- 正文必须是完整的段落式描述，不要分点简述",
                "- 正文首行必须空两格（添加两个全角空格）",
                "- 正文要详细说明实现原理、处理逻辑、关键步骤等",
            ])

        task_parts.append("\n请开始生成。你可以使用工具来获取代码信息。")

        return "\n".join(task_parts)

    def _build_list_task_message(self, paragraph: TemplateParagraph, repo_id: str) -> str:
        """构建列表生成任务消息."""
        task_parts = [
            f"仓库ID: {repo_id}",
            "",
            f"请根据以下主题生成一个简洁的标题列表:",
            f"主题: {paragraph.prompt}",
            "",
            "要求：",
            "1. 列表项应该简洁明了，每个项不超过15个字",
            "2. 列表项应该是同一级别的并列关系",
            "3. 直接输出列表，每行一个项目",
            "4. 不要输出编号或解释",
            "5. 使用纯文本格式，不要包含任何Markdown标记（如#、##、**、-、*等）",
            "",
            "请开始生成。你可以使用工具来获取代码信息。",
        ]

        return "\n".join(task_parts)
