"""
agent/main.py
主入口 - CLI 和交互式对话模式，基于 Typer 构建。
"""

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="perf-agent",
    help="🚀 企业级性能测试智能体 - 基于 LangChain + k6 + GitHub Actions",
    add_completion=False,
)

console = Console()


def _get_agent(verbose: bool = False):
    """延迟初始化 Agent（避免启动时加载所有依赖）。"""
    from agent.core.agent import PerformanceTestAgent
    from agent.utils.config import get_settings
    from agent.utils.logger import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return PerformanceTestAgent(settings, verbose=verbose)


@app.command("run-test")
def run_test(
    url: str = typer.Argument(..., help="目标 URL（必填），如 https://api.example.com"),
    test_type: str = typer.Option("load", "--type", "-t", help="测试类型: load/stress/spike/soak/api"),
    requirements: str = typer.Option("", "--req", "-r", help="补充测试要求（自然语言）"),
    branch: str = typer.Option("perf-test/auto", "--branch", "-b", help="工作分支名称"),
    async_mode: bool = typer.Option(False, "--async", help="异步模式：触发后不等待结果"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细日志"),
) -> None:
    """🚀 执行完整性能测试流水线（生成脚本 → 上传 → 触发 Actions → 分析报告）。"""
    console.print(
        Panel.fit(
            f"[bold green]🚀 启动性能测试流水线[/bold green]\n"
            f"URL: [cyan]{url}[/cyan]\n"
            f"类型: [yellow]{test_type}[/yellow]\n"
            f"分支: [blue]{branch}[/blue]",
            title="perf-test-agent",
        )
    )

    try:
        agent = _get_agent(verbose=verbose)
        result = asyncio.run(
            agent.run_performance_test_pipeline(
                target_url=url,
                test_type=test_type,
                requirements=requirements,
                branch=branch,
            )
        )

        if result.success:
            console.print("[bold green]✅ 测试流水线执行成功！[/bold green]")
            if result.llm_analysis:
                console.print("\n[bold]📊 分析结果：[/bold]")
                console.print(result.llm_analysis)
            if result.pr_url:
                console.print(f"\n[bold]🔗 优化建议 PR：[/bold] {result.pr_url}")
        else:
            console.print(f"[bold red]❌ 流水线执行失败：{result.error_message}[/bold red]")
            raise typer.Exit(code=1)

    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户中断[/yellow]")
        raise typer.Exit(code=130)
    except Exception as exc:
        console.print(f"[bold red]❌ 错误：{exc!s}[/bold red]")
        if verbose:
            import traceback
            console.print(traceback.format_exc())
        raise typer.Exit(code=1)


@app.command("analyze")
def analyze(
    script_path: str = typer.Argument(..., help="脚本路径，如 k6_scripts/load_test.js"),
    branch: str = typer.Option("main", "--branch", "-b", help="分支名称"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """📊 分析已有测试报告，给出优化建议。"""
    console.print(f"[bold]📊 分析报告：[/bold] {script_path}@{branch}")

    try:
        agent = _get_agent(verbose=verbose)
        result = asyncio.run(agent.analyze_existing_report(script_path, branch))

        # 展示分析结果
        table = Table(title="性能分析结果", show_header=True)
        table.add_column("指标", style="cyan")
        table.add_column("值", style="green")

        assessment_color = {
            "PASS": "green",
            "WARN": "yellow",
            "FAIL": "red",
        }.get(result.overall_assessment, "white")

        table.add_row(
            "总体评估",
            f"[{assessment_color}]{result.overall_assessment}[/{assessment_color}]",
        )
        table.add_row("性能评分", f"{result.performance_score}/100")
        console.print(table)

        if result.key_findings:
            console.print("\n[bold]🔍 关键发现：[/bold]")
            for finding in result.key_findings:
                console.print(f"  • {finding}")

        if result.recommendations:
            console.print("\n[bold]💡 优化建议：[/bold]")
            for rec in result.recommendations[:5]:
                priority = rec.get("priority", "MEDIUM")
                title = rec.get("title", "")
                desc = rec.get("description", "")
                console.print(f"  [{priority}] {title}: {desc}")

    except Exception as exc:
        console.print(f"[bold red]❌ 分析失败：{exc!s}[/bold red]")
        raise typer.Exit(code=1)


@app.command("compare")
def compare(
    baseline_path: str = typer.Argument(..., help="基线报告路径"),
    current_path: str = typer.Argument(..., help="当前报告路径"),
    branch: str = typer.Option("main", "--branch", "-b"),
) -> None:
    """🔀 对比两个测试报告，识别性能退化。"""
    console.print(
        f"[bold]🔀 对比报告：[/bold]\n"
        f"  基线: {baseline_path}\n"
        f"  当前: {current_path}"
    )

    try:
        from agent.services.github_service import GitHubService
        from agent.services.report_service import ReportService
        from agent.utils.config import get_settings

        settings = get_settings()
        github_svc = GitHubService(settings)
        report_svc = ReportService()

        baseline_json = github_svc.get_file_content(baseline_path, branch)
        current_json = github_svc.get_file_content(current_path, branch)

        baseline = report_svc.parse_json_summary(baseline_json)
        current = report_svc.parse_json_summary(current_json)
        result = report_svc.compare_reports(baseline, current)

        console.print(f"\n[bold]📊 对比结果：[/bold] {result.summary}")
        console.print(f"  P95 变化: {result.delta_p95_ms:+.1f}ms")
        console.print(f"  错误率变化: {result.delta_error_rate:+.4f}")
        console.print(f"  RPS 变化: {result.delta_rps:+.1f}")

        if result.degraded_metrics:
            console.print(f"\n[red]❌ 退化项: {', '.join(result.degraded_metrics)}[/red]")
        if result.improved_metrics:
            console.print(f"[green]✅ 改善项: {', '.join(result.improved_metrics)}[/green]")

    except Exception as exc:
        console.print(f"[bold red]❌ 对比失败：{exc!s}[/bold red]")
        raise typer.Exit(code=1)


@app.command("interactive")
def interactive(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """💬 启动交互式智能对话模式（支持持续对话）。"""
    console.print(
        Panel.fit(
            "[bold green]💬 交互式性能测试智能体[/bold green]\n"
            "输入 [cyan]quit[/cyan] 或 [cyan]exit[/cyan] 退出\n"
            "输入 [cyan]help[/cyan] 查看常用命令示例",
            title="perf-test-agent interactive",
        )
    )

    try:
        agent = _get_agent(verbose=verbose)
    except Exception as exc:
        console.print(f"[bold red]❌ Agent 初始化失败：{exc!s}[/bold red]")
        raise typer.Exit(code=1)

    chat_history: list = []

    HELP_TEXT = """
常用命令示例：
  • 测试 https://api.example.com/users 的负载性能
  • 生成一个针对 POST /login 的压力测试脚本
  • 分析最新的测试报告并给出优化建议
  • 列出仓库中所有测试脚本
  • 查看最近 5 次 workflow 运行结果
"""

    while True:
        try:
            user_input = typer.prompt("\n[你]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]再见！[/yellow]")
            break

        user_input = user_input.strip()

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[yellow]再见！[/yellow]")
            break

        if user_input.lower() == "help":
            console.print(HELP_TEXT)
            continue

        try:
            with console.status("[bold green]🤔 思考中..."):
                response = agent.chat(user_input, chat_history)

            console.print(f"\n[bold cyan][Agent][/bold cyan] {response}")

            # 维护对话历史（简单追加）
            from langchain_core.messages import AIMessage, HumanMessage

            chat_history.append(HumanMessage(content=user_input))
            chat_history.append(AIMessage(content=response))

        except Exception as exc:
            console.print(f"[bold red]❌ 错误：{exc!s}[/bold red]")


@app.command("list-scripts")
def list_scripts(
    directory: str = typer.Option("k6_scripts", "--dir", "-d", help="搜索目录"),
) -> None:
    """📂 列出仓库中的 k6 测试脚本。"""
    try:
        from agent.services.github_service import GitHubService
        from agent.utils.config import get_settings

        settings = get_settings()
        svc = GitHubService(settings)
        scripts = svc.list_k6_scripts(directory)

        if not scripts:
            console.print(f"[yellow]目录 {directory!r} 中暂无脚本[/yellow]")
            return

        table = Table(title=f"k6 脚本列表（{directory}）", show_header=True)
        table.add_column("#", style="cyan", width=4)
        table.add_column("路径", style="green")
        for i, s in enumerate(scripts, 1):
            table.add_row(str(i), s)
        console.print(table)

    except Exception as exc:
        console.print(f"[bold red]❌ 获取脚本列表失败：{exc!s}[/bold red]")
        raise typer.Exit(code=1)


@app.command("list-runs")
def list_runs(
    workflow: str = typer.Option(
        "k6-performance-test.yml", "--workflow", "-w", help="Workflow 文件名"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="最多显示条数"),
) -> None:
    """📋 列出最近的 k6 Workflow 运行记录。"""
    try:
        from agent.services.github_service import GitHubService
        from agent.utils.config import get_settings

        settings = get_settings()
        svc = GitHubService(settings)
        runs = svc.list_workflow_runs(workflow, limit)

        if not runs:
            console.print("[yellow]暂无运行记录[/yellow]")
            return

        table = Table(title=f"最近 {len(runs)} 次运行（{workflow}）", show_header=True)
        table.add_column("Run ID", style="cyan")
        table.add_column("状态")
        table.add_column("结论")
        table.add_column("时间")
        table.add_column("URL")

        for r in runs:
            conclusion = r.conclusion or "pending"
            icon = "✅" if conclusion == "success" else ("❌" if conclusion == "failure" else "🔄")
            table.add_row(
                str(r.id),
                r.status,
                f"{icon} {conclusion}",
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.html_url,
            )
        console.print(table)

    except Exception as exc:
        console.print(f"[bold red]❌ 获取运行记录失败：{exc!s}[/bold red]")
        raise typer.Exit(code=1)


def main() -> None:
    """程序主入口。"""
    app()


if __name__ == "__main__":
    main()
