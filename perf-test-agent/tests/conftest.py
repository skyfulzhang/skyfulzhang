"""
tests/conftest.py
pytest 全局配置和 fixtures。
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.models.test_config import K6ReportSummary, K6TestConfig
from datetime import datetime, timezone


# ── 基础 Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_k6_config() -> K6TestConfig:
    """标准 k6 测试配置 fixture。"""
    return K6TestConfig(
        target_url="https://httpbin.org",  # type: ignore[arg-type]
        test_type="load",
        vus=10,
        duration="30s",
        ramp_up_time="10s",
        ramp_down_time="10s",
        script_name="test-load",
        description="测试用配置",
    )


@pytest.fixture
def sample_report_summary() -> K6ReportSummary:
    """标准 k6 报告摘要 fixture。"""
    now = datetime.now(tz=timezone.utc)
    return K6ReportSummary(
        test_name="test-load",
        start_time=now,
        end_time=now,
        duration_seconds=60.0,
        http_req_duration_avg=150.0,
        http_req_duration_p90=280.0,
        http_req_duration_p95=350.0,
        http_req_duration_p99=480.0,
        http_req_duration_max=650.0,
        http_reqs_total=1000,
        http_reqs_rate=16.7,
        http_req_failed_rate=0.005,
        data_received_bytes=5242880.0,
        data_sent_bytes=102400.0,
        vus_max=10,
        thresholds_passed=True,
        thresholds_detail={
            "http_req_duration['p(95)<500']": True,
            "http_req_failed['rate<0.01']": True,
        },
        raw_metrics={},
    )


@pytest.fixture
def sample_k6_json_report() -> str:
    """标准 k6 JSON summary 报告内容 fixture。"""
    return json.dumps({
        "metrics": {
            "http_req_duration": {
                "type": "trend",
                "contains": "time",
                "values": {
                    "avg": 150.0,
                    "min": 50.0,
                    "max": 650.0,
                    "p(90)": 280.0,
                    "p(95)": 350.0,
                    "p(99)": 480.0,
                },
            },
            "http_reqs": {
                "type": "counter",
                "values": {"count": 1000, "rate": 16.7},
            },
            "http_req_failed": {
                "type": "rate",
                "values": {"rate": 0.005, "passes": 995, "fails": 5},
            },
            "data_received": {
                "type": "counter",
                "values": {"count": 5242880, "rate": 87381.3},
            },
            "data_sent": {
                "type": "counter",
                "values": {"count": 102400, "rate": 1706.7},
            },
            "vus_max": {
                "type": "gauge",
                "values": {"value": 10, "min": 0, "max": 10},
            },
        },
        "thresholds": {
            "http_req_duration['p(95)<500']": {"ok": True},
            "http_req_failed['rate<0.01']": {"ok": True},
        },
        "state": {"testRunDuration": 60000000000},
        "options": {
            "ext": {"loadimpact": {"name": "test-load"}},
        },
    })


@pytest.fixture
def mock_settings():
    """模拟配置 fixture（不需要真实 API Key）。"""
    settings = MagicMock()
    settings.github_token = "ghp_mock_token_12345"
    settings.github_repo_owner = "test-owner"
    settings.github_repo_name = "test-repo"
    settings.llm_provider = "openai"
    settings.openai_api_key = "sk-mock-key"
    settings.openai_model = "gpt-4o"
    settings.k6_scripts_dir = "k6_scripts"
    settings.max_workflow_wait_seconds = 1800
    settings.workflow_poll_interval_seconds = 30
    settings.log_level = "INFO"
    settings.log_format = "text"
    return settings
