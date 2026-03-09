"""
agent/tools/report_analyzer.py
报告分析工具集 - LangChain StructuredTool 封装，提供 JSON 报告解析和分析。
"""

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.services.report_service import ReportService
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_report_service = ReportService()


# ── Input Schema Models ───────────────────────────────────────────────────────

class AnalyzeReportInput(BaseModel):
    """分析报告的输入参数。"""
    json_content: str = Field(description="k6 summary JSON 报告内容")


class CompareReportsInput(BaseModel):
    """对比两份报告的输入参数。"""
    baseline_json: str = Field(description="基线测试报告 JSON 内容")
    current_json: str = Field(description="当前测试报告 JSON 内容")


class GenerateHtmlInput(BaseModel):
    """生成 HTML 报告的输入参数。"""
    json_content: str = Field(description="k6 summary JSON 报告内容")
    script_path: str = Field(default="", description="对应脚本路径（用于报告标注）")


class ExtractMetricsInput(BaseModel):
    """提取关键指标的输入参数。"""
    json_content: str = Field(description="k6 summary JSON 报告内容")


# ── Tools ─────────────────────────────────────────────────────────────────────

def _analyze_performance_report(json_content: str) -> str:
    """解析并格式化 k6 性能测试报告。"""
    try:
        summary = _report_service.parse_json_summary(json_content)
        metrics = _report_service.extract_key_metrics(summary)

        # 性能等级评估
        p95 = metrics["p95_ms"]
        error_rate = metrics["error_rate"]
        thresholds_passed = metrics["thresholds_passed"]

        if thresholds_passed and p95 < 300 and error_rate < 0.005:
            grade = "🟢 PASS（优秀）"
        elif thresholds_passed and p95 < 500 and error_rate < 0.01:
            grade = "🟡 PASS（达标）"
        elif not thresholds_passed or error_rate > 0.05:
            grade = "🔴 FAIL（不合格）"
        else:
            grade = "🟠 WARN（需关注）"

        return (
            f"📊 **性能测试报告分析**\n\n"
            f"**测试名称**: {metrics['test_name']}\n"
            f"**总体评级**: {grade}\n\n"
            f"**响应时间指标**:\n"
            f"  - 平均: {metrics['p50_ms']:.1f} ms\n"
            f"  - P90: {metrics['p90_ms']:.1f} ms\n"
            f"  - P95: {metrics['p95_ms']:.1f} ms\n"
            f"  - P99: {metrics['p99_ms']:.1f} ms\n"
            f"  - 最大: {metrics['max_ms']:.1f} ms\n\n"
            f"**吞吐量**:\n"
            f"  - RPS: {metrics['rps']:.1f} 请求/秒\n"
            f"  - 总请求: {metrics['total_requests']} 次\n\n"
            f"**可靠性**:\n"
            f"  - 错误率: {metrics['error_rate_pct']:.3f}%\n\n"
            f"**资源**:\n"
            f"  - 峰值 VUs: {metrics['vus_max']}\n"
            f"  - 数据接收: {metrics['data_received_mb']:.2f} MB\n\n"
            f"**阈值状态**: {'✅ 全部通过' if thresholds_passed else '❌ 有阈值未通过'}\n"
            + (
                "\n".join(
                    f"  - {k}: {'✅' if v else '❌'}"
                    for k, v in metrics["thresholds_detail"].items()
                )
                if metrics["thresholds_detail"]
                else "  （无阈值配置）"
            )
        )
    except Exception as exc:
        logger.error("analyze_report_error", error=str(exc))
        return f"❌ 报告分析失败: {exc!s}"


analyze_performance_report_tool = StructuredTool.from_function(
    func=_analyze_performance_report,
    name="analyze_performance_report",
    description=(
        "分析 k6 性能测试 JSON 报告，提取关键指标并给出性能评级。"
        "需要传入 k6 --summary-export 生成的 JSON 内容。"
        "返回格式化的性能摘要，包含响应时间、吞吐量、错误率、阈值状态。"
    ),
    args_schema=AnalyzeReportInput,
)


