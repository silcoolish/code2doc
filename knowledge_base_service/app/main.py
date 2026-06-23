"""FastAPI 应用入口."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT, get_settings, resolve_runtime_path
from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.api.routes import initialization, progress, reset, settings
from app.api.test import (
    flowchart_generation as test_flowchart_generation,
    module_detection as test_module_detection,
    structure_graph_build as test_structure_graph_build,
    semantic_analysis as test_semantic_analysis,
    vector_db_store as test_vector_db_store,
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
    app_settings = get_settings()

    # 创建日志根目录
    try:
        Path(app_settings.log_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"Log directory created: {app_settings.log_dir}")
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


def _resolve_static_path(app_settings) -> Path:
    """解析静态文件目录路径."""
    return resolve_runtime_path(app_settings.static_files_path)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例."""
    app_settings = get_settings()

    app = FastAPI(
        title="Knowledge Base Service",
        description="代码知识底座管理服务",
        version=app_settings.app_version,
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
    app.include_router(
        settings.router,
        prefix="/api/v1",
        tags=["settings"],
    )

    # MCP 路由 (HTTP 方式)
    app.include_router(mcp_router)

    # 静态文件服务 - 提供data目录中的图片访问
    static_path = _resolve_static_path(app_settings)
    static_path.mkdir(parents=True, exist_ok=True)
    static_dir = str(static_path.resolve())
    static_url = app_settings.static_files_url

    # 确保URL以/开头
    if not static_url.startswith("/"):
        static_url = "/" + static_url

    logger.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
    logger.info(f"Static files configured: URL={static_url}, Directory={static_dir}")

    app.mount(
        static_url,
        StaticFiles(directory=static_dir, check_dir=False),
        name="static"
    )

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
    app.include_router(
        test_vector_db_store.router,
        prefix="/api/v1/test",
        tags=["test"],
    )

    @app.get("/health")
    async def health_check():
        """健康检查端点."""
        return {"status": "healthy", "version": app_settings.app_version}

    # 图片下载接口
    @app.get("/images/{repo_id}/{image_id}")
    async def download_image(repo_id: str, image_id: str):
        """根据仓库ID和图片ID下载图片文件."""
        from fastapi.responses import FileResponse

        static_path = _resolve_static_path(app_settings)
        file_path = static_path / repo_id / "image" / image_id
        logger.info(f"Image download request: {file_path}")

        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            raise HTTPException(
                status_code=404,
                detail={"error": "File not found", "path": str(file_path)},
            )

        media_type = "image/svg+xml" if image_id.endswith(".svg") else "image/png"
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=image_id,
        )

    return app


# 应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn

    app_settings = get_settings()
    is_frozen = getattr(sys, "frozen", False)
    app_target = app if is_frozen else "app.main:app"
    uvicorn.run(
        app_target,
        host=app_settings.host,
        port=app_settings.port,
        reload=app_settings.debug and not is_frozen,
        workers=1,
    )
