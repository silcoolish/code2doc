"""配置管理."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 获取项目根目录（app/config.py 的上级目录）
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """应用配置."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # FastAPI配置
    app_name: str = Field(default="doc-handle-agent", alias="APP_NAME")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8001, alias="APP_PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    # LLM配置
    llm_provider: str = Field(default="qwen", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="qwen-max-latest", alias="LLM_MODEL")
    llm_request_timeout: float = Field(default=180.0, alias="LLM_REQUEST_TIMEOUT")

    # MCP配置
    mcp_server_url: str = Field(
        default="http://localhost:8000/sse",
        alias="MCP_SERVER_URL",
    )

    # Workspace服务配置
    workspace_service_url: str = Field(
        default="http://localhost:18867",
        alias="WORKSPACE_SERVICE_URL",
    )

    # 路径配置
    template_dir: str = Field(default="./templates", alias="TEMPLATE_DIR")
    output_dir: str = Field(default="./output", alias="OUTPUT_DIR")
    log_dir: str = Field(default="./log", alias="LOG_DIR")
    temp_dir: str = Field(default="./temp", alias="TEMP_DIR")

    # 日志配置
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def template_path(self) -> Path:
        """获取模板目录路径."""
        return Path(self.template_dir).resolve()

    @property
    def output_path(self) -> Path:
        """获取输出目录路径."""
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    @property
    def log_path(self) -> Path:
        """获取日志目录路径."""
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    @property
    def temp_path(self) -> Path:
        """获取临时目录路径."""
        path = Path(self.temp_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()


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