def _compare_performance_reports(baseline_json: str, current_json: str) -> str:
    """对比两份 k6 性能测试报告。"""
    try:
        baseline = _report_service.parse_json_summary(baseline_json)
        current = _report_service.parse_json_summary(current_json)
        result = _report_service.compare_reports(baseline, current)

        return (
            f"📊 **性能对比分析**\n\n"
            f"**基线**: {result.baseline_name}\n"
            f"**当前**: {result.current_name}\n\n"
            f"**对比摘要**: {result.summary}\n\n"
            f"**指标变化**:\n"
            f"  - P95 响应时间: {result.delta_p95_ms:+.1f}ms "
            f"{'⬆️退化' if result.delta_p95_ms > 0 else '⬇️改善'}\n"
            f"  - 错误率: {result.delta_error_rate:+.4f} "
            f"{'⬆️退化' if result.delta_error_rate > 0 else '⬇️改善'}\n"
            f"  - RPS: {result.delta_rps:+.1f} "
            f"{'⬆️改善' if result.delta_rps > 0 else '⬇️下降'}\n\n"
            + (
                f"✅ **改善项**: {', '.join(result.improved_metrics)}\n"
                if result.improved_metrics
                else ""
            )
            + (
                f"❌ **退化项**: {', '.join(result.degraded_metrics)}\n"
                if result.degraded_metrics
                else ""
            )
        )
    except Exception as exc:
        return f"❌ 对比报告失败: {exc!s}"


compare_performance_reports_tool = StructuredTool.from_function(
    func=_compare_performance_reports,
    name="compare_performance_reports",
    description=(
        "对比两次 k6 性能测试报告（基线 vs 当前），识别性能退化或改善。"
        "需要传入两个 k6 summary JSON 内容。"
        "返回各关键指标的变化量和趋势。"
    ),
    args_schema=CompareReportsInput,
)


def _generate_html_report(json_content: str, script_path: str = "") -> str:
    """将 JSON 报告转换为 HTML 报告。"""
    try:
        summary = _report_service.parse_json_summary(json_content)
        html = _report_service.generate_html_report(summary, script_path)
        return f"✅ HTML 报告已生成（{len(html)} 字节）。\n请将此 HTML 内容保存到报告文件中。\n\n{html}"
    except Exception as exc:
        return f"❌ HTML 报告生成失败: {exc!s}"


generate_html_report_tool = StructuredTool.from_function(
    func=_generate_html_report,
    name="generate_html_report",
    description=(
        "将 k6 JSON 测试报告转换为包含 Chart.js 图表的美观 HTML 报告。"
        "返回完整 HTML 内容，可保存到仓库供浏览器查看。"
    ),
    args_schema=GenerateHtmlInput,
)


def _extract_metrics_summary(json_content: str) -> str:
    """提取关键指标摘要（精简 JSON 格式）。"""
    try:
        import json

        summary = _report_service.parse_json_summary(json_content)
        metrics = _report_service.extract_key_metrics(summary)
        return (
            f"✅ 关键指标摘要：\n\n```json\n"
            f"{json.dumps(metrics, indent=2, ensure_ascii=False)}\n```"
        )
    except Exception as exc:
        return f"❌ 提取指标失败: {exc!s}"


extract_metrics_summary_tool = StructuredTool.from_function(
    func=_extract_metrics_summary,
    name="extract_metrics_summary",
    description=(
        "从 k6 JSON 报告中提取关键性能指标摘要（p95/p99/error_rate/rps 等）。"
        "返回精简的 JSON 格式，便于 LLM 进一步分析。"
    ),
    args_schema=ExtractMetricsInput,
)


def get_report_analyzer_tools() -> list[BaseTool]:
    """返回所有报告分析工具列表。"""
    return [
        analyze_performance_report_tool,
        compare_performance_reports_tool,
        generate_html_report_tool,
        extract_metrics_summary_tool,
    ]
