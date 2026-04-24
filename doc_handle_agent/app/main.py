"""FastAPI应用入口."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import generation, progress
from app.config import get_settings
from app.utils.logger import get_logger, setup_logging, bind_log_context

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

    # Trace ID 中间件：为每个请求注入 trace_id 到日志上下文
    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        if not trace_id:
            trace_id = str(uuid.uuid4())

        with bind_log_context(trace_id=trace_id):
            response = await call_next(request)
            response.headers["X-Request-ID"] = trace_id
            return response

    # 全局异常处理中间件：记录未捕获异常
    @app.middleware("http")
    async def error_logging_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            logger.error(
                "unhandled_exception",
                path=request.url.path,
                method=request.method,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
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
