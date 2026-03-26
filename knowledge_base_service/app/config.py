"""配置管理模块."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类."""

    model_config = SettingsConfigDict(
        env_file=".env",
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

    # Neo4j Settings
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password")

    # Vector Database Settings
    vector_db_type: str = Field(default="milvus")  # "milvus" | "pinecone" | "weaviate" | "qdrant"

    # Milvus Settings
    milvus_host: str = Field(default="localhost")
    milvus_port: int = Field(default=19530)

    # LLM Provider: "anthropic" | "openai" | "qwen" | "azure"
    llm_provider: str = Field(default="qwen")

    # Anthropic Settings
    anthropic_api_key: Optional[str] = Field(default=None)
    anthropic_model: str = Field(default="claude-sonnet-4-6")

    # OpenAI Settings
    openai_api_key: Optional[str] = Field(default=None)
    openai_model: str = Field(default="gpt-4o")
    openai_embedding_model: str = Field(default="text-embedding-3-large")

    # Qwen/DashScope Settings
    dashscope_api_key: Optional[str] = Field(default=None)
    qwen_model: str = Field(default="qwen3.5-plus")
    qwen_embedding_model: str = Field(default="text-embedding-v3")
    qwen_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Embedding Settings
    embedding_dimensions: int = Field(default=1024)
    embedding_provider: str = Field(default="qwen")  # "openai" | "qwen"

    # Pipeline Settings
    batch_size: int = Field(default=100)
    max_retries: int = Field(default=3)
    retry_delay: float = Field(default=1.0)

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


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例模式）."""
    return Settings()
