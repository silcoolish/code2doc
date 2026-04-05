"""FastAPI应用入口."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import generation, progress
from app.config import get_settings
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    # 启动时
    setup_logging()
    logger.info(
        "app_startup",
        app_name=app.title,
        version=app.version,
    )

    yield

    # 关闭时
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """创建FastAPI应用.

    Returns:
        FastAPI应用实例
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="文档处理Agent服务 - 基于LangGraph的智能文档生成",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 配置CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(
        generation.router,
        prefix="/api/v1",
    )
    app.include_router(
        progress.router,
        prefix="/api/v1",
    )

    @app.get("/health")
    async def health_check():
        """健康检查端点."""
        return {"status": "healthy", "service": settings.app_name}

    @app.get("/")
    async def root():
        """根路径."""
        return {
            "service": settings.app_name,
            "version": "1.0.0",
            "docs": "/docs",
        }

    return app


# 应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
