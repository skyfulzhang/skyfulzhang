#!/usr/bin/env python3
"""
.github/scripts/generate_html_report.py
将 k6 JSON summary 转换为包含 Chart.js 图表的美观 HTML 报告。
在 GitHub Actions workflow 中使用，依赖 jinja2。
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>K6 Performance Report - {test_name}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f0f2f5; color: #333; }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
    .subtitle {{ color: #666; margin-bottom: 24px; font-size: .9rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
              gap: 16px; margin-bottom: 24px; }}
    .card {{ background: #fff; border-radius: 8px; padding: 20px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .card .label {{ font-size: .75rem; text-transform: uppercase;
                    letter-spacing: .05em; color: #888; margin-bottom: 6px; }}
    .card .value {{ font-size: 1.5rem; font-weight: 700; }}
    .card.pass .value {{ color: #22c55e; }}
    .card.warn .value {{ color: #f59e0b; }}
    .card.fail .value {{ color: #ef4444; }}
    .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px;
               margin-bottom: 24px; }}
    .chart-box {{ background: #fff; border-radius: 8px; padding: 20px;
                  box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .chart-box h3 {{ font-size: 1rem; margin-bottom: 16px; color: #555; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }}
    th {{ background: #f8f9fa; padding: 12px 16px; text-align: left;
          font-size: .8rem; text-transform: uppercase; color: #666; }}
    td {{ padding: 12px 16px; border-top: 1px solid #f0f2f5; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px;
              font-size: .75rem; font-weight: 600; }}
    .badge-pass {{ background: #dcfce7; color: #166534; }}
    .badge-fail {{ background: #fee2e2; color: #991b1b; }}
    .meta {{ background: #fff; border-radius: 8px; padding: 20px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }}
    .meta table {{ box-shadow: none; margin: 0; }}
    footer {{ text-align: center; color: #aaa; font-size: .8rem;
              margin-top: 16px; padding-bottom: 24px; }}
  </style>
</head>
<body>
<div class="container">
  <h1>⚡ K6 Performance Test Report</h1>
  <p class="subtitle">
    Test: <strong>{test_name}</strong> &nbsp;|&nbsp;
    Run ID: <a href="{run_url}">{run_id}</a> &nbsp;|&nbsp;
    Generated: {generated_at}
  </p>

  <!-- KPI 卡片 -->
  <div class="cards">
    <div class="card {threshold_class}">
      <div class="label">阈值状态</div>
      <div class="value">{threshold_status}</div>
    </div>
    <div class="card {p95_class}">
      <div class="label">P95 响应时间</div>
      <div class="value">{p95_ms:.0f} ms</div>
    </div>
    <div class="card {error_class}">
      <div class="label">错误率</div>
      <div class="value">{error_rate_pct:.2f}%</div>
    </div>
    <div class="card">
      <div class="label">RPS</div>
      <div class="value">{rps:.1f}</div>
    </div>
    <div class="card">
      <div class="label">总请求数</div>
      <div class="value">{total_reqs}</div>
    </div>
    <div class="card">
      <div class="label">峰值 VUs</div>
      <div class="value">{vus_max}</div>
    </div>
  </div>

  <!-- 图表 -->
  <div class="charts">
    <div class="chart-box">
      <h3>📊 响应时间分布 (ms)</h3>
      <canvas id="rtChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>🔴 成功率 vs 错误率</h3>
      <canvas id="errChart"></canvas>
    </div>
  </div>

  <!-- 阈值详情 -->
  <h3 style="margin-bottom:12px;color:#555;">📋 阈值检查详情</h3>
  <table>
    <thead><tr><th>指标</th><th>状态</th></tr></thead>
    <tbody>
    {threshold_rows}
    </tbody>
  </table>

  <!-- 测试元数据 -->
  <div class="meta">
    <h3 style="margin-bottom:12px;color:#555;">ℹ️ 测试配置</h3>
    <table>
      <tbody>
        <tr><td><strong>平均响应时间</strong></td><td>{avg_ms:.1f} ms</td></tr>
        <tr><td><strong>P90 响应时间</strong></td><td>{p90_ms:.1f} ms</td></tr>
        <tr><td><strong>P99 响应时间</strong></td><td>{p99_ms:.1f} ms</td></tr>
        <tr><td><strong>最大响应时间</strong></td><td>{max_ms:.1f} ms</td></tr>
        <tr><td><strong>数据接收</strong></td><td>{data_received_mb:.2f} MB</td></tr>
      </tbody>
    </table>
  </div>

  <footer>由 perf-test-agent 自动生成 · {generated_at}</footer>
</div>

<script>
new Chart(document.getElementById('rtChart'), {{
  type: 'bar',
  data: {{
    labels: ['Avg', 'P90', 'P95', 'P99', 'Max'],
    datasets: [{{
      label: '响应时间 (ms)',
      data: [{avg_ms:.1f}, {p90_ms:.1f}, {p95_ms:.1f}, {p99_ms:.1f}, {max_ms:.1f}],
      backgroundColor: ['#60a5fa','#34d399','#f59e0b','#f87171','#a78bfa'],
    }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
}});

new Chart(document.getElementById('errChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['成功', '失败'],
    datasets: [{{
      data: [{success_rate:.4f}, {error_rate:.4f}],
      backgroundColor: ['#22c55e', '#ef4444'],
    }}]
  }},
  options: {{ responsive: true }}
}});
</script>
</body>
</html>"""


