"""
agent/models/report_models.py
报告相关数据模型 - 从 test_config.py 重新导出，统一入口。
"""

from agent.models.test_config import (
    AnalysisResult,
    ComparisonResult,
    K6ReportSummary,
    K6TestConfig,
    PipelineResult,
    WorkflowRunStatus,
)

__all__ = [
    "K6TestConfig",
    "K6ReportSummary",
    "WorkflowRunStatus",
    "PipelineResult",
    "AnalysisResult",
    "ComparisonResult",
]
