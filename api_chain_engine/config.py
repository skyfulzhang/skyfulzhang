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
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/execution.log")

    # 报告
    REPORT_DIR: str = os.getenv("REPORT_DIR", "reports/")

    # 运行环境: test | staging | prod
    ENV: str = os.getenv("ENV", "test")

    # Mock 模式（测试时启用）
    MOCK_ENABLED: bool = os.getenv("MOCK_ENABLED", "true").lower() == "true"

    # 默认请求头
    DEFAULT_HEADERS: Dict[str, str] = field(default_factory=lambda: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ApiChainEngine/1.0.0",
    })

    # 环境变量配置映射
    ENV_CONFIGS: Dict[str, Dict] = field(default_factory=lambda: {
        "test": {
            "base_url": "https://test-api.example.com",
            "timeout": 30,
        },
        "staging": {
            "base_url": "https://staging-api.example.com",
            "timeout": 60,
        },
        "prod": {
            "base_url": "https://api.example.com",
            "timeout": 30,
        },
    })

    def get_env_config(self) -> Dict:
        return self.ENV_CONFIGS.get(self.ENV, {})


# 全局配置单例
config = Config()
