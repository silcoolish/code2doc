"""配置管理模块."""

from pathlib import Path
import sys
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_project_root() -> Path:
    """获取运行时项目根目录."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = get_project_root()


def resolve_runtime_path(path_value: str) -> Path:
    """解析运行时路径，打包态相对 exe 目录，源码态相对项目根目录."""
    normalized = path_value.strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    path = Path(normalized)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


class Settings(BaseSettings):
    """应用配置类."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App Settings
    app_name: str = Field(default="knowledge_base_service")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # Neo4j Settings
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password")

    # Graph Database Settings
    graph_db_type: str = Field(default="neo4j")  # "neo4j" | "nebula" | "janusgraph"

    # Vector Database Settings
    vector_db_type: str = Field(default="milvus")  # "milvus" | "pinecone" | "weaviate" | "qdrant"

    # Milvus Settings
    milvus_host: str = Field(default="localhost")
    milvus_port: int = Field(default=19530)

    # LLM Provider: "anthropic" | "openai" | "qwen" | "azure"
    llm_provider: str = Field(default="qwen")

    # Unified LLM Settings
    llm_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: Optional[str] = Field(default=None)
    llm_model: str = Field(default="qwen3.5-plus")

    # Embedding Settings
    embedding_dimensions: int = Field(default=1024)
    embedding_provider: str = Field(default="qwen")  # "openai" | "qwen"
    embedding_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    embedding_api_key: Optional[str] = Field(default=None)
    embedding_model: str = Field(default="text-embedding-v3")

    # Pipeline Settings
    batch_size: int = Field(default=100)
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)

    # LLM Context Window Settings (fallback when API detection fails)
    llm_context_window: int = Field(default=128000)  # 默认 128K tokens

    # Logging Settings
    log_dir: str = Field(default="./log")
    log_level: str = Field(default="INFO")

    # Supported Languages
    supported_languages: List[str] = Field(
        default=[
            ".py",
            ".java",
            ".js",
            ".ts",
            ".go",
            ".rs",
            ".cpp",
            ".c",
            ".h",
        ]
    )

    # Default Exclude Patterns
    default_exclude_patterns: List[str] = Field(
        default=[
            "node_modules/**",
            ".git/**",
            "__pycache__/**",
            "*.min.js",
            "*.min.css",
            "dist/**",
            "build/**",
            ".idea/**",
            ".vscode/**",
            "*.pyc",
            "*.class",
            "target/**",
            "vendor/**",
        ]
    )

    # Flowchart Generation Service Settings
    flowchart_service_url: str = Field(default="http://localhost:18765")
    flowchart_service_timeout: int = Field(default=30)
    flowchart_supported_languages: List[str] = Field(default=["c", "cpp"])
    flowchart_image_dir: str = Field(default="data")  # 相对于项目根目录
    flowchart_batch_size: int = Field(default=50)  # 每批处理的方法数量

    # Static Files Settings
    public_base_url: str = Field(default="http://localhost:8000")  # 公共服务基础URL
    static_files_path: str = Field(default="data")  # 相对于运行时项目根目录
    static_files_url: str = Field(default="/static")  # 静态文件URL前缀

    # Module Detection Strategy Settings
    # Strategy: "simple" | "clustering"
    module_detection_strategy: str = Field(default="simple")

    # Simple Truncation Strategy Settings
    simple_strategy_max_files: int = Field(default=100)

    # Clustering Strategy Settings
    clustering_strategy_max_cluster_size: int = Field(default=80)
    clustering_strategy_max_concurrency: int = Field(default=5)
    clustering_strategy_merge_threshold: float = Field(default=0.7)


def get_settings() -> Settings:
    """获取配置实例（每次调用重新读取 .env）."""
    return Settings()


def update_env_file(updates: dict) -> None:
    """更新 .env 文件中的配置项.

    Args:
        updates: 要更新的 key-value 字典
    """
    env_path = PROJECT_ROOT / ".env"
    lines = []
    existing: dict[str, str] = {}

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, val = stripped.split("=", 1)
                existing[key] = val
            lines.append(line)

    existing.update(updates)

    with open(env_path, "w", encoding="utf-8") as f:
        for key, val in existing.items():
            f.write(f"{key}={val}\n")
