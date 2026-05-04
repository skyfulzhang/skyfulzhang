# -*- coding: utf-8 -*-
"""
全局配置模块
支持多环境切换：test / staging / prod
"""
import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class EnvironmentConfig:
    """单环境配置"""
    name: str
    base_url: str
    timeout: int = 30
    extra_headers: Dict[str, str] = field(default_factory=dict)


class Config:
    """全局配置，优先读取环境变量"""

    # ─── 运行环境 ───────────────────────────────────────────────
    ENV: str = os.getenv("ACE_ENV", "test")

    # ─── 数据库 ─────────────────────────────────────────────────
    DB_PATH: str = os.getenv("ACE_DB_PATH", "chain_store.db")

    # ─── 日志 ───────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("ACE_LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("ACE_LOG_FILE", "logs/execution.log")

    # ─── 报告 ───────────────────────────────────────────────────
    REPORT_DIR: str = os.getenv("ACE_REPORT_DIR", "reports/")

    # ─── 请求 ───────────────────────────────────────────────────
    TIMEOUT: int = int(os.getenv("ACE_TIMEOUT", "30"))
    MAX_RETRY: int = int(os.getenv("ACE_MAX_RETRY", "3"))
    RETRY_INTERVAL: float = float(os.getenv("ACE_RETRY_INTERVAL", "1.0"))

    # ─── Mock ───────────────────────────────────────────────────
    MOCK_ENABLED: bool = os.getenv("ACE_MOCK_ENABLED", "true").lower() == "true"

    # ─── 多环境 base_url ────────────────────────────────────────
    ENVIRONMENTS: Dict[str, EnvironmentConfig] = {
        "test": EnvironmentConfig(
            name="test",
            base_url="http://test-api.example.com",
            timeout=30,
        ),
        "staging": EnvironmentConfig(
            name="staging",
            base_url="http://staging-api.example.com",
            timeout=20,
        ),
        "prod": EnvironmentConfig(
            name="prod",
            base_url="https://api.example.com",
            timeout=10,
        ),
    }

    @classmethod
    def current_env(cls) -> EnvironmentConfig:
        return cls.ENVIRONMENTS.get(cls.ENV, cls.ENVIRONMENTS["test"])

    @classmethod
    def base_url(cls) -> str:
        return cls.current_env().base_url
