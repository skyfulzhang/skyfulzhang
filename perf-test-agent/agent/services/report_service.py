"""
agent/services/report_service.py
测试报告解析服务 - 解析 k6 JSON 报告、生成 HTML 报告、对比测试结果。
"""

import json
from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, BaseLoader

from agent.models.test_config import (
    AnalysisResult,
    ComparisonResult,
    K6ReportSummary,
)
from agent.utils.logger import get_logger

logger = get_logger(__name__)

# ── HTML 报告 Jinja2 模板 ─────────────────────────────────────────────────────
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>K6 性能测试报告 - {{ test_name }}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f0f2f5; color: #333; }
    .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 1.8rem; margin-bottom: 4px; }
    .subtitle { color: #666; margin-bottom: 24px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
             gap: 16px; margin-bottom: 24px; }
    .card { background: #fff; border-radius: 8px; padding: 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .card .label { font-size: .75rem; text-transform: uppercase;
                   letter-spacing: .05em; color: #888; margin-bottom: 6px; }
    .card .value { font-size: 1.6rem; font-weight: 700; }
    .card.pass .value { color: #22c55e; }
    .card.warn .value { color: #f59e0b; }
    .card.fail .value { color: #ef4444; }
    .charts { display: grid; grid-template-columns: 2fr 1fr; gap: 16px;
              margin-bottom: 24px; }
    .chart-box { background: #fff; border-radius: 8px; padding: 20px;
                 box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .chart-box h3 { font-size: 1rem; margin-bottom: 16px; color: #555; }
    table { width: 100%; border-collapse: collapse; background: #fff;
            border-radius: 8px; overflow: hidden;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    th { background: #f8f9fa; padding: 12px 16px; text-align: left;
         font-size: .8rem; text-transform: uppercase; color: #666; }
    td { padding: 12px 16px; border-top: 1px solid #f0f2f5; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
             font-size: .75rem; font-weight: 600; }
    .badge-pass { background: #dcfce7; color: #166534; }
    .badge-fail { background: #fee2e2; color: #991b1b; }
    footer { text-align: center; color: #aaa; font-size: .8rem;
             margin-top: 32px; padding-bottom: 24px; }
  </style>
</head>
<body>
<div class="container">
  <h1>⚡ K6 性能测试报告</h1>
  <p class="subtitle">{{ test_name }} &nbsp;|&nbsp; {{ start_time }} &nbsp;→&nbsp; {{ end_time }}
    &nbsp;|&nbsp; 耗时 {{ "%.1f"|format(duration_seconds) }}s</p>

  <!-- KPI 卡片 -->
  <div class="cards">
    <div class="card {{ 'pass' if thresholds_passed else 'fail' }}">
      <div class="label">阈值状态</div>
      <div class="value">{{ '✅ PASS' if thresholds_passed else '❌ FAIL' }}</div>
    </div>
    <div class="card {{ 'pass' if http_req_duration_p95 < 500 else 'warn' if http_req_duration_p95 < 1000 else 'fail' }}">
      <div class="label">P95 响应时间</div>
      <div class="value">{{ "%.0f"|format(http_req_duration_p95) }} ms</div>
    </div>
    <div class="card {{ 'pass' if http_req_failed_rate < 0.01 else 'fail' }}">
      <div class="label">错误率</div>
      <div class="value">{{ "%.2f"|format(http_req_failed_rate * 100) }}%</div>
    </div>
    <div class="card">
      <div class="label">RPS</div>
      <div class="value">{{ "%.1f"|format(http_reqs_rate) }}</div>
    </div>
    <div class="card">
      <div class="label">总请求数</div>
      <div class="value">{{ http_reqs_total }}</div>
    </div>
    <div class="card">
      <div class="label">峰值 VUs</div>
      <div class="value">{{ vus_max }}</div>
    </div>
  </div>

  <!-- 图表区域 -->
  <div class="charts">
    <div class="chart-box">
      <h3>📊 响应时间分布（ms）</h3>
      <canvas id="rtChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>🔴 错误率</h3>
      <canvas id="errChart"></canvas>
    </div>
  </div>

  <!-- 阈值详情表格 -->
  <h3 style="margin-bottom:12px; color:#555;">📋 阈值检查详情</h3>
  <table>
    <thead><tr><th>指标</th><th>状态</th></tr></thead>
    <tbody>
    {% for name, passed in thresholds_detail.items() %}
      <tr>
        <td>{{ name }}</td>
        <td><span class="badge {{ 'badge-pass' if passed else 'badge-fail' }}">
          {{ 'PASS' if passed else 'FAIL' }}</span></td>
      </tr>
    {% else %}
      <tr><td colspan="2" style="text-align:center;color:#aaa;">暂无阈值配置</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <footer>由 perf-test-agent 自动生成 &nbsp;·&nbsp; {{ generated_at }}</footer>
</div>

<script>
// 响应时间柱状图
new Chart(document.getElementById('rtChart'), {
  type: 'bar',
  data: {
    labels: ['Avg', 'P90', 'P95', 'P99', 'Max'],
    datasets: [{
      label: '响应时间 (ms)',
      data: [{{ "%.1f"|format(http_req_duration_avg) }},
             {{ "%.1f"|format(http_req_duration_p90) }},
             {{ "%.1f"|format(http_req_duration_p95) }},
             {{ "%.1f"|format(http_req_duration_p99) }},
             {{ "%.1f"|format(http_req_duration_max) }}],
      backgroundColor: ['#60a5fa','#34d399','#f59e0b','#f87171','#a78bfa'],
    }]
  },
  options: { responsive: true, plugins: { legend: { display: false } } }
});

// 错误率饼图
new Chart(document.getElementById('errChart'), {
  type: 'doughnut',
  data: {
    labels: ['成功', '失败'],
    datasets: [{
      data: [{{ "%.4f"|format(1 - http_req_failed_rate) }},
             {{ "%.4f"|format(http_req_failed_rate) }}],
      backgroundColor: ['#22c55e', '#ef4444'],
    }]
  },
  options: { responsive: true }
});
</script>
</body>
</html>"""


class ReportService:
    """测试报告解析与生成服务。

    提供 k6 JSON 报告解析、HTML 报告生成、报告对比等功能。
    """

    def parse_json_summary(self, json_content: str) -> K6ReportSummary:
        """解析 k6 ``--summary-export`` 输出的 JSON 报告。

        Args:
            json_content: k6 summary JSON 字符串。

        Returns:
            K6ReportSummary: 结构化报告摘要对象。

        Raises:
            ValueError: JSON 格式不合法时。
        """
        try:
            data: dict[str, Any] = json.loads(json_content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无效的 JSON 报告：{exc}") from exc

        metrics = data.get("metrics", {})

        def _val(metric_name: str, stat: str = "avg", default: float = 0.0) -> float:
            """安全提取指标统计值。"""
            m = metrics.get(metric_name, {})
            if isinstance(m, dict):
                values = m.get("values", m)
                return float(values.get(stat, default))
            return default

        # 解析时间（k6 summary 中有 state.testRunDuration）
        state = data.get("state", {})
        test_run_duration_ns: float = state.get("testRunDuration", 0)
        duration_s = test_run_duration_ns / 1e9 if test_run_duration_ns > 0 else 0.0

        # 构造时间戳（k6 summary 不含绝对时间，使用当前时间作为结束时间）
        end_dt = datetime.now(tz=timezone.utc)
        from datetime import timedelta
        start_dt = end_dt - timedelta(seconds=duration_s)

        # 阈值结果
        thresholds_raw: dict[str, Any] = data.get("thresholds", {})
        thresholds_detail: dict[str, bool] = {}
        for name, thr in thresholds_raw.items():
            if isinstance(thr, dict):
                thresholds_detail[name] = bool(thr.get("ok", True))
            else:
                thresholds_detail[name] = bool(thr)
        thresholds_passed = all(thresholds_detail.values()) if thresholds_detail else True

        # http_req_duration values
        dur_values = metrics.get("http_req_duration", {}).get("values", {})
        failed_values = metrics.get("http_req_failed", {}).get("values", {})
        reqs_values = metrics.get("http_reqs", {}).get("values", {})
        data_recv = metrics.get("data_received", {}).get("values", {})
        data_sent = metrics.get("data_sent", {}).get("values", {})
        vus_values = metrics.get("vus_max", {}).get("values", {})

        summary = K6ReportSummary(
            test_name=data.get("options", {}).get("ext", {}).get(
                "loadimpact", {}
            ).get("name", "k6-test"),
            start_time=start_dt,
            end_time=end_dt,
            duration_seconds=duration_s,
            http_req_duration_avg=float(dur_values.get("avg", 0)),
            http_req_duration_p90=float(dur_values.get("p(90)", 0)),
            http_req_duration_p95=float(dur_values.get("p(95)", 0)),
            http_req_duration_p99=float(dur_values.get("p(99)", 0)),
            http_req_duration_max=float(dur_values.get("max", 0)),
            http_reqs_total=int(reqs_values.get("count", 0)),
            http_reqs_rate=float(reqs_values.get("rate", 0)),
            http_req_failed_rate=float(failed_values.get("rate", 0)),
            data_received_bytes=float(data_recv.get("count", 0)),
            data_sent_bytes=float(data_sent.get("count", 0)),
            vus_max=int(vus_values.get("value", 0)),
            thresholds_passed=thresholds_passed,
            thresholds_detail=thresholds_detail,
            raw_metrics=metrics,
        )

        logger.info(
            "report_parsed",
            test_name=summary.test_name,
            p95=summary.http_req_duration_p95,
            rps=summary.http_reqs_rate,
            error_rate=summary.http_req_failed_rate,
        )
        return summary

    def generate_html_report(
        self,
        summary: K6ReportSummary,
        script_path: str = "",
    ) -> str:
        """生成包含 Chart.js 图表的美观 HTML 报告。

        Args:
            summary: 测试报告摘要。
            script_path: 脚本路径（可选，用于报告标注）。

        Returns:
            str: HTML 报告内容。
        """
        env = Environment(loader=BaseLoader(), autoescape=True)
        template = env.from_string(_HTML_TEMPLATE)

        html = template.render(
            test_name=summary.test_name,
            start_time=summary.start_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            end_time=summary.end_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            duration_seconds=summary.duration_seconds,
            thresholds_passed=summary.thresholds_passed,
            http_req_duration_avg=summary.http_req_duration_avg,
            http_req_duration_p90=summary.http_req_duration_p90,
            http_req_duration_p95=summary.http_req_duration_p95,
            http_req_duration_p99=summary.http_req_duration_p99,
            http_req_duration_max=summary.http_req_duration_max,
            http_reqs_total=summary.http_reqs_total,
            http_reqs_rate=summary.http_reqs_rate,
            http_req_failed_rate=summary.http_req_failed_rate,
            vus_max=summary.vus_max,
            thresholds_detail=summary.thresholds_detail,
            generated_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        logger.info("html_report_generated", test_name=summary.test_name)
        return html

    def compare_reports(
        self,
        baseline: K6ReportSummary,
        current: K6ReportSummary,
    ) -> ComparisonResult:
        """对比两次测试结果，识别性能退化或改善。

        Args:
            baseline: 基准测试报告。
            current: 当前测试报告。

        Returns:
            ComparisonResult: 对比结果。
        """
        delta_p95 = current.http_req_duration_p95 - baseline.http_req_duration_p95
        delta_error = current.http_req_failed_rate - baseline.http_req_failed_rate
        delta_rps = current.http_reqs_rate - baseline.http_reqs_rate

        improved: list[str] = []
        degraded: list[str] = []
        unchanged: list[str] = []

        # p95 响应时间（delta 为正表示退化）
        if delta_p95 > 50:
            degraded.append(f"p95 响应时间增加 {delta_p95:.0f}ms")
        elif delta_p95 < -50:
            improved.append(f"p95 响应时间减少 {abs(delta_p95):.0f}ms")
        else:
            unchanged.append("p95 响应时间")

        # 错误率（delta 为正表示退化）
        if delta_error > 0.005:
            degraded.append(f"错误率上升 {delta_error:.2%}")
        elif delta_error < -0.005:
            improved.append(f"错误率下降 {abs(delta_error):.2%}")
        else:
            unchanged.append("错误率")

        # RPS（delta 为正表示改善）
        if delta_rps > 5:
            improved.append(f"RPS 提升 {delta_rps:.1f}")
        elif delta_rps < -5:
            degraded.append(f"RPS 下降 {abs(delta_rps):.1f}")
        else:
            unchanged.append("RPS")

        if degraded:
            summary = f"⚠️ 性能退化：{len(degraded)} 项指标变差，{len(improved)} 项改善"
        elif improved:
            summary = f"✅ 性能改善：{len(improved)} 项指标提升"
        else:
            summary = "📊 性能基本持平，无显著变化"

        result = ComparisonResult(
            baseline_name=baseline.test_name,
            current_name=current.test_name,
            improved_metrics=improved,
            degraded_metrics=degraded,
            unchanged_metrics=unchanged,
            delta_p95_ms=delta_p95,
            delta_error_rate=delta_error,
            delta_rps=delta_rps,
            summary=summary,
        )

        logger.info(
            "reports_compared",
            baseline=baseline.test_name,
            current=current.test_name,
            degraded=len(degraded),
            improved=len(improved),
        )
        return result

    def extract_key_metrics(self, summary: K6ReportSummary) -> dict[str, Any]:
        """提取测试报告中的关键指标字典。

        Args:
            summary: 测试报告摘要。

        Returns:
            dict: 包含 p95, p99, error_rate, rps, vus_max 等关键指标。
        """
        return {
            "test_name": summary.test_name,
            "duration_seconds": summary.duration_seconds,
            "p50_ms": summary.http_req_duration_avg,
            "p90_ms": summary.http_req_duration_p90,
            "p95_ms": summary.http_req_duration_p95,
            "p99_ms": summary.http_req_duration_p99,
            "max_ms": summary.http_req_duration_max,
            "rps": summary.http_reqs_rate,
            "total_requests": summary.http_reqs_total,
            "error_rate": summary.http_req_failed_rate,
            "error_rate_pct": round(summary.http_req_failed_rate * 100, 3),
            "vus_max": summary.vus_max,
            "data_received_mb": round(summary.data_received_bytes / 1024 / 1024, 2),
            "thresholds_passed": summary.thresholds_passed,
            "thresholds_detail": summary.thresholds_detail,
        }
