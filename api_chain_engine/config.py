# -*- coding: utf-8 -*-
"""
全局配置模块
支持多环境配置，优先读取环境变量，其次使用默认值
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """全局配置，支持环境变量覆盖"""

    # 服务地址
    BASE_URL: str = os.getenv("BASE_URL", "https://api.example.com")

    # HTTP 配置
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))
    MAX_RETRY: int = int(os.getenv("MAX_RETRY", "3"))
    RETRY_INTERVAL: float = float(os.getenv("RETRY_INTERVAL", "1.0"))

    # 数据库
    DB_PATH: str = os.getenv("DB_PATH", "chain_store.db")

    # 日志
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "execution.log")

    # 报告
    REPORT_DIR: str = os.getenv("REPORT_DIR", "reports")

    # 运行模式
    MOCK_ENABLED: bool = os.getenv("MOCK_ENABLED", "true").lower() == "true"
    ENV: str = os.getenv("ENV", "test")  # test | staging | prod

    # 请求头默认值
    DEFAULT_HEADERS: dict = field(default_factory=lambda: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ApiChainEngine/1.0",
    })


# 全局单例
config = Config()
