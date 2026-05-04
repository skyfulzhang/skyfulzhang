"""可观测性与追踪模块 - 彩色控制台输出 + 结构化日志 + HTML报告"""
from __future__ import annotations
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from loguru import logger

if TYPE_CHECKING:
    from models.chain import ChainDefinition, ChainResult, StepResult
    from models.step import StepDefinition
    from core.context import ExecutionContext

from config import config

# 初始化 loguru 日志
logger.remove()
logger.add(
    config.LOG_FILE,
    level=config.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    rotation="10 MB",
    encoding="utf-8",
)
logger.add(
    lambda msg: None,  # 控制台由 rich 处理
    level=config.LOG_LEVEL,
    format="{message}",
)

console = Console()


class ExecutionTracer:
    """
    链路执行追踪，实时输出 + 最终报告
    - 彩色控制台输出（rich 库）
    - 结构化 JSON 日志
    - 执行时间线
    - 失败定位（哪步失败、哪个断言失败、失败原因）
    - 生成 HTML 执行报告
    """

    def on_chain_start(self, chain: "ChainDefinition", context: "ExecutionContext") -> None:
        """链路开始回调"""
        total_steps = len(chain.steps)
        panel = Panel(
            f"[bold cyan]🔗 链路执行开始: {chain.name}[/bold cyan]\n"
            f"[dim]chain_id: {chain.chain_id} | 步骤数: {total_steps}[/dim]\n"
            f"[dim]{chain.description}[/dim]",
            box=box.DOUBLE,
            style="bold blue",
        )
        console.print(panel)
        logger.info(f"链路开始: {chain.chain_id} - {chain.name}")

    def on_step_start(self, step: "StepDefinition", request_data: dict) -> None:
        """步骤开始回调"""
        method = request_data.get("method", "")
        url = request_data.get("url", "")
        body = request_data.get("body") or request_data.get("json", {})
        params = request_data.get("params", {})

        console.print(f"\n[bold yellow]🚀 {step.name}[/bold yellow] [dim]({step.step_id})[/dim]")
        console.print(f"  [cyan]➤[/cyan] [bold]{method}[/bold] {url}")

        if params:
            console.print(f"  [cyan]➤[/cyan] Params: {json.dumps(params, ensure_ascii=False)}")
        if body:
            # 脱敏处理：password 字段显示 ****
            safe_body = self._mask_sensitive(body)
            console.print(f"  [cyan]➤[/cyan] Body: {json.dumps(safe_body, ensure_ascii=False, default=str)}")

        logger.info(f"步骤开始: {step.step_id} - {step.name} | {method} {url}")

    def on_step_end(self, step_result: "StepResult") -> None:
        """步骤结束回调"""
        status = step_result.status
        duration = step_result.duration_ms
        resp = step_result.response

        if status == "success":
            status_icon = "✅"
            status_color = "green"
        elif status == "skipped":
            status_icon = "⏭️"
            status_color = "yellow"
        else:
            status_icon = "❌"
            status_color = "red"

        console.print(
            f"  [{status_color}]{status_icon} {resp.status_code}[/{status_color}]  "
            f"[dim]耗时: {duration:.0f}ms[/dim]"
        )

        # 打印提取变量
        if step_result.extractions:
            parts = []
            for k, v in step_result.extractions.items():
                val_str = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
                parts.append(f"{k}={val_str}")
            console.print(f"  [magenta]📤 提取变量:[/magenta] {', '.join(parts)}")

        # 打印断言结果
        if step_result.assertions:
            passed_count = sum(1 for a in step_result.assertions if a.passed)
            total_count = len(step_result.assertions)
            for assertion in step_result.assertions:
                if assertion.passed:
                    console.print(f"  [green]  ✅ 断言通过: {assertion.name}[/green]")
                else:
                    console.print(
                        f"  [red]  ❌ 断言失败: {assertion.name}[/red] "
                        f"[dim]期望={assertion.expected}, 实际={assertion.actual}[/dim]"
                    )
                    if assertion.error:
                        console.print(f"      [dim red]{assertion.error}[/dim red]")

        # 错误信息
        if step_result.error:
            console.print(f"  [red]  ⚠️  错误: {step_result.error}[/red]")

        logger.info(
            f"步骤结束: {step_result.step_id} | 状态={status} | "
            f"耗时={duration:.0f}ms | 断言={sum(1 for a in step_result.assertions if a.passed)}/{len(step_result.assertions)}"
        )

    def on_chain_end(self, result: "ChainResult") -> None:
        """链路结束回调"""
        self.print_summary(result)
        logger.info(
            f"链路结束: {result.chain_id} | 状态={result.status} | "
            f"耗时={result.total_duration_ms:.0f}ms"
        )

    def print_summary(self, result: "ChainResult") -> None:
        """打印执行摘要"""
        summary = result.summary
        is_success = result.status == "success"
        status_text = "✅ SUCCESS" if is_success else "❌ FAILED"
        status_style = "bold green" if is_success else "bold red"

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Key", style="dim")
        table.add_column("Value")

        table.add_row("链路名称", result.chain_name)
        table.add_row("执行状态", Text(status_text, style=status_style))
        table.add_row("总耗时", f"{result.total_duration_ms:.0f}ms")
        table.add_row(
            "步骤统计",
            f"{summary.get('success_steps', 0)}/{summary.get('total_steps', 0)} 成功, "
            f"{summary.get('failed_steps', 0)} 失败, "
            f"{summary.get('skipped_steps', 0)} 跳过",
        )
        table.add_row(
            "断言统计",
            f"{summary.get('passed_assertions', 0)}/{summary.get('total_assertions', 0)} 通过",
        )
        table.add_row("开始时间", result.started_at)
        table.add_row("结束时间", result.finished_at)

        console.print()
        console.rule("[bold]执行摘要", style="blue")
        console.print(table)
        console.rule(style="blue")

        # 失败详情
        if not is_success:
            for step_result in result.step_results:
                if step_result.status == "failed":
                    console.print(
                        f"\n[red]❌ 步骤失败: {step_result.name} ({step_result.step_id})[/red]"
                    )
                    if step_result.error:
                        console.print(f"   原因: {step_result.error}")
                    for assertion in step_result.assertions:
                        if not assertion.passed:
                            console.print(
                                f"   断言失败: {assertion.name} | "
                                f"期望={assertion.expected}, 实际={assertion.actual}"
                            )

    def generate_report(self, result: "ChainResult", output_path: str | None = None) -> str:
        """生成 HTML 执行报告，返回报告文件路径"""
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(config.REPORT_DIR, f"report_{result.chain_id}_{ts}.html")

        html = self._build_html_report(result)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        console.print(f"\n[green]📄 HTML 报告已生成: {output_path}[/green]")
        return output_path

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    def _mask_sensitive(self, data: dict) -> dict:
        """脱敏敏感字段"""
        sensitive_keys = {"password", "passwd", "secret", "token", "Authorization"}
        result = {}
        for k, v in data.items():
            if k.lower() in {s.lower() for s in sensitive_keys}:
                result[k] = "****"
            elif isinstance(v, dict):
                result[k] = self._mask_sensitive(v)
            else:
                result[k] = v
        return result

    def _build_html_report(self, result: "ChainResult") -> str:
        """构建 HTML 报告内容"""
        is_success = result.status == "success"
        status_color = "#28a745" if is_success else "#dc3545"
        status_text = "✅ SUCCESS" if is_success else "❌ FAILED"

        steps_html = ""
        for i, step in enumerate(result.step_results, 1):
            step_color = "#28a745" if step.status == "success" else "#dc3545" if step.status == "failed" else "#ffc107"
            step_icon = "✅" if step.status == "success" else "❌" if step.status == "failed" else "⏭"

            assertions_html = ""
            for a in step.assertions:
                a_color = "#28a745" if a.passed else "#dc3545"
                a_icon = "✅" if a.passed else "❌"
                assertions_html += f"""
                <tr>
                    <td style="color:{a_color}">{a_icon} {a.name}</td>
                    <td>{a.operator}</td>
                    <td>{a.expected}</td>
                    <td>{a.actual}</td>
                </tr>"""

            extracts_html = ""
            for k, v in step.extractions.items():
                extracts_html += f"<li><b>{k}</b> = {v}</li>"

            steps_html += f"""
            <div class="step-card" style="border-left: 4px solid {step_color};">
                <h3>{step_icon} Step {i}: {step.name} <small style="color:{step_color}">({step.status})</small></h3>
                <p><b>接口:</b> {step.api_id} | <b>耗时:</b> {step.duration_ms:.0f}ms</p>
                <p><b>请求:</b> {step.request.method} {step.request.url}</p>
                <p><b>响应状态:</b> {step.response.status_code}</p>
                {'<p><b>错误:</b> <span style="color:red">' + step.error + '</span></p>' if step.error else ''}
                {'<h4>提取变量</h4><ul>' + extracts_html + '</ul>' if extracts_html else ''}
                {'<h4>断言结果</h4><table><tr><th>断言</th><th>操作符</th><th>期望</th><th>实际</th></tr>' + assertions_html + '</table>' if assertions_html else ''}
            </div>"""

        summary = result.summary
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>链路执行报告 - {result.chain_name}</title>
<style>
body {{ font-family: "PingFang SC", "Microsoft YaHei", sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
h1 {{ color: {status_color}; }}
.summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 20px 0; }}
.summary-card {{ background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; }}
.summary-card h2 {{ margin: 0; color: {status_color}; }}
.step-card {{ background: #fff; margin: 10px 0; padding: 15px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
th {{ background: #f8f9fa; }}
</style>
</head>
<body>
<div class="container">
<h1>🔗 链路执行报告: {result.chain_name}</h1>
<p style="color:{status_color}; font-size: 1.2em; font-weight: bold;">{status_text}</p>
<div class="summary">
    <div class="summary-card"><h2>{result.total_duration_ms:.0f}ms</h2><p>总耗时</p></div>
    <div class="summary-card"><h2>{summary.get('success_steps', 0)}/{summary.get('total_steps', 0)}</h2><p>步骤成功</p></div>
    <div class="summary-card"><h2>{summary.get('passed_assertions', 0)}/{summary.get('total_assertions', 0)}</h2><p>断言通过</p></div>
</div>
<p><b>开始时间:</b> {result.started_at} | <b>结束时间:</b> {result.finished_at}</p>
<h2>步骤详情</h2>
{steps_html}
</div>
</body>
</html>"""
