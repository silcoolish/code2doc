"""LLM 服务层 - 业务相关操作.

该模块包含与业务相关的 LLM 操作，如代码摘要生成、模块检测等。
底层 LLM 连接由 infrastructure/llm/client.py 中的 LLMClient 提供。
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.infrastructure.llm import LLMClient

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务 - 业务层封装，依赖 LLMClient 进行底层操作."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.settings = get_settings()
        self._client = llm_client or LLMClient()

    def get_context_window(self) -> int:
        """获取当前缓存的上下文窗口大小.

        委托给 LLMClient 实现。

        Returns:
            有效的上下文窗口大小
        """
        return self._client.get_context_window()

    def get_context_window_or_default(self, default: int = 100000) -> int:
        """获取上下文窗口，如未初始化则返回默认值.

        委托给 LLMClient 实现。

        Args:
            default: 未初始化时的默认值

        Returns:
            上下文窗口大小或默认值
        """
        return self._client.get_context_window_or_default(default)

    async def generate_summary(
        self,
        code: str,
        docstring: str = "",
        callee_summaries: Optional[List[str]] = None,
        node_type: str = "method",
        language: str = "python",
    ) -> str:
        """生成代码摘要.

        Args:
            code: 代码片段
            docstring: 文档字符串
            callee_summaries: 被调用者的摘要（用于方法）
            node_type: 节点类型
            language: 编程语言

        Returns:
            生成的摘要
        """
        prompt = self._build_summary_prompt(
            code=code,
            docstring=docstring,
            callee_summaries=callee_summaries,
            node_type=node_type,
            language=language,
        )

        summary = await self._client.complete(
            prompt=prompt,
            system_prompt="你是代码分析专家。请为代码生成简洁、信息丰富的摘要。",
            max_tokens=1024,
            temperature=0.3,
        )

        return summary.strip()

    async def generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """批量生成嵌入向量.

        Args:
            texts: 文本列表
            batch_size: 批处理大小

        Returns:
            嵌入向量列表
        """
        # DashScope API 限制 batch size 不能超过 10
        provider_name = self.settings.embedding_provider or self.settings.llm_provider
        if provider_name.lower() == "qwen":
            batch_size = min(batch_size, 10)

        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # 重试逻辑
            for attempt in range(self.settings.max_retries):
                try:
                    embeddings = await self._client.embed(batch)
                    results.extend(embeddings)
                    break
                except Exception as e:
                    if attempt == self.settings.max_retries - 1:
                        raise
                    wait_time = (2 ** attempt) * self.settings.retry_delay
                    logger.warning(f"Embedding failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)

        return results

    async def detect_modules(
        self,
        structure_json: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检测功能模块.

        Args:
            structure_json: 代码结构 JSON

        Returns:
            模块列表
        """
        prompt = f"""
        分析以下代码仓库结构，识别功能模块和业务流程。

        仓库结构:
        ```json
        {json.dumps(structure_json, indent=2, ensure_ascii=False)}
        ```

        请识别:
        1. 高层功能模块 (例如: "用户认证", "数据库操作", "API接口")
        2. 每个模块内的业务工作流 (例如: "用户登录流程", "数据同步流程")

        请用中文返回分析结果，JSON格式如下:
        {{
            "modules": [
                {{
                    "name": "模块名称(中文)",
                    "description": "该模块的简述(中文，50字以内)",
                    "detail": "该模块的详细说明(中文，200-500字，包含功能描述、职责、关键逻辑等)",
                    "files": ["file1.py", "file2.py"],
                    "workflows": [
                        {{
                            "name": "工作流名称(中文)",
                            "description": "该工作流的简述(中文，50字以内)",
                            "detail": "该工作流的详细说明(中文，200-500字，包含流程描述、处理步骤、关键逻辑等)",
                            "files": ["file1.py"]
                        }}
                    ]
                }}
            ]
        }}

        注意:
        - name、description、detail 字段必须使用中文
        - description 是简要描述，用于快速了解功能
        - detail 是详细说明，包含更多技术细节和实现逻辑
        """

        response = await self._client.complete(
            prompt=prompt,
            system_prompt="你是软件架构专家。分析代码结构并识别功能模块，所有描述必须使用中文。",
            max_tokens=4096,
            temperature=0.2,
        )

        # 解析 JSON 响应
        try:
            # 尝试提取 JSON
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            else:
                json_str = response

            result = json.loads(json_str.strip())
            return result.get("modules", [])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse module detection response: {e}")
            return []

    def _calculate_batch_size(
        self,
        items: List[Dict[str, Any]],
        context_window: int,
    ) -> int:
        """根据代码总大小和上下文窗口计算每批节点数量.

        策略：
        1. 估算每个节点的 token 数（字符数 / 4）
        2. 每批输入 + 预留输出空间不超过上下文限制
        3. 每批最少 5 个，最多 50 个节点

        Args:
            items: 节点列表
            context_window: 当前模型的有效上下文窗口（已预留输出空间）
        """
        total_chars = sum(len(item.get("code", "")) for item in items)
        estimated_input_tokens = total_chars / 4

        # 预留输出空间（每个 summary 约 150 tokens，与 _generate_batch 保持一致）
        estimated_output_per_item = 150

        if estimated_input_tokens <= context_window * 0.7:  # 如果总量不大，一次处理
            return len(items)

        # 动态计算每批数量
        avg_input_tokens = estimated_input_tokens / len(items)
        # 每批 = 输入 tokens + 输出 tokens <= context_window
        batch_size = int(context_window / (avg_input_tokens + estimated_output_per_item))

        return max(5, min(batch_size, 50))  # 限制在 5-50 之间

    def _build_enhanced_summary_prompt(
        self,
        items: List[Any],
    ) -> str:
        """构建增强型摘要Prompt - 区分已处理summary和批次内源码.

        Args:
            items: MethodAnalysisItem 列表

        Returns:
            构建的提示词
        """
        parts = [
            "你是一个代码分析专家。请为以下方法生成中文摘要。",
            "",
            "每个方法的输入包含：",
            "- 方法自身的代码和文档",
            "- 【已处理方法】的摘要（语义提炼，高价值）",
            "- 【批次内待处理方法】的源码（详细实现）",
            "",
            "请综合这些信息，生成准确、简洁的1-2句中文摘要，描述：",
            "- 这段代码的功能",
            "- 主要用途或目的",
            "",
            "返回格式：",
            "```json",
            '{"summaries": [{"id": "method_id", "summary": "摘要内容"}, ...]}',
            "```",
            "",
            f"共 {len(items)} 个方法：",
            "=" * 50,
            "",
        ]

        for i, item in enumerate(items, 1):
            parts.append(f"[{i}] 方法: {item.name}")
            parts.append(f"ID: {item.id}")
            parts.append(f"语言: {item.language}")
            parts.append("")

            # 1. 已处理依赖 - 使用summary（最精炼）
            if item.external_callees:
                parts.append("  【已处理依赖 - 摘要参考】:")
                for callee in item.external_callees[:3]:  # 限制数量
                    summary = callee.get("summary", "")[:100]
                    parts.append(f"    - {callee.get('name', 'unknown')}: {summary}...")
                parts.append("")

            # 2. 批次内依赖 - 使用源码（详细）
            if item.internal_callees:
                parts.append("  【批次内依赖 - 源码参考】:")
                for callee in item.internal_callees:
                    parts.append(f"    - {callee.get('name', 'unknown')}:")
                    code = callee.get("code", "")[:800]
                    parts.append(f"      ```{item.language}")
                    for line in code.split("\n"):
                        parts.append(f"      {line}")
                    parts.append("      ```")
                parts.append("")

            # 3. 提示有未包含的依赖
            if item.pending_callees:
                parts.append(f"  （注：还有 {len(item.pending_callees)} 个依赖方法未处理）")
                parts.append("")

            # 4. 自身代码
            if item.docstring:
                parts.append(f"  文档注释: {item.docstring}")
            parts.append("  代码:")
            parts.append(f"  ```{item.language}")
            code_lines = item.code.split("\n")
            for line in code_lines:
                parts.append(f"  {line}")
            parts.append("  ```")
            parts.append("")
            parts.append("-" * 40)
            parts.append("")

        parts.append("请生成JSON格式的摘要结果：")
        return "\n".join(parts)

    def _build_batch_summary_prompt(
        self,
        items: List[Dict[str, Any]],
        node_type: str = "method",
    ) -> str:
        """构建批量摘要生成提示词."""
        parts = [
            f"你是一个代码分析专家。请为以下多个 {node_type} 生成中文摘要。",
            "",
            f"对于每个代码片段，请生成 1-2 句话的中文描述，说明：",
            "- 这段代码的功能",
            "- 主要用途或目的",
            "",
            "请按以下 JSON 格式返回，确保 ID 与输入顺序一致：",
            "{\n"
            '  "summaries": [\n'
            '    {"id": "node_id_1", "summary": "摘要内容"},\n'
            '    {"id": "node_id_2", "summary": "摘要内容"},\n'
            "    ...\n"
            "  ]\n"
            "}",
            "",
        ]

        for i, item in enumerate(items, 1):
            node_id = item.get("id", "")
            code = item.get("code", "")[:3000]  # 限制代码长度
            docstring = item.get("docstring", "")
            language = item.get("language", "python")
            name = item.get("name", "")
            callee_summaries = item.get("callee_summaries", [])

            parts.append(f"=== 代码片段 {i} [ID: {node_id}] ===")
            parts.append(f"名称: {name}")
            parts.append(f"语言: {language}")

            if docstring:
                parts.append(f"文档注释: {docstring}")

            if callee_summaries:
                parts.append("调用的函数摘要:")
                for j, summary in enumerate(callee_summaries[:3], 1):
                    parts.append(f"  {j}. {summary}")

            parts.append("代码:")
            parts.append("```")
            parts.append(code)
            parts.append("```")
            parts.append("")

        parts.append("请返回 JSON 格式的摘要结果：")
        return "\n".join(parts)

    def _parse_batch_response(
        self,
        response: str,
        expected_ids: List[str],
    ) -> Dict[str, str]:
        """解析批量生成的响应.

        处理以下情况：
        1. 正常 JSON 返回
        2. JSON 格式损坏（尝试修复）
        3. 缺少某些 ID（返回空字符串）

        Args:
            response: LLM 响应内容
            expected_ids: 期望的节点 ID 列表

        Returns:
            节点 ID 到摘要的映射字典
        """
        result = {node_id: "" for node_id in expected_ids}

        # 提取 JSON 内容
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        try:
            data = json.loads(json_str.strip())
            summaries = data.get("summaries", [])

            for item in summaries:
                node_id = item.get("id", "")
                summary = item.get("summary", "").strip()
                if node_id in result:
                    result[node_id] = summary

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse batch response as JSON: {e}")
            # 尝试用正则提取
            import re
            pattern = r'"id"\s*:\s*"([^"]+)"\s*,\s*"summary"\s*:\s*"([^"]*)"'
            matches = re.findall(pattern, response)
            for node_id, summary in matches:
                if node_id in result:
                    result[node_id] = summary.strip()

        return result

    async def generate_summaries_batch(
        self,
        items: List[Dict[str, Any]],
        node_type: str = "method",
    ) -> List[str]:
        """批量生成代码摘要.

        使用启动时已获取的上下文窗口计算最优批次大小。

        Args:
            items: 节点列表，每个包含 id, code, docstring, name, language 等字段
            node_type: 节点类型 (method/class/file)

        Returns:
            生成的摘要列表，与 items 一一对应
        """
        if not items:
            return []

        # 获取上下文窗口（已在服务启动时初始化）
        context_window = self.get_context_window_or_default(default=100000)

        # 计算批次大小
        batch_size = self._calculate_batch_size(items, context_window)

        logger.info(
            f"Batch generating summaries for {len(items)} {node_type}s, "
            f"batch_size={batch_size}, context_window={context_window}"
        )

        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_summaries = await self._generate_batch(batch, node_type)
            results.extend(batch_summaries)

        return results

    async def _generate_batch(
        self,
        items: List[Dict[str, Any]],
        node_type: str,
    ) -> List[str]:
        """生成一批节点的摘要.

        Args:
            items: 一批节点数据
            node_type: 节点类型

        Returns:
            摘要列表
        """
        if not items:
            return []

        expected_ids = [item.get("id", "") for item in items]

        # 动态计算 max_tokens：每个摘要约150 tokens + 缓冲区
        estimated_output_tokens = len(items) * 150 + 500
        max_tokens = max(estimated_output_tokens, 2048)  # 至少2048

        try:
            prompt = self._build_batch_summary_prompt(items, node_type)

            response = await self._client.complete(
                prompt=prompt,
                system_prompt=(
                    "你是代码分析专家。请为代码生成简洁、信息丰富的中文摘要。"
                    "以有效的 JSON 格式返回结果。"
                ),
                max_tokens=max_tokens,
                temperature=0.3,
            )

            # 解析响应
            summaries_map = self._parse_batch_response(response, expected_ids)

            # 按输入顺序返回摘要
            return [summaries_map.get(node_id, "") for node_id in expected_ids]

        except Exception as e:
            logger.error(f"Failed to generate batch summaries: {e}")
            raise

    async def generate_method_summaries_enhanced(
        self,
        items: List[Any],
    ) -> List[str]:
        """使用增强依赖上下文生成方法摘要.

        支持批次内依赖消解：已处理方法使用summary，批次内待处理方法使用源码。

        Args:
            items: MethodAnalysisItem 列表

        Returns:
            生成的摘要列表，与 items 一一对应
        """
        if not items:
            return []

        expected_ids = [item.id for item in items]

        # 动态计算 max_tokens：每个摘要约150 tokens + 缓冲区
        estimated_output_tokens = len(items) * 150 + 500
        max_tokens = max(estimated_output_tokens, 2048)  # 至少2048

        try:
            prompt = self._build_enhanced_summary_prompt(items)

            response = await self._client.complete(
                prompt=prompt,
                system_prompt=(
                    "你是代码分析专家。请为代码生成简洁、信息丰富的中文摘要。"
                    "综合考虑外部依赖（摘要）和内部依赖（源代码）以获得准确的上下文。"
                    "以有效的 JSON 格式返回结果。"
                ),
                max_tokens=max_tokens,
                temperature=0.3,
            )

            # 解析响应
            summaries_map = self._parse_batch_response(response, expected_ids)

            # 按输入顺序返回摘要
            return [summaries_map.get(node_id, "") for node_id in expected_ids]

        except Exception as e:
            logger.error(f"Failed to generate enhanced summaries: {e}")
            raise

    def _build_summary_prompt(
        self,
        code: str,
        docstring: str = "",
        callee_summaries: Optional[List[str]] = None,
        node_type: str = "method",
        language: str = "python",
    ) -> str:
        """构建摘要生成提示词."""
        parts = [
            f"请为以下 {language} {node_type} 生成中文摘要。",
            "",
            "代码:",
            "```",
            code[:3000],  # 限制代码长度
            "```",
        ]

        if docstring:
            parts.extend([
                "",
                "文档注释:",
                docstring,
            ])

        if callee_summaries:
            parts.extend([
                "",
                "此代码调用了以下函数（及其摘要）:",
            ])
            for i, summary in enumerate(callee_summaries[:5], 1):  # 限制数量
                parts.append(f"{i}. {summary}")

        parts.extend([
            "",
            "请用 1-2 句话的中文描述以下内容:",
            "- 这段代码的功能",
            "- 主要用途或目的",
            "",
            "摘要（中文）:",
        ])

        return "\n".join(parts)

    # ==================== 模块检测相关方法 ====================

    async def detect_modules_in_cluster(
        self,
        structure_json: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """检测代码簇内的功能模块.

        Args:
            structure_json: 簇的结构JSON，包含文件信息、依赖关系等

        Returns:
            模块列表，每个模块包含name, description, detail, files, confidence, workflows等字段
        """
        prompt = self._build_cluster_detection_prompt(structure_json)

        response = await self._client.complete(
            prompt=prompt,
            system_prompt="你是软件架构专家。分析代码结构并识别功能模块，所有描述必须使用中文。",
            temperature=0.3,
        )

        return self._parse_cluster_detection_response(response)

    def _build_cluster_detection_prompt(self, structure_json: Dict[str, Any]) -> str:
        """构建簇检测Prompt.

        Args:
            structure_json: 结构JSON

        Returns:
            Prompt字符串
        """
        return f"""分析以下代码簇的结构，识别功能模块和业务流程。

簇信息:
- ID: {structure_json['cluster_id']}
- 目录前缀: {structure_json['directory_prefix']}
- 文件数: {structure_json['file_count']}

文件列表（含摘要和关键类/方法）:
```json
{json.dumps(structure_json['files'], indent=2, ensure_ascii=False)}
```

内部依赖关系:
```json
{json.dumps(structure_json['internal_dependencies'], indent=2, ensure_ascii=False)}
```

外部依赖摘要:
{structure_json['external_dependency_summary']}

请识别:
1. 该簇包含的功能模块（1-3个）
2. 每个模块的核心职责
3. 模块内的工作流程/业务流程
4. 模块间的关系（基于依赖图）

返回JSON格式:
{{
    "modules": [
        {{
            "name": "模块名称(中文)",
            "description": "简述(50字以内)",
            "detail": "详细说明(200-500字)",
            "files": ["file_id_1", "file_id_2"],
            "confidence": 0.85,
            "workflows": [
                {{
                    "name": "工作流名称(中文)",
                    "description": "简述(50字以内)",
                    "files": ["file_id_1"]
                }}
            ]
        }}
    ],
    "cross_module_dependencies": [
        {{"from": "模块A", "to": "模块B", "type": "调用/数据流"}}
    ]
}}

注意:
- name、description、detail 字段必须使用中文
- files 应该包含相关的文件ID（不是路径）
- confidence 是置信度 (0-1)
"""

    def _parse_cluster_detection_response(self, response: str) -> List[Dict[str, Any]]:
        """解析簇检测结果.

        Args:
            response: LLM响应

        Returns:
            模块信息列表
        """
        # 提取JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str.strip())
            return data.get("modules", [])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse cluster detection response as JSON")
            return []

    async def detect_module_workflows(
        self,
        module_name: str,
        module_description: str,
        module_file_count: int,
        call_chains: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """检测模块的工作流.

        Args:
            module_name: 模块名称
            module_description: 模块描述
            module_file_count: 模块内文件数量
            call_chains: 方法调用链列表

        Returns:
            工作流列表，每个工作流包含name, description, entry_points, key_files等字段
        """
        prompt = self._build_workflow_detection_prompt(
            module_name=module_name,
            module_description=module_description,
            module_file_count=module_file_count,
            call_chains=call_chains,
        )

        try:
            response = await self._client.complete(
                prompt=prompt,
                system_prompt="你是业务流程分析专家。基于方法调用链识别业务流程，所有描述必须使用中文。",
                temperature=0.3,
            )

            return self._parse_workflow_response(response)

        except Exception as e:
            logger.warning(f"Failed to detect workflows for {module_name}: {e}")
            return []

    def _build_workflow_detection_prompt(
        self,
        module_name: str,
        module_description: str,
        module_file_count: int,
        call_chains: List[Dict[str, Any]],
    ) -> str:
        """构建工作流检测Prompt.

        Args:
            module_name: 模块名称
            module_description: 模块描述
            module_file_count: 模块内文件数量
            call_chains: 方法调用链

        Returns:
            Prompt字符串
        """
        return f"""分析以下模块的方法调用关系，识别核心业务流程。

模块名称: {module_name}
模块描述: {module_description}
文件数量: {module_file_count}

方法调用链:
```json
{json.dumps(call_chains[:20], indent=2, ensure_ascii=False)}
```

请识别:
1. 该模块的核心业务流程（1-3个）
2. 每个流程的入口点和关键步骤
3. 流程涉及的主要文件

返回JSON格式:
{{
    "workflows": [
        {{
            "name": "流程名称(中文)",
            "description": "流程描述(50字以内)",
            "entry_points": ["方法名1", "方法名2"],
            "key_files": ["file_id_1", "file_id_2"]
        }}
    ]
}}
"""

    def _parse_workflow_response(self, response: str) -> List[Dict[str, Any]]:
        """解析工作流响应.

        Args:
            response: LLM响应

        Returns:
            工作流列表
        """
        # 提取JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse workflow response as JSON")
            return []

        return data.get("workflows", [])


# 全局服务实例
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """获取 LLM 服务实例."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
