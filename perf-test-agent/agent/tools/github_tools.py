"""
agent/tools/github_tools.py
LangChain Tools 封装 - GitHub 操作工具集，每个 Tool 有清晰的描述和错误处理。
"""

from typing import Any, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.services.github_service import GitHubService
from agent.utils.config import Settings
from agent.utils.logger import get_logger

logger = get_logger(__name__)


# ── Input Schema Models ───────────────────────────────────────────────────────

class UploadScriptInput(BaseModel):
    """上传 k6 脚本的输入参数。"""
    script_content: str = Field(description="k6 脚本 JavaScript 内容")
    script_path: str = Field(description="仓库内文件路径，如 k6_scripts/load_test.js")
    branch: str = Field(default="perf-test/auto", description="目标分支名称")
    commit_message: str = Field(
        default="perf: add/update k6 test script", description="Git 提交信息"
    )


class TriggerWorkflowInput(BaseModel):
    """触发 Workflow 的输入参数。"""
    workflow_file: str = Field(
        default="k6-performance-test.yml", description="Workflow 文件名"
    )
    ref: str = Field(default="perf-test/auto", description="触发分支名")
    script_path: str = Field(description="k6 脚本路径（作为 workflow input）")
    vus: str = Field(default="10", description="并发用户数")
    duration: str = Field(default="30s", description="测试时长")
    test_name: str = Field(default="perf-test", description="测试名称")
    base_url: str = Field(default="", description="目标 URL（覆盖脚本默认值）")


class WaitWorkflowInput(BaseModel):
    """等待 Workflow 完成的输入参数。"""
    run_id: int = Field(description="WorkflowRun ID")
    timeout_seconds: int = Field(default=1800, description="最大等待秒数")
    poll_interval: int = Field(default=30, description="轮询间隔秒数")


class GetFileInput(BaseModel):
    """获取文件内容的输入参数。"""
    path: str = Field(description="仓库内文件路径")
    branch: str = Field(default="main", description="分支名称")


class ListScriptsInput(BaseModel):
    """列出脚本的输入参数。"""
    directory: str = Field(default="k6_scripts", description="搜索目录")


class GetReportInput(BaseModel):
    """获取报告的输入参数。"""
    script_path: str = Field(description="脚本路径，如 k6_scripts/load_test.js")
    branch: str = Field(default="main", description="分支名称")


class CreatePRInput(BaseModel):
    """创建 PR 的输入参数。"""
    title: str = Field(description="PR 标题")
    body: str = Field(description="PR 描述")
    head_branch: str = Field(description="源分支")
    base_branch: str = Field(default="main", description="目标分支")


class CompareBaselineInput(BaseModel):
    """对比基线的输入参数。"""
    baseline_report_path: str = Field(description="基线报告路径")
    current_report_path: str = Field(description="当前报告路径")
    branch: str = Field(default="main", description="分支名称")


class ListRunsInput(BaseModel):
    """列出 Workflow 运行的输入参数。"""
    workflow_file: str = Field(
        default="k6-performance-test.yml", description="Workflow 文件名"
    )
    limit: int = Field(default=10, description="最多返回条数")


# ── Toolkit ───────────────────────────────────────────────────────────────────

