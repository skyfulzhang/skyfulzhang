"""全局配置模块"""
import os


class Config:
    BASE_URL: str = os.getenv("BASE_URL", "https://api.example.com")
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))
    DB_PATH: str = os.getenv("DB_PATH", "chain_store.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "execution.log")
    REPORT_DIR: str = os.getenv("REPORT_DIR", "reports/")
    MAX_RETRY: int = int(os.getenv("MAX_RETRY", "3"))
    RETRY_INTERVAL: float = float(os.getenv("RETRY_INTERVAL", "1.0"))
    MOCK_ENABLED: bool = os.getenv("MOCK_ENABLED", "true").lower() == "true"
    ENV: str = os.getenv("ENV", "test")  # test | staging | prod


# 默认配置实例
config = Config()
