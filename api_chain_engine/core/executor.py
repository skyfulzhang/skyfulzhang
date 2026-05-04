"""链式执行器 - 核心模块"""
from __future__ import annotations
import time
from datetime import datetime
from typing import Any, TYPE_CHECKING

import requests as requests_lib

from models.chain import (
    ChainResult,
    StepResult,
    RequestRecord,
    ResponseRecord,
    AssertionRecord,
)
from models.step import StepDefinition
from core.context import ExecutionContext

if TYPE_CHECKING:
    from models.chain import ChainDefinition
    from core.registry import APIRegistry
    from core.tracer import ExecutionTracer
    from core.parser import ParameterParser
    from core.extractor import ResponseExtractor
    from core.assertion import AssertionEngine


class ChainExecutor:
    """
    链式执行器核心：
    1. 接收 ChainDefinition，按步骤顺序执行
    2. 每步执行前：解析模板参数（从上下文注入）
    3. 发起 HTTP 请求（requests）
    4. 提取响应变量存入上下文
    5. 执行断言校验
    6. 根据失败策略决定是否继续
    7. 记录每步的请求/响应/提取/断言/耗时
    8. 返回完整的 ChainResult
    """

    def __init__(
        self,
        registry: "APIRegistry",
        tracer: "ExecutionTracer",
        parser: "ParameterParser",
        extractor: "ResponseExtractor",
        assertion_engine: "AssertionEngine",
    ) -> None:
        self.registry = registry
        self.tracer = tracer
        self.parser = parser
        self.extractor = extractor
        self.assertion_engine = assertion_engine
        self._session = requests_lib.Session()

    def execute(
        self,
        chain: "ChainDefinition",
        runtime_variables: dict[str, Any] | None = None,
    ) -> ChainResult:
        """执行完整链路"""
        started_at = datetime.now().isoformat()
        start_time = time.time()

        # 初始化上下文
        global_vars = dict(chain.global_variables or {})
        if runtime_variables:
            global_vars.update(runtime_variables)
        context = ExecutionContext(global_variables=global_vars)

        self.tracer.on_chain_start(chain, context)

        step_results: list[StepResult] = []
        skip_remaining = False

        for step in chain.steps:
            if skip_remaining:
                step_results.append(self._make_skipped_result(step))
                continue

            step_result = self.execute_step(step, context)
            step_results.append(step_result)

            # 存储步骤提取结果到上下文
            if step_result.extractions:
                context.set_step_result(step.step_id, step_result.extractions)

            self.tracer.on_step_end(step_result)

            # 处理失败策略
            if step_result.status == "failed":
                on_failure = getattr(step, "on_failure", "stop")
                if on_failure == "stop":
                    skip_remaining = True
                elif on_failure == "skip_next":
                    skip_remaining = True
                # "continue" 策略：继续执行

        total_duration_ms = (time.time() - start_time) * 1000
        finished_at = datetime.now().isoformat()

        # 判断链路整体状态：所有步骤成功且所有断言通过
        overall_status = self._compute_chain_status(step_results)

        result = ChainResult(
            chain_id=chain.chain_id,
            chain_name=chain.name,
            status=overall_status,
            step_results=step_results,
            context_snapshot=context.snapshot(),
            total_duration_ms=total_duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            summary=self._build_summary(step_results),
        )

        self.tracer.on_chain_end(result)
        return result

    def execute_step(self, step: StepDefinition, context: ExecutionContext) -> StepResult:
        """执行单个步骤"""
        context.clear_step_scope()
        start_time = time.time()

        # 运行前置脚本
        for script in (step.pre_scripts or []):
            try:
                self._run_script(script, context)
            except Exception as e:
                pass

        try:
            # 获取接口定义
            api = self.registry.get(step.api_id)

            # 构建请求数据（解析模板参数）
            request_data = self._build_request(api, step, context)
            request_record = RequestRecord(
                method=request_data["method"],
                url=request_data["url"],
                headers=request_data.get("headers", {}),
                params=request_data.get("params", {}),
                body=request_data.get("json") or request_data.get("data"),
            )

            self.tracer.on_step_start(step, request_data)

            # 发起 HTTP 请求
            response = self._send_request(request_data)
            duration_ms = (time.time() - start_time) * 1000

            # 解析响应
            try:
                resp_body = response.json()
            except Exception:
                resp_body = response.text

            response_record = ResponseRecord(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=resp_body,
                text=response.text,
            )

            # 提取变量
            extractions = self.extractor.extract(response, step.extracts or [], context)

            # 执行断言
            assertion_records = self.assertion_engine.run_assertions(
                response, step.assertions or [], context
            )

            # 运行后置脚本
            for script in (step.post_scripts or []):
                try:
                    self._run_script(script, context)
                except Exception:
                    pass

            # 判断步骤状态：所有断言通过则成功
            all_assertions_passed = all(a.passed for a in assertion_records)
            http_ok = response.status_code < 500
            step_status = "success" if (http_ok and all_assertions_passed) else "failed"

            return StepResult(
                step_id=step.step_id,
                api_id=step.api_id,
                name=step.name,
                status=step_status,
                request=request_record,
                response=response_record,
                extractions=extractions,
                assertions=assertion_records,
                duration_ms=duration_ms,
                error=None,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return StepResult(
                step_id=step.step_id,
                api_id=step.api_id,
                name=step.name,
                status="failed",
                request=RequestRecord(method="", url=""),
                response=ResponseRecord(),
                extractions={},
                assertions=[],
                duration_ms=duration_ms,
                error=str(e),
            )

    def _build_request(
        self,
        api: Any,
        step: StepDefinition,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """构建请求数据（合并接口定义与步骤覆盖，解析模板）"""
        import copy

        # 合并接口默认参数与步骤覆盖参数
        merged_headers = dict(api.headers or {})
        merged_params = dict(api.params or {})
        merged_body = copy.deepcopy(api.body or {})

        overrides = step.param_overrides or {}
        merged_headers.update(overrides.get("headers", {}))
        merged_params.update(overrides.get("params", {}))

        # body 覆盖（支持嵌套）
        body_overrides = overrides.get("body", {})
        if body_overrides:
            merged_body.update(body_overrides)

        # 解析模板变量
        url = self.parser.parse_string(api.url, context)
        headers = self.parser.parse_dict(merged_headers, context)
        params = self.parser.parse_dict(merged_params, context)
        body = self.parser.parse(merged_body, context)

        request_data: dict[str, Any] = {
            "method": api.method,
            "url": url,
            "headers": headers,
            "params": params,
            "timeout": api.timeout,
        }

        if api.method in ("POST", "PUT", "PATCH"):
            request_data["json"] = body
        elif body:
            request_data["json"] = body

        return request_data

    def _send_request(self, request_data: dict[str, Any]) -> requests_lib.Response:
        """发起 HTTP 请求"""
        method = request_data.pop("method")
        url = request_data.pop("url")
        # params 为空则不传
        if not request_data.get("params"):
            request_data.pop("params", None)
        return self._session.request(method, url, **request_data)

    def _run_script(self, script: str, context: ExecutionContext) -> None:
        """执行 Python 脚本（在受限上下文环境中）。
        
        安全说明：此功能仅用于受信任的测试工程师编写的内部脚本，不应暴露给不可信的外部输入。
        执行环境中仅提供 context 对象，不提供文件系统或网络访问能力。
        """
        exec(script, {"context": context, "__builtins__": {}})  # noqa: S102

    def dry_run(
        self,
        chain: "ChainDefinition",
        runtime_variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        干跑模式：不发送真实请求，只解析模板参数。
        返回每个步骤解析后的请求参数。
        """
        global_vars = dict(chain.global_variables or {})
        if runtime_variables:
            global_vars.update(runtime_variables)
        context = ExecutionContext(global_variables=global_vars)

        dry_results = {}
        for step in chain.steps:
            api = self.registry.get(step.api_id)
            request_data = self._build_request(api, step, context)
            dry_results[step.step_id] = {
                "step_name": step.name,
                "request": request_data,
            }
        return dry_results

    @staticmethod
    def _make_skipped_result(step: StepDefinition) -> StepResult:
        """生成跳过的步骤结果"""
        return StepResult(
            step_id=step.step_id,
            api_id=step.api_id,
            name=step.name,
            status="skipped",
            request=RequestRecord(method="", url=""),
            response=ResponseRecord(),
            extractions={},
            assertions=[],
            duration_ms=0.0,
            error=None,
        )

    @staticmethod
    def _compute_chain_status(step_results: list[StepResult]) -> str:
        """根据步骤结果计算链路整体状态"""
        for step_result in step_results:
            if step_result.status == "failed":
                return "failed"
        return "success"

    @staticmethod
    def _build_summary(step_results: list[StepResult]) -> dict[str, Any]:
        """构建执行摘要"""
        total = len(step_results)
        success = sum(1 for s in step_results if s.status == "success")
        failed = sum(1 for s in step_results if s.status == "failed")
        skipped = sum(1 for s in step_results if s.status == "skipped")

        all_assertions = [a for s in step_results for a in s.assertions]
        total_assertions = len(all_assertions)
        passed_assertions = sum(1 for a in all_assertions if a.passed)

        return {
            "total_steps": total,
            "success_steps": success,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_assertions": total_assertions,
            "passed_assertions": passed_assertions,
        }