class GitHubToolkit:
    """GitHub 操作工具集。

    将 GitHubService 方法封装为 LangChain StructuredTool，供 Agent 调用。

    Args:
        config: 全局配置对象。
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self._service = GitHubService(config)

    def get_tools(self) -> list[BaseTool]:
        """返回所有 GitHub 操作工具列表。"""
        return [
            self._upload_k6_script_tool(),
            self._trigger_performance_test_tool(),
            self._wait_and_get_results_tool(),
            self._list_existing_scripts_tool(),
            self._get_script_content_tool(),
            self._get_latest_report_tool(),
            self._create_pr_with_optimized_script_tool(),
            self._compare_with_baseline_tool(),
            self._list_recent_runs_tool(),
        ]

    def _upload_k6_script_tool(self) -> StructuredTool:
        def run(
            script_content: str,
            script_path: str,
            branch: str = "perf-test/auto",
            commit_message: str = "perf: add/update k6 test script",
        ) -> str:
            try:
                # 确保分支存在
                self._service.get_or_create_branch(branch)
                sha = self._service.upload_k6_script(
                    script_content=script_content,
                    script_path=script_path,
                    branch=branch,
                    commit_message=commit_message,
                )
                return f"✅ 脚本上传成功！路径: {script_path}，SHA: {sha}，分支: {branch}"
            except Exception as exc:
                logger.error("upload_script_error", error=str(exc))
                return f"❌ 脚本上传失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="upload_k6_script",
            description=(
                "上传 k6 测试脚本到 GitHub 仓库。"
                "在生成脚本后、触发 Workflow 前使用。"
                "会自动创建目标分支（如不存在）。"
                "返回文件 SHA 和完整路径。"
            ),
            args_schema=UploadScriptInput,
        )

    def _trigger_performance_test_tool(self) -> StructuredTool:
        def run(
            workflow_file: str = "k6-performance-test.yml",
            ref: str = "perf-test/auto",
            script_path: str = "",
            vus: str = "10",
            duration: str = "30s",
            test_name: str = "perf-test",
            base_url: str = "",
        ) -> str:
            try:
                inputs: dict[str, Any] = {
                    "script_path": script_path,
                    "vus": vus,
                    "duration": duration,
                    "test_name": test_name,
                }
                if base_url:
                    inputs["base_url"] = base_url

                run_obj = self._service.trigger_workflow(
                    workflow_file=workflow_file,
                    ref=ref,
                    inputs=inputs,
                )
                return (
                    f"✅ Workflow 已触发！\n"
                    f"Run ID: {run_obj.id}\n"
                    f"状态: {run_obj.status}\n"
                    f"URL: {run_obj.html_url}"
                )
            except Exception as exc:
                logger.error("trigger_workflow_error", error=str(exc))
                return f"❌ 触发 Workflow 失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="trigger_performance_test",
            description=(
                "触发 GitHub Actions k6 性能测试 Workflow。"
                "需要先上传脚本才能触发。"
                "返回 Workflow Run ID，后续用于等待和获取结果。"
                "触发后不会等待完成，需要配合 wait_for_workflow_completion 使用。"
            ),
            args_schema=TriggerWorkflowInput,
        )

    def _wait_and_get_results_tool(self) -> StructuredTool:
        def run(
            run_id: int,
            timeout_seconds: int = 1800,
            poll_interval: int = 30,
        ) -> str:
            try:
                run_obj = self._service.wait_for_workflow_completion(
                    run_id=run_id,
                    timeout_seconds=timeout_seconds,
                    poll_interval=poll_interval,
                )
                return (
                    f"✅ Workflow 完成！\n"
                    f"Run ID: {run_id}\n"
                    f"结论: {run_obj.conclusion}\n"
                    f"URL: {run_obj.html_url}\n"
                    f"状态: {'成功' if run_obj.conclusion == 'success' else '失败/取消'}"
                )
            except TimeoutError as exc:
                return f"⏰ Workflow 超时: {exc!s}"
            except Exception as exc:
                logger.error("wait_workflow_error", error=str(exc))
                return f"❌ 等待 Workflow 失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="wait_for_workflow_completion",
            description=(
                "等待 GitHub Actions Workflow 运行完成（轮询方式）。"
                "触发 Workflow 后必须调用此工具等待结果。"
                "返回最终状态（success/failure/cancelled）。"
            ),
            args_schema=WaitWorkflowInput,
        )

    def _list_existing_scripts_tool(self) -> StructuredTool:
        def run(directory: str = "k6_scripts") -> str:
            try:
                scripts = self._service.list_k6_scripts(directory)
                if not scripts:
                    return f"📂 目录 {directory!r} 中暂无 k6 脚本文件"
                return f"📂 找到 {len(scripts)} 个脚本：\n" + "\n".join(
                    f"  - {s}" for s in scripts
                )
            except Exception as exc:
                return f"❌ 列出脚本失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="list_existing_scripts",
            description=(
                "列出 GitHub 仓库中指定目录下的所有 k6 测试脚本（.js 文件）。"
                "在决定是否复用已有脚本时使用。"
            ),
            args_schema=ListScriptsInput,
        )

    def _get_script_content_tool(self) -> StructuredTool:
        def run(path: str, branch: str = "main") -> str:
            try:
                content = self._service.get_file_content(path, branch)
                return f"✅ 文件内容（{path}@{branch}）：\n\n```javascript\n{content}\n```"
            except Exception as exc:
                return f"❌ 获取文件失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="get_script_content",
            description=(
                "获取 GitHub 仓库中指定文件的内容。"
                "用于查看已有脚本或报告内容。"
            ),
            args_schema=GetFileInput,
        )

    def _get_latest_report_tool(self) -> StructuredTool:
        def run(script_path: str, branch: str = "main") -> str:
            try:
                import os

                script_dir = os.path.dirname(script_path)
                script_name = os.path.splitext(os.path.basename(script_path))[0]
                reports_dir = f"{script_dir}/reports"

                scripts = self._service.list_k6_scripts(reports_dir)
                json_reports = [
                    s for s in scripts if s.endswith("_summary.json")
                ]

                if not json_reports:
                    return f"📋 {reports_dir!r} 中暂无测试报告"

                # 取最新的报告
                latest = sorted(json_reports)[-1]
                content = self._service.get_file_content(latest, branch)
                return f"✅ 最新报告（{latest}）：\n\n```json\n{content}\n```"
            except Exception as exc:
                return f"❌ 获取报告失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="get_latest_report",
            description=(
                "获取与指定脚本对应目录下最新的 k6 JSON 测试报告。"
                "Workflow 完成后调用此工具获取报告数据进行分析。"
            ),
            args_schema=GetReportInput,
        )

    def _create_pr_with_optimized_script_tool(self) -> StructuredTool:
        def run(
            title: str,
            body: str,
            head_branch: str,
            base_branch: str = "main",
        ) -> str:
            try:
                pr = self._service.create_pull_request(
                    title=title,
                    body=body,
                    head_branch=head_branch,
                    base_branch=base_branch,
                )
                return (
                    f"✅ PR 创建成功！\n"
                    f"PR #{pr.number}: {pr.title}\n"
                    f"URL: {pr.html_url}"
                )
            except Exception as exc:
                return f"❌ 创建 PR 失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="create_pr_with_optimized_script",
            description=(
                "创建包含优化脚本的 Pull Request。"
                "在分析报告、生成优化脚本并上传后使用。"
                "PR 的 body 应包含性能对比数据和优化说明。"
            ),
            args_schema=CreatePRInput,
        )

    def _compare_with_baseline_tool(self) -> StructuredTool:
        def run(
            baseline_report_path: str,
            current_report_path: str,
            branch: str = "main",
        ) -> str:
            try:
                baseline_json = self._service.get_file_content(
                    baseline_report_path, branch
                )
                current_json = self._service.get_file_content(
                    current_report_path, branch
                )

                from agent.services.report_service import ReportService

                svc = ReportService()
                baseline = svc.parse_json_summary(baseline_json)
                current = svc.parse_json_summary(current_json)
                result = svc.compare_reports(baseline, current)

                return (
                    f"📊 性能对比结果：\n"
                    f"  摘要: {result.summary}\n"
                    f"  p95 变化: {result.delta_p95_ms:+.1f}ms\n"
                    f"  错误率变化: {result.delta_error_rate:+.4f}\n"
                    f"  RPS 变化: {result.delta_rps:+.1f}\n"
                    f"  改善项: {', '.join(result.improved_metrics) or '无'}\n"
                    f"  退化项: {', '.join(result.degraded_metrics) or '无'}"
                )
            except Exception as exc:
                return f"❌ 对比报告失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="compare_with_baseline",
            description=(
                "对比当前测试报告与历史基线报告，识别性能退化或改善。"
                "需要提供两个 JSON 报告的仓库路径。"
            ),
            args_schema=CompareBaselineInput,
        )

    def _list_recent_runs_tool(self) -> StructuredTool:
        def run(
            workflow_file: str = "k6-performance-test.yml",
            limit: int = 10,
        ) -> str:
            try:
                runs = self._service.list_workflow_runs(workflow_file, limit)
                if not runs:
                    return "📋 暂无 Workflow 运行记录"
                lines = [f"📋 最近 {len(runs)} 次运行："]
                for r in runs:
                    status_icon = "✅" if r.conclusion == "success" else (
                        "❌" if r.conclusion == "failure" else "🔄"
                    )
                    lines.append(
                        f"  {status_icon} Run #{r.id} | {r.status} | "
                        f"{r.conclusion or 'pending'} | {r.created_at}"
                    )
                return "\n".join(lines)
            except Exception as exc:
                return f"❌ 获取运行记录失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="list_recent_runs",
            description=(
                "列出最近的 k6 Workflow 运行记录，包含状态和结论。"
                "用于查看历史测试执行情况。"
            ),
            args_schema=ListRunsInput,
        )
