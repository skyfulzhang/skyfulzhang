"""
agent/models/test_config.py
Pydantic v2 数据模型 - 测试配置与报告数据结构。
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class K6TestConfig(BaseModel):
    """k6 测试配置模型。

    Attributes:
        target_url: 被测目标 URL。
        test_type: 测试类型（load/stress/spike/soak/api）。
        vus: 并发虚拟用户数。
        duration: 稳定期持续时长，格式为 ``\\d+[smh]``。
        ramp_up_time: 爬升期时长。
        ramp_down_time: 下降期时长。
        thresholds: k6 阈值配置字典。
        headers: 自定义请求头。
        scenarios: 高级场景配置。
        env_vars: 传递给 k6 脚本的环境变量。
        script_name: 脚本名称（用于文件命名）。
        description: 测试描述。
    """

    target_url: HttpUrl
    test_type: Literal["load", "stress", "spike", "soak", "api"]
    vus: int = Field(default=10, ge=1, le=10000, description="并发虚拟用户数")
    duration: str = Field(
        default="30s",
        pattern=r"^\d+[smh]$",
        description="稳定期持续时长，如 30s / 5m / 1h",
    )
    ramp_up_time: str = Field(default="10s", description="爬升期时长")
    ramp_down_time: str = Field(default="10s", description="下降期时长")
    thresholds: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "http_req_duration": ["p(95)<500", "p(99)<1000"],
            "http_req_failed": ["rate<0.01"],
        },
        description="k6 阈值配置，例：{'http_req_duration': ['p(95)<500']}",
    )
    headers: Dict[str, str] = Field(default_factory=dict, description="自定义 HTTP 请求头")
    scenarios: Optional[Dict[str, Any]] = Field(
        default=None, description="k6 高级场景配置（优先级高于 stages）"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="传递给 k6 脚本的环境变量"
    )
    script_name: str = Field(default="test", description="脚本名称，用于文件和报告命名")
    description: str = Field(default="", description="测试描述")

    @field_validator("ramp_up_time", "ramp_down_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """校验时间格式。"""
        import re

        if not re.match(r"^\d+[smh]$", v):
            raise ValueError(f"时间格式必须为 \\d+[smh]，当前值: {v!r}")
        return v


class K6ReportSummary(BaseModel):
    """k6 测试报告摘要数据模型。

    对应 k6 ``--summary-export`` 输出的 JSON 结构。
    """

    test_name: str = Field(description="测试名称")
    start_time: datetime = Field(description="测试开始时间")
    end_time: datetime = Field(description="测试结束时间")
    duration_seconds: float = Field(description="测试总耗时（秒）")

    # HTTP 响应时间指标（毫秒）
    http_req_duration_avg: float = Field(description="平均响应时间（ms）")
    http_req_duration_p90: float = Field(description="p90 响应时间（ms）")
    http_req_duration_p95: float = Field(description="p95 响应时间（ms）")
    http_req_duration_p99: float = Field(description="p99 响应时间（ms）")
    http_req_duration_max: float = Field(description="最大响应时间（ms）")

    # 请求统计
    http_reqs_total: int = Field(description="总请求数")
    http_reqs_rate: float = Field(description="每秒请求数（RPS）")
    http_req_failed_rate: float = Field(description="请求失败率（0~1）")

    # 网络流量
    data_received_bytes: float = Field(description="接收数据量（字节）")
    data_sent_bytes: float = Field(description="发送数据量（字节）")

    # 虚拟用户
    vus_max: int = Field(description="峰值虚拟用户数")

    # 阈值结果
    thresholds_passed: bool = Field(description="所有阈值是否通过")
    thresholds_detail: Dict[str, bool] = Field(
        default_factory=dict, description="各阈值通过详情"
    )

    # 原始数据
    raw_metrics: Dict[str, Any] = Field(
        default_factory=dict, description="k6 原始指标数据"
    )


class WorkflowRunStatus(BaseModel):
    """GitHub Actions Workflow 运行状态模型。"""

    run_id: int = Field(description="Workflow 运行 ID")
    status: str = Field(description="运行状态：queued / in_progress / completed")
    conclusion: Optional[str] = Field(
        default=None,
        description="结论：success / failure / cancelled / skipped / timed_out",
    )
    html_url: str = Field(description="Workflow 运行页面 URL")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="最后更新时间")
    duration_seconds: Optional[float] = Field(
        default=None, description="运行耗时（秒），completed 后才有值"
    )


class PipelineResult(BaseModel):
    """完整性能测试流水线执行结果。"""

    success: bool = Field(description="流水线是否成功完成")
    test_config: Optional[K6TestConfig] = Field(default=None, description="测试配置")
    workflow_run: Optional[WorkflowRunStatus] = Field(
        default=None, description="Workflow 运行状态"
    )
    report_summary: Optional[K6ReportSummary] = Field(
        default=None, description="测试报告摘要"
    )
    script_path: Optional[str] = Field(default=None, description="上传的脚本路径")
    report_path: Optional[str] = Field(default=None, description="报告路径")
    pr_url: Optional[str] = Field(default=None, description="优化建议 PR URL")
    llm_analysis: Optional[str] = Field(default=None, description="LLM 分析结果 JSON")
    error_message: Optional[str] = Field(default=None, description="失败原因")


class AnalysisResult(BaseModel):
    """报告分析结果。"""

    overall_assessment: Literal["PASS", "WARN", "FAIL"] = Field(description="总体评估")
    performance_score: int = Field(ge=0, le=100, description="性能评分（0-100）")
    key_findings: List[str] = Field(default_factory=list, description="关键发现列表")
    bottlenecks: List[Dict[str, Any]] = Field(
        default_factory=list, description="性能瓶颈列表"
    )
    recommendations: List[Dict[str, Any]] = Field(
        default_factory=list, description="优化建议列表（按优先级排序）"
    )
    optimized_script: Optional[str] = Field(
        default=None, description="优化后的完整脚本"
    )


class ComparisonResult(BaseModel):
    """两次测试对比结果。"""

    baseline_name: str = Field(description="基准测试名称")
    current_name: str = Field(description="当前测试名称")
    improved_metrics: List[str] = Field(default_factory=list, description="改善的指标")
    degraded_metrics: List[str] = Field(default_factory=list, description="退化的指标")
    unchanged_metrics: List[str] = Field(default_factory=list, description="无变化的指标")
    delta_p95_ms: float = Field(description="p95 响应时间差值（ms），正值表示退化")
    delta_error_rate: float = Field(description="错误率差值，正值表示退化")
    delta_rps: float = Field(description="RPS 差值，正值表示改善")
    summary: str = Field(description="对比摘要描述")
