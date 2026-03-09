"""
agent/tools/workflow_tools.py
Workflow 工具集 - LangChain StructuredTool 封装，提供 Workflow 触发和监控功能。
"""

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.services.github_service import GitHubService
from agent.utils.config import Settings
from agent.utils.logger import get_logger

logger = get_logger(__name__)


# ── Input Schema Models ───────────────────────────────────────────────────────

class TriggerWorkflowInput(BaseModel):
    """触发 k6 Workflow 的输入参数。"""
    workflow_file: str = Field(
        default="k6-performance-test.yml", description="Workflow YAML 文件名"
    )
    ref: str = Field(default="perf-test/auto", description="触发分支名")
    script_path: str = Field(description="k6 脚本路径")
    vus: str = Field(default="10", description="并发用户数")
    duration: str = Field(default="30s", description="测试时长")
    test_name: str = Field(default="perf-test", description="测试名称")
    base_url: str = Field(default="", description="目标 URL")


class MonitorWorkflowInput(BaseModel):
    """监控 Workflow 进度的输入参数。"""
    run_id: int = Field(description="WorkflowRun ID")
    timeout_seconds: int = Field(default=1800, description="最大等待秒数")
    poll_interval: int = Field(default=30, description="轮询间隔秒数")


class GetArtifactsInput(BaseModel):
    """获取 Artifacts 的输入参数。"""
    run_id: int = Field(description="WorkflowRun ID")
    artifact_name: str = Field(description="Artifact 名称")


class ListRunsInput(BaseModel):
    """列出最近 Runs 的输入参数。"""
    workflow_file: str = Field(
        default="k6-performance-test.yml", description="Workflow 文件名"
    )
    limit: int = Field(default=10, description="最多返回条数")


# ── Toolkit ───────────────────────────────────────────────────────────────────

class WorkflowToolkit:
    """Workflow 操作工具集。

    Args:
        config: 全局配置对象。
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self._service = GitHubService(config)

    def get_tools(self) -> list[BaseTool]:
        """返回所有 Workflow 操作工具列表。"""
        return [
            self._trigger_k6_workflow_tool(),
            self._monitor_workflow_progress_tool(),
            self._get_workflow_artifacts_tool(),
            self._list_recent_runs_tool(),
        ]

    def _trigger_k6_workflow_tool(self) -> StructuredTool:
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
                inputs: dict[str, str] = {
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
                    f"✅ k6 Workflow 已触发！\n"
                    f"Run ID: {run_obj.id}\n"
                    f"状态: {run_obj.status}\n"
                    f"URL: {run_obj.html_url}\n"
                    f"使用 monitor_workflow_progress 工具（run_id={run_obj.id}）等待完成。"
                )
            except Exception as exc:
                logger.error("trigger_workflow_tool_error", error=str(exc))
                return f"❌ 触发 Workflow 失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="trigger_k6_workflow",
            description=(
                "触发 GitHub Actions k6 性能测试 Workflow (workflow_dispatch)。"
                "需要先上传脚本到对应分支才能触发。"
                "返回 Run ID，后续使用 monitor_workflow_progress 等待结果。"
            ),
            args_schema=TriggerWorkflowInput,
        )

    def _monitor_workflow_progress_tool(self) -> StructuredTool:
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
                conclusion = run_obj.conclusion or "unknown"
                icon = "✅" if conclusion == "success" else "❌"
                return (
                    f"{icon} Workflow 运行完成！\n"
                    f"Run ID: {run_id}\n"
                    f"结论: {conclusion}\n"
                    f"URL: {run_obj.html_url}"
                )
            except TimeoutError as exc:
                return f"⏰ {exc!s}"
            except Exception as exc:
                return f"❌ 监控失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="monitor_workflow_progress",
            description=(
                "实时监控 GitHub Actions Workflow 运行进度，等待完成。"
                "触发 Workflow 后必须调用此工具，确认完成后再获取报告。"
                "支持超时配置，超时后会返回当前状态而不是抛出异常。"
            ),
            args_schema=MonitorWorkflowInput,
        )

    def _get_workflow_artifacts_tool(self) -> StructuredTool:
        def run(run_id: int, artifact_name: str) -> str:
            try:
                data = self._service.download_artifact(run_id, artifact_name)
                return (
                    f"✅ Artifact 下载成功！\n"
                    f"名称: {artifact_name}\n"
                    f"大小: {len(data) / 1024:.1f} KB\n"
                    f"（zip 格式，包含测试报告文件）"
                )
            except ValueError as exc:
                return f"❌ {exc!s}"
            except Exception as exc:
                return f"❌ 下载 Artifact 失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="get_workflow_artifacts",
            description=(
                "下载 GitHub Actions Workflow 运行的 Artifact（zip 格式）。"
                "Workflow 完成后可以通过此工具获取测试报告压缩包。"
            ),
            args_schema=GetArtifactsInput,
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
                lines = [f"📋 最近 {len(runs)} 次 k6 Workflow 运行：\n"]
                for r in runs:
                    icon = (
                        "✅" if r.conclusion == "success"
                        else "❌" if r.conclusion == "failure"
                        else "🔄"
                    )
                    lines.append(
                        f"  {icon} Run #{r.id} | {r.status} | "
                        f"结论: {r.conclusion or 'pending'} | "
                        f"时间: {r.created_at.strftime('%Y-%m-%d %H:%M')}"
                    )
                return "\n".join(lines)
            except Exception as exc:
                return f"❌ 获取运行记录失败: {exc!s}"

        return StructuredTool.from_function(
            func=run,
            name="list_recent_k6_runs",
            description=(
                "列出最近的 k6 性能测试 Workflow 运行记录。"
                "用于查看历史测试执行情况和结果趋势。"
            ),
            args_schema=ListRunsInput,
        )
