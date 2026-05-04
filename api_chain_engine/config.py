# -*- coding: utf-8 -*-
"""
全局配置模块
支持多环境配置，可通过环境变量覆盖
"""
import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Config:
    """全局配置类，支持环境变量覆盖"""

    # 服务基础配置
    BASE_URL: str = os.getenv("BASE_URL", "https://api.example.com")
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))

    # 数据库配置
    DB_PATH: str = os.getenv("DB_PATH", "chain_store.db")

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/execution.log")
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "7 days"

    # 报告配置
    REPORT_DIR: str = os.getenv("REPORT_DIR", "reports/")

    # 重试配置
    MAX_RETRY: int = int(os.getenv("MAX_RETRY", "3"))
    RETRY_INTERVAL: float = float(os.getenv("RETRY_INTERVAL", "1.0"))
    RETRY_STATUS_CODES: list = field(default_factory=lambda: [500, 502, 503, 504])

    # Mock 配置（测试环境启用）
    MOCK_ENABLED: bool = os.getenv("MOCK_ENABLED", "true").lower() == "true"

    # 环境标识
    ENV: str = os.getenv("ENV", "test")  # test | staging | prod

    # 并发配置
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "5"))

    # 请求头默认配置
    DEFAULT_HEADERS: Dict[str, str] = field(default_factory=lambda: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ApiChainEngine/1.0"
    })

    # 断言失败策略: stop | continue
    DEFAULT_ON_FAILURE: str = "stop"

    # 上下文变量作用域: chain | step | global
    DEFAULT_SCOPE: str = "chain"


# 单例配置
config = Config()

# 环境变量映射
ENV_CONFIGS: Dict[str, Dict] = {
    "test": {
        "BASE_URL": "https://test-api.example.com",
        "MOCK_ENABLED": True,
        "LOG_LEVEL": "DEBUG",
    },
    "staging": {
        "BASE_URL": "https://staging-api.example.com",
        "MOCK_ENABLED": False,
        "LOG_LEVEL": "INFO",
    },
    "prod": {
        "BASE_URL": "https://api.example.com",
        "MOCK_ENABLED": False,
        "LOG_LEVEL": "WARNING",
    },
}
