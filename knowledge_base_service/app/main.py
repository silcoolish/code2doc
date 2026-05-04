"""FastAPI 应用入口."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# 获取项目根目录（基于当前文件位置）
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.infrastructure.db import get_graph_db_client, get_vector_db_client
from app.api.routes import initialization, progress, reset
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

    # 静态文件服务 - 提供data目录中的图片访问
    # 使用基于项目根目录的绝对路径，避免工作目录问题
    if settings.static_files_path.startswith("./"):
        # 相对路径，基于项目根目录
        relative_path = settings.static_files_path[2:]  # 移除 ./ 前缀
        static_path = BASE_DIR / relative_path
    elif settings.static_files_path.startswith("/"):
        # 已经是绝对路径
        static_path = Path(settings.static_files_path)
    else:
        # 相对路径但没有 ./ 前缀，基于项目根目录
        static_path = BASE_DIR / settings.static_files_path

    static_path.mkdir(parents=True, exist_ok=True)
    static_dir = str(static_path.resolve())
    static_url = settings.static_files_url

    # 确保URL以/开头
    if not static_url.startswith("/"):
        static_url = "/" + static_url

    logger.info(f"BASE_DIR: {BASE_DIR}")
    logger.info(f"Static files configured: URL={static_url}, Directory={static_dir}")

    # 验证测试文件是否存在
    test_file = static_path / "repo_b087a727a064488f9078f5c0bbc00624/image/Hardware_usart3_usart3_c_Usart3_Init__L27.svg"
    logger.info(f"Test file path: {test_file}")
    logger.info(f"Test file exists: {test_file.exists()}")

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
        return {"status": "healthy", "version": settings.app_version}

    # 临时测试路由：直接提供图片文件
    @app.get("/test-image/{repo_id}/{filename:path}")
    async def test_image(repo_id: str, filename: str):
        """测试图片访问."""
        from fastapi.responses import FileResponse
        import os

        # 使用与静态文件服务相同的路径逻辑
        if settings.static_files_path.startswith("./"):
            relative_path = settings.static_files_path[2:]
            static_path = BASE_DIR / relative_path
        elif settings.static_files_path.startswith("/"):
            static_path = Path(settings.static_files_path)
        else:
            static_path = BASE_DIR / settings.static_files_path

        # 构建文件路径
        file_path = static_path / repo_id / "image" / filename
        logger.info(f"Test image request: {file_path}")

        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return {"error": "File not found", "path": str(file_path)}

        return FileResponse(
            path=str(file_path),
            media_type="image/svg+xml" if filename.endswith(".svg") else "image/png"
        )

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
