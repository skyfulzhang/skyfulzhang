"""链式执行器单元测试"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests_mock as requests_mock_lib

from core.executor import ChainExecutor
from core.registry import APIRegistry
from core.tracer import ExecutionTracer
from core.parser import ParameterParser
from core.extractor import ResponseExtractor
from core.assertion import AssertionEngine
from core.context import ExecutionContext
from models.api_def import APIDefinition
from models.chain import ChainDefinition
from models.step import StepDefinition, ExtractRule, AssertRule


@pytest.fixture
def registry():
    reg = APIRegistry()
    reg.register(APIDefinition(
        api_id="test_get",
        name="测试GET接口",
        method="GET",
        url="http://test.local/api/get",
        headers={},
        params={},
        body={},
        timeout=10,
        description="测试用GET接口",
        module="测试模块",
        tags=["test"],
    ))
    reg.register(APIDefinition(
        api_id="test_post",
        name="测试POST接口",
        method="POST",
        url="http://test.local/api/post",
        headers={"Content-Type": "application/json"},
        params={},
        body={"name": "{{name}}", "value": "{{value}}"},
        timeout=10,
        description="测试用POST接口",
        module="测试模块",
        tags=["test"],
    ))
    reg.register(APIDefinition(
        api_id="test_with_path",
        name="带路径参数的接口",
        method="GET",
        url="http://test.local/api/items/{{item_id}}",
        headers={},
        params={},
        body={},
        timeout=10,
        description="路径参数测试",
        module="测试模块",
        tags=["test"],
    ))
    return reg


@pytest.fixture
def executor(registry):
    return ChainExecutor(
        registry=registry,
        tracer=ExecutionTracer(),
        parser=ParameterParser(),
        extractor=ResponseExtractor(),
        assertion_engine=AssertionEngine(),
    )


class TestSingleStepExecution:
    """单步骤执行测试"""

    def test_get_request_success(self, executor):
        with requests_mock_lib.Mocker() as m:
            m.get("http://test.local/api/get", json={"code": 0, "data": "ok"})
            step = StepDefinition(
                step_id="s1",
                api_id="test_get",
                name="GET测试",
                assertions=[
                    AssertRule(name="状态码200", source="status_code", expression="status_code",
                               operator="eq", expected=200),
                ],
            )
            context = ExecutionContext()
            result = executor.execute_step(step, context)
            assert result.status == "success"
            assert result.response.status_code == 200

    def test_post_request_with_template(self, executor):
        with requests_mock_lib.Mocker() as m:
            m.post("http://test.local/api/post", json={"code": 0, "id": "123"})
            step = StepDefinition(
                step_id="s1",
                api_id="test_post",
                name="POST测试",
            )
            context = ExecutionContext(global_variables={"name": "测试", "value": "100"})
            result = executor.execute_step(step, context)
            assert result.status == "success"

    def test_path_variable_resolution(self, executor):
        with requests_mock_lib.Mocker() as m:
            m.get("http://test.local/api/items/ABC123", json={"code": 0})
            step = StepDefinition(
                step_id="s1",
                api_id="test_with_path",
                name="路径参数测试",
            )
            context = ExecutionContext(global_variables={"item_id": "ABC123"})
            result = executor.execute_step(step, context)
            assert result.status == "success"
            assert "ABC123" in result.request.url

    def test_extraction_stores_in_context(self, executor):
        with requests_mock_lib.Mocker() as m:
            m.get("http://test.local/api/get",
                  json={"code": 0, "data": {"token": "tok_xyz", "user_id": "42"}})
            step = StepDefinition(
                step_id="s1",
                api_id="test_get",
                name="提取测试",
                extracts=[
                    ExtractRule(var_name="token", source="body", extractor="jsonpath",
                                expression="$.data.token", default=None),
                    ExtractRule(var_name="user_id", source="body", extractor="jsonpath",
                                expression="$.data.user_id", default=None),
                ],
            )
            context = ExecutionContext()
            result = executor.execute_step(step, context)
            assert result.extractions["token"] == "tok_xyz"
            assert result.extractions["user_id"] == "42"
            assert context.get("token") == "tok_xyz"

    def test_assertion_failure_marks_step_failed(self, executor):
        with requests_mock_lib.Mocker() as m:
            m.get("http://test.local/api/get", json={"code": 1, "message": "error"})
            step = StepDefinition(
                step_id="s1",
                api_id="test_get",
                name="断言失败测试",
                assertions=[
                    AssertRule(name="code=0", source="body", expression="$.code",
                               operator="eq", expected=0),
                ],
            )
            context = ExecutionContext()
            result = executor.execute_step(step, context)
            assert result.status == "failed"
            assert result.assertions[0].passed is False


class TestChainExecution:
    """链路执行测试"""

    def _make_simple_chain(self) -> ChainDefinition:
        return ChainDefinition(
            chain_id="test_chain",
            name="测试链路",
            description="单元测试链路",
            global_variables={"name": "test", "value": "42"},
            steps=[
                StepDefinition(
                    step_id="step1",
                    api_id="test_post",
                    name="POST步骤",
                    extracts=[
                        ExtractRule(var_name="item_id", source="body", extractor="jsonpath",
                                    expression="$.id", default=None),
                    ],
                    assertions=[
                        AssertRule(name="状态码200", source="status_code", expression="status_code",
                                   operator="eq", expected=200),
                    ],
                ),
                StepDefinition(
                    step_id="step2",
                    api_id="test_with_path",
                    name="GET步骤",
                    assertions=[
                        AssertRule(name="状态码200", source="status_code", expression="status_code",
                                   operator="eq", expected=200),
                    ],
                    depends_on=["step1"],
                ),
            ],
        )

    def test_chain_success(self, executor):
        chain = self._make_simple_chain()
        with requests_mock_lib.Mocker() as m:
            m.post("http://test.local/api/post", json={"code": 0, "id": "ITEM001"})
            m.get("http://test.local/api/items/ITEM001", json={"code": 0, "name": "test_item"})
            result = executor.execute(chain)

        assert result.status == "success"
        assert len(result.step_results) == 2
        assert result.step_results[0].status == "success"
        assert result.step_results[1].status == "success"
        assert result.summary["success_steps"] == 2

    def test_chain_fail_on_first_step(self, executor):
        chain = self._make_simple_chain()
        with requests_mock_lib.Mocker() as m:
            m.post("http://test.local/api/post", json={"code": 1}, status_code=500)
            result = executor.execute(chain)

        assert result.status == "failed"
        assert result.step_results[0].status == "failed"
        # step2 应该被跳过（on_failure=stop）
        assert result.step_results[1].status == "skipped"

    def test_chain_with_runtime_variables(self, executor):
        chain = ChainDefinition(
            chain_id="rt_chain",
            name="运行时变量测试",
            steps=[
                StepDefinition(
                    step_id="s1",
                    api_id="test_post",
                    name="运行时变量",
                ),
            ],
        )
        with requests_mock_lib.Mocker() as m:
            m.post("http://test.local/api/post", json={"code": 0})
            result = executor.execute(chain, runtime_variables={"name": "rt_name", "value": "rt_val"})

        assert result.status == "success"

    def test_chain_result_has_context_snapshot(self, executor):
        chain = ChainDefinition(
            chain_id="snap_chain",
            name="上下文快照测试",
            global_variables={"name": "test", "value": "1"},
            steps=[
                StepDefinition(
                    step_id="s1",
                    api_id="test_post",
                    name="快照测试",
                    extracts=[
                        ExtractRule(var_name="extracted_id", source="body", extractor="jsonpath",
                                    expression="$.id", default=None),
                    ],
                ),
            ],
        )
        with requests_mock_lib.Mocker() as m:
            m.post("http://test.local/api/post", json={"code": 0, "id": "snap_001"})
            result = executor.execute(chain)

        assert "extracted_id" in result.context_snapshot
        assert result.context_snapshot["extracted_id"] == "snap_001"

    def test_dry_run(self, executor):
        chain = ChainDefinition(
            chain_id="dry_chain",
            name="干跑测试",
            global_variables={"name": "dry", "value": "123"},
            steps=[
                StepDefinition(
                    step_id="s1",
                    api_id="test_post",
                    name="干跑步骤",
                ),
            ],
        )
        dry_results = executor.dry_run(chain)
        assert "s1" in dry_results
        assert dry_results["s1"]["step_name"] == "干跑步骤"
        assert "request" in dry_results["s1"]


class TestOnFailurePolicy:
    """失败策略测试"""

    def test_continue_on_failure(self, executor, registry):
        chain = ChainDefinition(
            chain_id="continue_chain",
            name="continue策略测试",
            global_variables={"name": "t", "value": "1"},
            steps=[
                StepDefinition(
                    step_id="s1",
                    api_id="test_get",
                    name="失败步骤",
                    on_failure="continue",
                    assertions=[
                        AssertRule(name="会失败的断言", source="body", expression="$.nonexistent",
                                   operator="eq", expected="must_fail"),
                    ],
                ),
                StepDefinition(
                    step_id="s2",
                    api_id="test_get",
                    name="继续执行步骤",
                    assertions=[
                        AssertRule(name="状态码200", source="status_code", expression="status_code",
                                   operator="eq", expected=200),
                    ],
                ),
            ],
        )
        with requests_mock_lib.Mocker() as m:
            m.get("http://test.local/api/get", json={"code": 0})
            result = executor.execute(chain)

        # s1 失败但继续执行，s2 应该成功
        assert result.step_results[0].status == "failed"
        assert result.step_results[1].status == "success"
