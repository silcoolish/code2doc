"""提示词管理模块.

从独立的 markdown 文件中加载系统提示词，实现代码与提示词的解耦。
"""

from pathlib import Path


def _load_prompt(filename: str) -> str:
    """从文件加载提示词内容.

    Args:
        filename: 提示词文件名（不含扩展名）

    Returns:
        提示词内容

    Raises:
        FileNotFoundError: 如果提示词文件不存在
    """
    prompt_path = Path(__file__).parent / f"{filename}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")

    # 移除开头的标题行（如"# 批量内容生成系统提示词\n\n"）
    lines = content.split("\n")
    if lines and lines[0].startswith("# "):
        content = "\n".join(lines[1:]).strip()

    return content


# 知识底座图模型介绍（供内容生成策略复用）
_KNOWLEDGE_BASE_MODEL_PROMPT: str = _load_prompt("knowledge_base_model")

# 内容块格式说明与输出要求（供内容生成策略复用）
_BLOCK_FORMAT_GUIDE_PROMPT: str = _load_prompt("block_format_guide")

# 批量内容生成系统提示词
BATCH_CONTENT_GENERATION_SYSTEM_PROMPT: str = (
    _load_prompt("batch_content_generation") + "\n\n" + _KNOWLEDGE_BASE_MODEL_PROMPT
)

# 大纲确认系统提示词
OUTLINE_CONFIRMATION_PROMPT: str = (
    _load_prompt("outline_confirmation") + "\n\n" + _KNOWLEDGE_BASE_MODEL_PROMPT
)

# 完整上下文策略系统提示词
FULL_CONTEXT_STRATEGY_PROMPT: str = (
    _load_prompt("full_context_strategy")
    + "\n\n"
    + _BLOCK_FORMAT_GUIDE_PROMPT
    + "\n\n"
    + _KNOWLEDGE_BASE_MODEL_PROMPT
)

# 分批生成策略系统提示词（原精简上下文策略，重命名避免歧义）
BATCH_CONTEXT_STRATEGY_PROMPT: str = (
    _load_prompt("filtered_context_strategy")
    + "\n\n"
    + _BLOCK_FORMAT_GUIDE_PROMPT
    + "\n\n"
    + _KNOWLEDGE_BASE_MODEL_PROMPT
)

# 向后兼容别名
FILTERED_CONTEXT_STRATEGY_PROMPT = BATCH_CONTEXT_STRATEGY_PROMPT

# 列表项生成系统提示词
LIST_GENERATION_SYSTEM_PROMPT: str = (
    _load_prompt("list_generation") + "\n\n" + _KNOWLEDGE_BASE_MODEL_PROMPT
)

__all__ = [
    "BATCH_CONTENT_GENERATION_SYSTEM_PROMPT",
    "OUTLINE_CONFIRMATION_PROMPT",
    "FULL_CONTEXT_STRATEGY_PROMPT",
    "BATCH_CONTEXT_STRATEGY_PROMPT",
    "FILTERED_CONTEXT_STRATEGY_PROMPT",
    "LIST_GENERATION_SYSTEM_PROMPT",
]
