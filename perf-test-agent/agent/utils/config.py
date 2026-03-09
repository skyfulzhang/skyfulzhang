"""
agent/utils/config.py
配置管理模块 - 使用 pydantic-settings 管理所有配置，支持 .env 文件加载。
"""

from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置。

    所有配置项均可通过环境变量或 .env 文件覆盖。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GitHub ──────────────────────────────────────────────────────────────
    github_token: str = Field(..., description="GitHub Personal Access Token")
    github_repo_owner: str = Field(..., description="GitHub 仓库所有者（用户名或组织名）")
    github_repo_name: str = Field(..., description="GitHub 仓库名称")

    # ── LLM Provider ────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "azure", "ollama"] = Field(
        default="openai", description="LLM 提供商"
    )

    # OpenAI
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API Key")
    openai_model: str = Field(default="gpt-4o", description="OpenAI 模型名称")

    # Azure OpenAI
    azure_openai_endpoint: Optional[str] = Field(
        default=None, description="Azure OpenAI 端点 URL"
    )
    azure_openai_api_key: Optional[str] = Field(
        default=None, description="Azure OpenAI API Key"
    )
    azure_openai_deployment: Optional[str] = Field(
        default=None, description="Azure OpenAI 部署名称"
    )

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama 服务地址"
    )
    ollama_model: str = Field(default="llama3", description="Ollama 模型名称")

    # ── k6 ──────────────────────────────────────────────────────────────────
    k6_scripts_dir: str = Field(default="k6_scripts", description="k6 脚本存放目录")

    # ── Workflow ─────────────────────────────────────────────────────────────
    max_workflow_wait_seconds: int = Field(
        default=1800, description="等待 workflow 完成的最大秒数"
    )
    workflow_poll_interval_seconds: int = Field(
        default=30, description="轮询 workflow 状态的间隔秒数"
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="日志级别")
    log_format: Literal["json", "text"] = Field(
        default="json", description="日志格式：json（生产环境）或 text（开发环境）"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """校验日志级别合法性。"""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level 必须是 {allowed} 之一，当前值: {v!r}")
        return upper

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, v: str) -> str:
        """确保 GitHub Token 非空。"""
        if not v or v.strip() == "":
            raise ValueError("GITHUB_TOKEN 不能为空")
        return v.strip()


# 全局单例（懒加载）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置单例。

    Returns:
        Settings: 全局配置对象。

    Raises:
        pydantic_settings.ValidationError: 当必填配置缺失时。
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
