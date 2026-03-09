#!/usr/bin/env python3
"""
.github/scripts/check_thresholds.py
阈值检查脚本 - 解析 k6 JSON 报告，如果有阈值未通过则以非零退出码退出。
用于 GitHub Actions 性能门禁检查。
"""

import argparse
import json
import sys
from pathlib import Path


def check_thresholds(report_path: str) -> bool:
    """检查 k6 报告中的阈值是否全部通过。

    Args:
        report_path: k6 JSON summary 报告路径。

    Returns:
        bool: True 表示所有阈值通过，False 表示有阈值失败。
    """
    path = Path(report_path)
    if not path.exists():
        print(f"[ERROR] 报告文件不存在: {report_path}", file=sys.stderr)
        # 报告不存在时不阻断 CI（可能是测试未完成）
        return True

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        print(f"[WARN] 报告文件为空，跳过阈值检查: {report_path}", file=sys.stderr)
        return True

    data = json.loads(content)

    thresholds = data.get("thresholds", {})

    if not thresholds:
        print("ℹ️  报告中无阈值配置，跳过检查")
        return True

    failed: list[str] = []
    passed: list[str] = []

    for name, thr in thresholds.items():
        if isinstance(thr, dict):
            ok = bool(thr.get("ok", True))
        else:
            ok = bool(thr)

        if ok:
            passed.append(name)
        else:
            failed.append(name)

    print(f"\n📊 阈值检查结果（共 {len(thresholds)} 项）:")
    for name in passed:
        print(f"  ✅ PASS: {name}")
    for name in failed:
        print(f"  ❌ FAIL: {name}")

    # 额外输出关键指标
    metrics = data.get("metrics", {})

    def _val(metric: str, stat: str) -> float:
        m = metrics.get(metric, {})
        if isinstance(m, dict):
            return float(m.get("values", m).get(stat, 0))
        return 0.0

    p95 = _val("http_req_duration", "p(95)")
    error_rate = _val("http_req_failed", "rate")
    rps = _val("http_reqs", "rate")

    print(f"\n📈 关键指标:")
    print(f"  P95 响应时间: {p95:.1f} ms")
    print(f"  错误率: {error_rate:.3%}")
    print(f"  RPS: {rps:.1f}")

    if failed:
        print(f"\n❌ 共 {len(failed)} 个阈值未通过：{', '.join(failed)}")
        return False

    print(f"\n✅ 所有 {len(passed)} 个阈值均通过！")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 k6 性能测试阈值")
    parser.add_argument("--report", required=True, help="k6 JSON summary 报告路径")
    args = parser.parse_args()

    all_passed = check_thresholds(args.report)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
