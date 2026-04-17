"""FastAPI 应用入口."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.api.routes import initialization, progress, reset
from app.api.test import (
    flowchart_generation as test_flowchart_generation,
    module_detection as test_module_detection,
    structure_graph_build as test_structure_graph_build,
    semantic_analysis as test_semantic_analysis,
)
from app.core.pipeline import get_orchestrator
from app.mcp import router as mcp_router
from app.domain.models.pipeline import PipelineStage

# 导入所有阶段处理器
from app.core.stages import (
    StructureGraphBuildStage,
    DependencyGraphBuildStage,
    SemanticAnalysisStage,
    FlowchartGenerationStage,
    VectorDBStoreStage,
    ModuleDetectionStage,
)

# 确保日志目录存在
log_dir = Path("./log")
log_dir.mkdir(parents=True, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "server.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def _register_pipeline_stages():
    """注册所有流水线阶段处理器."""
    orchestrator = get_orchestrator()

    # REPO_TRAVERSAL 已合并到 STRUCTURE_GRAPH_BUILD
    orchestrator.register_handler(PipelineStage.STRUCTURE_GRAPH_BUILD, StructureGraphBuildStage())
    orchestrator.register_handler(PipelineStage.DEPENDENCY_GRAPH_BUILD, DependencyGraphBuildStage())
    orchestrator.register_handler(PipelineStage.SEMANTIC_ANALYSIS, SemanticAnalysisStage())
    orchestrator.register_handler(PipelineStage.FLOWCHART_GENERATION, FlowchartGenerationStage())
    orchestrator.register_handler(PipelineStage.MODULE_DETECTION, ModuleDetectionStage())
    orchestrator.register_handler(PipelineStage.VECTOR_DB_STORE, VectorDBStoreStage())
    # EMBEDDING_GENERATION 已合并到 VECTOR_DB_STORE

    logger.info("Pipeline stages registered")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    # 启动时
    logger.info("Starting up Knowledge Base Service...")
    settings = get_settings()

    # 创建日志根目录
    try:
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"Log directory created: {settings.log_dir}")
    except Exception as e:
        logger.error(f"Failed to create log directory: {e}")

    # 注册流水线阶段
    _register_pipeline_stages()

    # 连接数据库
    try:
        neo4j_client = get_graph_db_client()
        await neo4j_client.connect()
        logger.info("Graph database connected")
    except Exception as e:
        logger.error(f"Failed to connect to graph database: {e}")

    try:
        milvus_client = get_vector_db_client()
        await milvus_client.connect()
        logger.info("Vector database connected")
    except Exception as e:
        logger.error(f"Failed to connect to vector database: {e}")

    # 初始化 LLM 上下文窗口
    try:
        from app.infrastructure.llm import LLMClient

        llm_client = LLMClient()
        await llm_client.initialize_context_window()
    except Exception as e:
        logger.error(f"Failed to initialize LLM context window: {e}")
        # 服务可以继续启动，使用默认配置值

    yield

    # 关闭时
    logger.info("Shutting down Knowledge Base Service...")

    try:
        neo4j_client = get_graph_db_client()
        await neo4j_client.close()
        logger.info("Graph database disconnected")
    except Exception as e:
        logger.error(f"Error closing graph database connection: {e}")

    try:
        milvus_client = get_vector_db_client()
        await milvus_client.close()
        logger.info("Vector database disconnected")
    except Exception as e:
        logger.error(f"Error closing vector database connection: {e}")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例."""
    settings = get_settings()

    app = FastAPI(
        title="Knowledge Base Service",
        description="代码知识底座管理服务",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(
        initialization.router,
        prefix="/api/v1/initialization",
        tags=["initialization"],
    )
    app.include_router(
        progress.router,
        prefix="/api/v1/initialization",
        tags=["progress"],
    )
    app.include_router(
        reset.router,
        prefix="/api/v1/initialization",
        tags=["reset"],
    )

    # MCP 路由 (HTTP 方式)
    app.include_router(mcp_router)

    # 测试路由
    app.include_router(
        test_structure_graph_build.router,
        prefix="/api/v1/test",
        tags=["test"],
    )
    app.include_router(
        test_semantic_analysis.router,
        prefix="/api/v1/test",
        tags=["test"],
    )
    app.include_router(
        test_module_detection.router,
        prefix="/api/v1/test",
        tags=["test"],
    )
    app.include_router(
        test_flowchart_generation.router,
        prefix="/api/v1/test",
        tags=["test"],
    )

    @app.get("/health")
    async def health_check():
        """健康检查端点."""
        return {"status": "healthy", "version": settings.app_version}

    return app


# 应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
