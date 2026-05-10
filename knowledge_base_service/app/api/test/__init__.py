"""测试API模块.

提供各个流水线阶段的单独测试接口，方便独立测试和调试。
"""

from .flowchart_generation import router as flowchart_generation_router
from .module_detection import router as module_detection_router
from .structure_graph_build import router as structure_graph_build_router
from .semantic_analysis import router as semantic_analysis_router
from .vector_db_store import router as vector_db_store_router

__all__ = [
    "flowchart_generation_router",
    "module_detection_router",
    "structure_graph_build_router",
    "semantic_analysis_router",
    "vector_db_store_router",
]
