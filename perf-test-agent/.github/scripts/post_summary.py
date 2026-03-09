#!/usr/bin/env python3
"""
.github/scripts/post_summary.py
生成 GitHub Actions Job Summary - 将 k6 报告摘要写入 $GITHUB_STEP_SUMMARY。
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_report(path: str) -> dict | None:
    """加载 k6 JSON 报告，不存在时返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _val(data: dict, metric: str, stat: str, default: float = 0.0) -> float:
    m = data.get("metrics", {}).get(metric, {})
    if isinstance(m, dict):
        return float(m.get("values", m).get(stat, default))
    return default


def generate_summary(
    report_data: dict,
    test_name: str,
    run_url: str,
) -> str:
    """生成 Markdown 格式的 Job Summary。"""
    avg = _val(report_data, "http_req_duration", "avg")
    p90 = _val(report_data, "http_req_duration", "p(90)")
    p95 = _val(report_data, "http_req_duration", "p(95)")
    p99 = _val(report_data, "http_req_duration", "p(99)")
    max_ms = _val(report_data, "http_req_duration", "max")
    rps = _val(report_data, "http_reqs", "rate")
    total_reqs = int(_val(report_data, "http_reqs", "count"))
    error_rate = _val(report_data, "http_req_failed", "rate")
    vus_max = int(_val(report_data, "vus_max", "value"))

    thresholds = report_data.get("thresholds", {})
    all_passed = True
    threshold_rows = ""
    for name, thr in thresholds.items():
        ok = bool(thr.get("ok", True)) if isinstance(thr, dict) else bool(thr)
        if not ok:
            all_passed = False
        icon = "✅" if ok else "❌"
        threshold_rows += f"| {name} | {icon} {'PASS' if ok else 'FAIL'} |\n"

    overall_icon = "✅" if all_passed else "❌"
    p95_icon = "✅" if p95 < 500 else ("⚠️" if p95 < 1000 else "❌")
    error_icon = "✅" if error_rate < 0.01 else "❌"

    lines = [
        f"## {overall_icon} K6 Performance Test Report: `{test_name}`",
        "",
        f"> 🔗 [View Full Run]({run_url})",
        "",
        "### 📊 Key Metrics",
        "",
        "| Metric | Value | Status |",
        "|--------|-------|--------|",
        f"| P95 Response Time | `{p95:.1f} ms` | {p95_icon} |",
        f"| P99 Response Time | `{p99:.1f} ms` | - |",
        f"| Avg Response Time | `{avg:.1f} ms` | - |",
        f"| Max Response Time | `{max_ms:.1f} ms` | - |",
        f"| Error Rate | `{error_rate:.3%}` | {error_icon} |",
        f"| RPS | `{rps:.1f} req/s` | - |",
        f"| Total Requests | `{total_reqs}` | - |",
        f"| Peak VUs | `{vus_max}` | - |",
        "",
    ]

    if threshold_rows:
        lines += [
            "### 📋 Threshold Results",
            "",
            "| Threshold | Result |",
            "|-----------|--------|",
            threshold_rows,
        ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 GitHub Actions Job Summary")
    parser.add_argument("--report", required=True, help="k6 JSON summary 报告路径")
    parser.add_argument("--test-name", default="k6-test", help="测试名称")
    parser.add_argument("--run-url", default="#", help="GitHub Actions Run URL")
    args = parser.parse_args()

    report_data = load_report(args.report)
    if report_data is None:
        print(f"[WARN] 报告文件不存在，跳过 summary 生成: {args.report}", file=sys.stderr)
        # 写入简单提示到 summary
        summary_content = f"## ⚠️ K6 Report Not Found\n\n报告文件不存在: `{args.report}`\n"
    else:
        summary_content = generate_summary(
            report_data=report_data,
            test_name=args.test_name,
            run_url=args.run_url,
        )

    # 写入 GitHub Actions Job Summary
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(summary_content)
        print("✅ Job Summary 已写入")
    else:
        # 非 GitHub Actions 环境，直接输出到 stdout
        print(summary_content)


if __name__ == "__main__":
    main()
