"""
agent/core/agent.py
核心 Agent 实现 - 企业级性能测试智能体，基于 LangChain ReAct Agent。
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.memory import BaseMemory
from langchain_core.tools import BaseTool

from agent.core.llm_factory import LLMFactory
from agent.core.prompts import REACT_AGENT_PROMPT
from agent.models.test_config import (
    AnalysisResult,
    ComparisonResult,
    K6TestConfig,
    PipelineResult,
    WorkflowRunStatus,
)
from agent.services.github_service import GitHubService
from agent.services.k6_service import K6ScriptService
from agent.services.report_service import ReportService
from agent.tools.github_tools import GitHubToolkit
from agent.tools.k6_script_tools import get_k6_script_tools
from agent.tools.report_analyzer import get_report_analyzer_tools
from agent.tools.workflow_tools import WorkflowToolkit
from agent.utils.config import Settings
from agent.utils.logger import get_logger

logger = get_logger(__name__)


class PerformanceTestAgent:
    """企业级性能测试智能体。

    整合 LangChain ReAct Agent、GitHub 操作、k6 脚本生成和报告分析，
    实现从测试脚本生成到结果分析的完整自动化流水线。

    Args:
        config: 全局配置对象。
        verbose: 是否输出详细日志（含 Agent 思考过程）。
    """

    def __init__(self, config: Settings, verbose: bool = False) -> None:
        self.config = config
        self.verbose = verbose
        self.github_service = GitHubService(config)
        self.k6_service = K6ScriptService()
        self.report_service = ReportService()
        self.llm = LLMFactory.create(config)
        self.tools = self._build_tools()
        self.agent_executor = self._build_agent_executor()
        logger.info("agent_initialized", provider=config.llm_provider)

    def _build_tools(self) -> list[BaseTool]:
        """构建所有工具列表。"""
        tools: list[BaseTool] = []

        # k6 脚本工具
        tools.extend(get_k6_script_tools())

        # 报告分析工具
        tools.extend(get_report_analyzer_tools())

        # GitHub 工具
        github_toolkit = GitHubToolkit(self.config)
        tools.extend(github_toolkit.get_tools())

        # Workflow 工具
        workflow_toolkit = WorkflowToolkit(self.config)
        tools.extend(workflow_toolkit.get_tools())

        logger.info("tools_built", count=len(tools), names=[t.name for t in tools])
        return tools

    def _build_agent_executor(self) -> AgentExecutor:
        """构建 ReAct AgentExecutor。"""
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=REACT_AGENT_PROMPT,
        )
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            max_iterations=20,
            early_stopping_method="force",
            handle_parsing_errors=True,
            verbose=self.verbose,
            return_intermediate_steps=True,
        )

    async def run_performance_test_pipeline(
        self,
        target_url: str,
        test_type: str = "load",
        requirements: str = "",
        branch: str = "perf-test/auto",
    ) -> PipelineResult:
        """执行完整性能测试流水线。

        流水线步骤：
        1. 生成 k6 脚本
        2. 上传到 GitHub
        3. 触发 Actions Workflow
        4. 等待结果
        5. 分析报告
        6. 生成优化建议
        7. 创建 PR（如有改进建议）

        Args:
            target_url: 被测 URL。
            test_type: 测试类型（load/stress/spike/soak/api）。
            requirements: 补充测试要求（自然语言）。
            branch: 工作分支名称。

        Returns:
            PipelineResult: 流水线执行结果。
        """
        logger.info(
            "pipeline_starting",
            url=target_url,
            test_type=test_type,
            branch=branch,
        )

        task = (
            f"请为以下 API 执行完整的性能测试流水线：\n\n"
            f"目标 URL: {target_url}\n"
            f"测试类型: {test_type}\n"
            f"测试分支: {branch}\n"
            f"补充要求: {requirements or '无'}\n\n"
            f"请按照以下步骤执行：\n"
            f"1. 使用 generate_k6_script 工具生成测试脚本\n"
            f"2. 使用 validate_k6_script 工具验证脚本语法\n"
            f"3. 使用 upload_k6_script 工具上传脚本（分支: {branch}）\n"
            f"4. 使用 trigger_k6_workflow 工具触发性能测试\n"
            f"5. 使用 monitor_workflow_progress 工具等待测试完成\n"
            f"6. 使用 get_latest_report 工具获取测试报告\n"
            f"7. 使用 analyze_performance_report 工具分析报告\n"
            f"8. 如果发现性能问题，使用 optimize_script_thresholds 优化脚本\n"
            f"9. 如有优化，上传优化后的脚本并创建 PR\n\n"
            f"请完成整个流水线并给出详细的测试报告和优化建议。"
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.agent_executor.invoke(
                    {
                        "input": task,
                        "current_time": datetime.now(tz=timezone.utc).isoformat(),
                        "chat_history": [],
                    }
                ),
            )

            logger.info("pipeline_completed", steps=len(result.get("intermediate_steps", [])))
            return PipelineResult(
                success=True,
                llm_analysis=result.get("output", ""),
            )
        except Exception as exc:
            logger.error("pipeline_failed", error=str(exc))
            return PipelineResult(success=False, error_message=str(exc))

    async def analyze_existing_report(
        self,
        script_path: str,
        branch: str = "main",
    ) -> AnalysisResult:
        """分析已有测试报告，给出优化建议。

        Args:
            script_path: 脚本路径（用于定位对应报告目录）。
            branch: 分支名称。

        Returns:
            AnalysisResult: 分析结果。
        """
        import os

        script_dir = os.path.dirname(script_path)
        reports_dir = f"{script_dir}/reports"

        # 获取最新报告
        try:
            scripts = self.github_service.list_k6_scripts(reports_dir)
            json_reports = sorted(
                [s for s in scripts if s.endswith("_summary.json")]
            )
            if not json_reports:
                return AnalysisResult(
                    overall_assessment="FAIL",
                    performance_score=0,
                    key_findings=[f"未找到测试报告：{reports_dir}"],
                )

            latest_report_path = json_reports[-1]
            report_json = self.github_service.get_file_content(latest_report_path, branch)
            summary = self.report_service.parse_json_summary(report_json)
            metrics = self.report_service.extract_key_metrics(summary)

        except Exception as exc:
            logger.error("analyze_report_fetch_error", error=str(exc))
            return AnalysisResult(
                overall_assessment="FAIL",
                performance_score=0,
                key_findings=[f"获取报告失败: {exc!s}"],
            )

        # 使用 LLM 分析
        from agent.core.prompts import REPORT_ANALYSIS_PROMPT

        analysis_prompt = REPORT_ANALYSIS_PROMPT.format(
            report_json=json.dumps(metrics, ensure_ascii=False, indent=2),
            baseline_data="{}",
            test_name=summary.test_name,
            target_url=script_path,
        )

        try:
            llm_response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm.invoke(analysis_prompt),
            )
            response_text = (
                llm_response.content
                if hasattr(llm_response, "content")
                else str(llm_response)
            )

            # 尝试解析 JSON 响应
            import re
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                analysis_data = json.loads(json_match.group())
                return AnalysisResult(**analysis_data)
        except Exception as exc:
            logger.warning("llm_analysis_parse_error", error=str(exc))

        # 降级：基于规则的分析
        p95 = metrics["p95_ms"]
        error_rate = metrics["error_rate"]
        thresholds_passed = metrics["thresholds_passed"]

        if thresholds_passed and p95 < 500 and error_rate < 0.01:
            assessment: str = "PASS"
            score = 85
        elif not thresholds_passed or error_rate > 0.05:
            assessment = "FAIL"
            score = 30
        else:
            assessment = "WARN"
            score = 60

        return AnalysisResult(
            overall_assessment=assessment,  # type: ignore[arg-type]
            performance_score=score,
            key_findings=[
                f"P95 响应时间: {p95:.1f}ms",
                f"错误率: {error_rate:.2%}",
                f"RPS: {metrics['rps']:.1f}",
            ],
        )

    async def run_comparison_test(
        self,
        baseline_script: str,
        new_script: str,
        branch: str,
    ) -> ComparisonResult:
        """对比两个脚本的性能差异。

        Args:
            baseline_script: 基线脚本内容。
            new_script: 新脚本内容。
            branch: 运行分支。

        Returns:
            ComparisonResult: 对比结果。
        """
        # 注：实际对比需要分别运行两次 workflow，此处提供基础框架
        logger.info("comparison_test_starting", branch=branch)

        # 提取基线脚本元数据
        baseline_meta = self.k6_service.extract_script_metadata(baseline_script)
        new_meta = self.k6_service.extract_script_metadata(new_script)

        return ComparisonResult(
            baseline_name=f"baseline (VUs={baseline_meta.vus})",
            current_name=f"new script (VUs={new_meta.vus})",
            improved_metrics=[],
            degraded_metrics=[],
            unchanged_metrics=["需要实际运行两次 workflow 后才能对比"],
            delta_p95_ms=0.0,
            delta_error_rate=0.0,
            delta_rps=0.0,
            summary="请分别上传两个脚本并执行 Workflow 后，使用 compare_with_baseline 工具对比报告",
        )

    def chat(self, message: str, chat_history: Optional[list] = None) -> str:
        """交互式对话模式（同步）。

        Args:
            message: 用户消息。
            chat_history: 历史对话（LangChain 消息格式）。

        Returns:
            str: Agent 回复。
        """
        result = self.agent_executor.invoke(
            {
                "input": message,
                "current_time": datetime.now(tz=timezone.utc).isoformat(),
                "chat_history": chat_history or [],
            }
        )
        return result.get("output", "")
