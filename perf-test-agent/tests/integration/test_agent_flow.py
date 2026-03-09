"""
tests/integration/test_agent_flow.py
集成测试 - 验证 Agent 完整流程（需要真实 API，标记为 integration）。
实际 CI 中跳过，本地配置好环境变量后手动运行。
"""

import pytest


@pytest.mark.integration
class TestAgentPipelineFlow:
    """Agent 完整流水线集成测试。"""

    @pytest.mark.skip(reason="需要真实 GitHub Token 和 OpenAI API Key")
    async def test_full_pipeline_execution(self):
        """完整流水线执行测试（需要真实凭证）。"""
        from agent.core.agent import PerformanceTestAgent
        from agent.utils.config import get_settings

        settings = get_settings()
        agent = PerformanceTestAgent(settings)

        result = await agent.run_performance_test_pipeline(
            target_url="https://httpbin.org",
            test_type="load",
            requirements="简单的 GET 请求负载测试",
            branch="perf-test/integration-test",
        )

        assert result.success is True
        assert result.llm_analysis is not None

    @pytest.mark.skip(reason="需要真实 GitHub Token")
    async def test_analyze_existing_report(self):
        """分析已有报告集成测试（需要真实凭证）。"""
        from agent.core.agent import PerformanceTestAgent
        from agent.utils.config import get_settings

        settings = get_settings()
        agent = PerformanceTestAgent(settings)

        result = await agent.analyze_existing_report(
            script_path="k6_scripts/templates/http_load_test.js",
            branch="main",
        )
        assert result.overall_assessment in ("PASS", "WARN", "FAIL")
        assert 0 <= result.performance_score <= 100
