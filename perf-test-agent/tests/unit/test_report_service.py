"""
tests/unit/test_report_service.py
ReportService 单元测试。
"""

import json
from datetime import datetime, timezone

import pytest

from agent.models.test_config import K6ReportSummary
from agent.services.report_service import ReportService


@pytest.fixture
def service() -> ReportService:
    return ReportService()


class TestParseJsonSummary:
    """parse_json_summary 方法测试。"""

    def test_parse_valid_report(self, service: ReportService, sample_k6_json_report: str):
        """有效 JSON 报告应能正确解析。"""
        summary = service.parse_json_summary(sample_k6_json_report)
        assert isinstance(summary, K6ReportSummary)
        assert summary.http_req_duration_p95 == 350.0
        assert summary.http_req_duration_avg == 150.0
        assert summary.http_reqs_total == 1000
        assert summary.http_reqs_rate == 16.7
        assert summary.http_req_failed_rate == 0.005
        assert summary.vus_max == 10
        assert summary.thresholds_passed is True

    def test_parse_invalid_json_raises_value_error(self, service: ReportService):
        """无效 JSON 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="无效的 JSON 报告"):
            service.parse_json_summary("not-json-content")

    def test_parse_empty_metrics(self, service: ReportService):
        """空指标 JSON 应返回默认值（不抛出异常）。"""
        empty_report = json.dumps({"metrics": {}, "thresholds": {}})
        summary = service.parse_json_summary(empty_report)
        assert summary.http_req_duration_avg == 0.0
        assert summary.http_reqs_total == 0

    def test_parse_thresholds_all_pass(self, service: ReportService):
        """所有阈值通过时 thresholds_passed 应为 True。"""
        report = json.dumps({
            "metrics": {},
            "thresholds": {
                "http_req_duration['p(95)<500']": {"ok": True},
                "http_req_failed['rate<0.01']": {"ok": True},
            },
        })
        summary = service.parse_json_summary(report)
        assert summary.thresholds_passed is True

    def test_parse_thresholds_some_fail(self, service: ReportService):
        """有阈值失败时 thresholds_passed 应为 False。"""
        report = json.dumps({
            "metrics": {},
            "thresholds": {
                "http_req_duration['p(95)<500']": {"ok": True},
                "http_req_failed['rate<0.01']": {"ok": False},  # 失败
            },
        })
        summary = service.parse_json_summary(report)
        assert summary.thresholds_passed is False


class TestGenerateHtmlReport:
    """generate_html_report 方法测试。"""

    def test_generate_returns_html_string(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """应返回包含 HTML 标签的字符串。"""
        html = service.generate_html_report(sample_report_summary)
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "chart.js" in html.lower() or "Chart" in html

    def test_html_contains_test_name(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """HTML 报告应包含测试名称。"""
        html = service.generate_html_report(sample_report_summary)
        assert sample_report_summary.test_name in html

    def test_html_contains_p95_value(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """HTML 报告应包含 p95 响应时间值。"""
        html = service.generate_html_report(sample_report_summary)
        assert "350" in html  # p95 = 350.0 ms

    def test_html_contains_pass_status(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """阈值全通过时 HTML 应显示 PASS 状态。"""
        html = service.generate_html_report(sample_report_summary)
        assert "PASS" in html


class TestCompareReports:
    """compare_reports 方法测试。"""

    def test_detect_p95_degradation(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """p95 增加超过 50ms 应识别为退化。"""
        baseline = sample_report_summary  # p95 = 350ms
        current = sample_report_summary.model_copy(
            update={"http_req_duration_p95": 450.0, "test_name": "current"}
        )
        result = service.compare_reports(baseline, current)
        assert result.delta_p95_ms == pytest.approx(100.0)
        assert any("p95" in d.lower() for d in result.degraded_metrics)

    def test_detect_p95_improvement(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """p95 减少超过 50ms 应识别为改善。"""
        baseline = sample_report_summary  # p95 = 350ms
        current = sample_report_summary.model_copy(
            update={"http_req_duration_p95": 280.0, "test_name": "current"}
        )
        result = service.compare_reports(baseline, current)
        assert result.delta_p95_ms == pytest.approx(-70.0)
        assert any("p95" in i.lower() for i in result.improved_metrics)

    def test_detect_error_rate_degradation(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """错误率上升超过 0.5% 应识别为退化。"""
        baseline = sample_report_summary  # error_rate = 0.005
        current = sample_report_summary.model_copy(
            update={"http_req_failed_rate": 0.02, "test_name": "current"}
        )
        result = service.compare_reports(baseline, current)
        assert result.delta_error_rate == pytest.approx(0.015)
        assert any("错误率" in d for d in result.degraded_metrics)

    def test_unchanged_metrics(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """相同报告对比应无退化也无改善。"""
        result = service.compare_reports(sample_report_summary, sample_report_summary)
        # 完全相同时，delta 应接近 0
        assert result.delta_p95_ms == pytest.approx(0.0)
        assert result.delta_error_rate == pytest.approx(0.0)


class TestExtractKeyMetrics:
    """extract_key_metrics 方法测试。"""

    def test_returns_dict_with_required_keys(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """应返回包含所有必要键的字典。"""
        metrics = service.extract_key_metrics(sample_report_summary)
        required_keys = [
            "test_name", "p95_ms", "p99_ms", "error_rate",
            "rps", "total_requests", "vus_max", "thresholds_passed",
        ]
        for key in required_keys:
            assert key in metrics, f"缺少键: {key}"

    def test_p95_value_correct(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """p95 值应与摘要中的值一致。"""
        metrics = service.extract_key_metrics(sample_report_summary)
        assert metrics["p95_ms"] == sample_report_summary.http_req_duration_p95

    def test_error_rate_pct_calculation(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """错误率百分比应正确计算。"""
        metrics = service.extract_key_metrics(sample_report_summary)
        # error_rate = 0.005，pct 应为 0.5%
        assert metrics["error_rate_pct"] == pytest.approx(0.5, abs=0.001)

    def test_data_received_mb_conversion(
        self, service: ReportService, sample_report_summary: K6ReportSummary
    ):
        """数据接收量应转换为 MB。"""
        metrics = service.extract_key_metrics(sample_report_summary)
        # 5242880 bytes = 5 MB
        assert metrics["data_received_mb"] == pytest.approx(5.0, abs=0.01)