def load_report(json_path: str) -> dict:
    """加载 k6 JSON 报告文件。"""
    path = Path(json_path)
    if not path.exists():
        print(f"[ERROR] 报告文件不存在: {json_path}", file=sys.stderr)
        sys.exit(1)

    with path.open(encoding="utf-8") as f:
        return json.load(f)


def extract_metric(data: dict, metric_name: str, stat: str, default: float = 0.0) -> float:
    """安全提取 k6 指标统计值。"""
    m = data.get("metrics", {}).get(metric_name, {})
    if isinstance(m, dict):
        values = m.get("values", m)
        return float(values.get(stat, default))
    return default


def generate_html(report_data: dict, test_name: str, run_id: str, run_url: str) -> str:
    """根据报告数据渲染 HTML 模板。"""
    avg_ms = extract_metric(report_data, "http_req_duration", "avg")
    p90_ms = extract_metric(report_data, "http_req_duration", "p(90)")
    p95_ms = extract_metric(report_data, "http_req_duration", "p(95)")
    p99_ms = extract_metric(report_data, "http_req_duration", "p(99)")
    max_ms = extract_metric(report_data, "http_req_duration", "max")
    rps = extract_metric(report_data, "http_reqs", "rate")
    total_reqs = int(extract_metric(report_data, "http_reqs", "count"))
    error_rate = extract_metric(report_data, "http_req_failed", "rate")
    data_received = extract_metric(report_data, "data_received", "count")
    vus_max = int(extract_metric(report_data, "vus_max", "value"))

    # 阈值
    thresholds = report_data.get("thresholds", {})
    all_passed = True
    threshold_rows_html = ""
    for name, thr in thresholds.items():
        if isinstance(thr, dict):
            passed = bool(thr.get("ok", True))
        else:
            passed = bool(thr)
        if not passed:
            all_passed = False
        badge_class = "badge-pass" if passed else "badge-fail"
        badge_text = "PASS" if passed else "FAIL"
        threshold_rows_html += (
            f"<tr><td>{name}</td><td>"
            f"<span class='badge {badge_class}'>{badge_text}</span></td></tr>\n"
        )

    if not threshold_rows_html:
        threshold_rows_html = "<tr><td colspan='2' style='text-align:center;color:#aaa;'>暂无阈值配置</td></tr>"

    # 评级颜色
    threshold_class = "pass" if all_passed else "fail"
    threshold_status = "✅ PASS" if all_passed else "❌ FAIL"
    p95_class = "pass" if p95_ms < 500 else ("warn" if p95_ms < 1000 else "fail")
    error_class = "pass" if error_rate < 0.01 else "fail"

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return HTML_TEMPLATE.format(
        test_name=test_name,
        run_id=run_id,
        run_url=run_url,
        generated_at=generated_at,
        threshold_class=threshold_class,
        threshold_status=threshold_status,
        p95_class=p95_class,
        error_class=error_class,
        p95_ms=p95_ms,
        error_rate_pct=error_rate * 100,
        rps=rps,
        total_reqs=total_reqs,
        vus_max=vus_max,
        avg_ms=avg_ms,
        p90_ms=p90_ms,
        p99_ms=p99_ms,
        max_ms=max_ms,
        data_received_mb=data_received / 1024 / 1024,
        threshold_rows=threshold_rows_html,
        success_rate=max(0.0, 1.0 - error_rate),
        error_rate=error_rate,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 k6 HTML 性能测试报告")
    parser.add_argument("--json", required=True, help="k6 JSON summary 报告路径")
    parser.add_argument("--output", required=True, help="输出 HTML 文件路径")
    parser.add_argument("--test-name", default="k6-test", help="测试名称")
    parser.add_argument("--run-id", default="", help="GitHub Actions Run ID")
    parser.add_argument("--run-url", default="#", help="GitHub Actions Run URL")
    args = parser.parse_args()

    report_data = load_report(args.json)
    html = generate_html(
        report_data=report_data,
        test_name=args.test_name,
        run_id=args.run_id,
        run_url=args.run_url,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    print(f"✅ HTML 报告已生成: {args.output}")


if __name__ == "__main__":
    main()
