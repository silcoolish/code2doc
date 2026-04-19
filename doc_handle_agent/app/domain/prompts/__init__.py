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


# 批量内容生成系统提示词
BATCH_CONTENT_GENERATION_SYSTEM_PROMPT: str = _load_prompt("batch_content_generation")

# 单个内容生成系统提示词
CONTENT_GENERATION_SYSTEM_PROMPT: str = _load_prompt("content_generation")

# 列表生成系统提示词
LIST_GENERATION_SYSTEM_PROMPT: str = _load_prompt("list_generation")

# 图片下载系统提示词
IMAGE_DOWNLOAD_SYSTEM_PROMPT: str = _load_prompt("image_download")

# 策略一：完整上下文内容生成系统提示词
STRATEGY1_FULL_CONTEXT_PROMPT: str = _load_prompt("strategy1_full_context")

# 策略二：精简上下文内容生成系统提示词
STRATEGY2_FILTERED_CONTEXT_PROMPT: str = _load_prompt("strategy2_filtered_context")

__all__ = [
    "BATCH_CONTENT_GENERATION_SYSTEM_PROMPT",
    "CONTENT_GENERATION_SYSTEM_PROMPT",
    "LIST_GENERATION_SYSTEM_PROMPT",
    "IMAGE_DOWNLOAD_SYSTEM_PROMPT",
    "STRATEGY1_FULL_CONTEXT_PROMPT",
    "STRATEGY2_FILTERED_CONTEXT_PROMPT",
]
