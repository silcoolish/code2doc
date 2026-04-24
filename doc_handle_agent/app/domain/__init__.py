"""Domain layer - 核心业务逻辑."""

from app.domain.content_generator import ContentGenerator
from app.domain.content_generator_agent import ContentGeneratorAgent
from app.domain.generation_strategies import (
    BatchedGenerationStrategy,
    FilteredContextStrategy,
    FullContextStrategy,
    GenerationStrategy,
    StrategySelector,
)
from app.domain.model import (
    BlockType,
    DocumentBlock,
    GenerationStatus,
    ImageInfo,
    TemplateBlock,
    TemplateType,
)
from app.domain.static_list_provider import ListItem, StaticListProvider

__all__ = [
    # 内容生成
    "ContentGenerator",
    "ContentGeneratorAgent",
    # 策略
    "GenerationStrategy",
    "FullContextStrategy",
    "FilteredContextStrategy",
    "BatchedGenerationStrategy",
    "StrategySelector",
    # 领域模型
    "BlockType",
    "TemplateType",
    "GenerationStatus",
    "TemplateBlock",
    "ImageInfo",
    "DocumentBlock",
    # 静态列表
    "ListItem",
    "StaticListProvider",
]
