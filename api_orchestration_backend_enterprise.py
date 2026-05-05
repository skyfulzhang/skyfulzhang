"""
api_orchestration_backend_enterprise.py
========================================
企业级 API 编排后端（Enterprise API Orchestration Backend）

支持功能：
  - OpenAPI 规范导入与解析
  - 链路（Pipeline）模板管理与热重载
  - 参数解析器（支持 ${var} 表达式）
  - HTTP 步骤执行器（含重试、超时）
  - SQLite 持久化（WAL 模式）
  - 线程安全指标收集器
  - 健康检查器
  - 链路校验器
  - LLM 规划器（openai 可选）
  - Pytest 草稿生成器

作者：skyfulzhang
版本：2.0.0
Python：3.9+
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = [
    # 异常
    "RegistryError",
    "StepExecutionError",
    "AssertionFailedError",
    "PlanValidationError",
    # 数据模型
    "StepParam",
    "StepExtract",
    "StepAssertion",
    "PipelineStep",
    "PipelinePlan",
    "StepResult",
    "PipelineRunResult",
    # 核心组件
    "ParameterParser",
    "OpenAPIImporter",
    "MetricsCollector",
    "PipelineRepository",
    "HttpStepExecutor",
    "OrchestrationBackend",
    "HealthChecker",
    "PipelineValidator",
    "LLMPlanner",
    "PytestCaseGenerator",
    # 内置模板
    "BUILTIN_TEMPLATES",
]

# ─────────────────────────────────────────────
# § 1. 标准库导入
# ─────────────────────────────────────────────
import contextlib
import json
import logging
import re
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

# ─────────────────────────────────────────────
# § 2. 可选第三方导入
# ─────────────────────────────────────────────
with contextlib.suppress(ImportError):
    import requests  # type: ignore[import]

_openai_available = False
with contextlib.suppress(ImportError):
    import openai  # type: ignore[import]
    _openai_available = True

# ─────────────────────────────────────────────
# § 3. 日志配置
# ─────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# § 4. 自定义异常体系
# ─────────────────────────────────────────────

class OrchestrationError(Exception):
    """所有编排异常的基类。"""


class RegistryError(OrchestrationError):
    """注册表操作异常：模板未找到、重复注册等。"""

    def __init__(self, message: str, plan_name: str = "") -> None:
        super().__init__(message)
        self.plan_name = plan_name

    def __repr__(self) -> str:
        return f"RegistryError(plan_name={self.plan_name!r}, message={str(self)!r})"


class StepExecutionError(OrchestrationError):
    """步骤执行异常：HTTP 请求失败、超时等。"""

    def __init__(self, message: str, step_name: str = "", status_code: int = 0) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.status_code = status_code

    def __repr__(self) -> str:
        return (
            f"StepExecutionError(step={self.step_name!r}, "
            f"status={self.status_code}, message={str(self)!r})"
        )


class AssertionFailedError(OrchestrationError):
    """断言失败异常：响应校验未通过。"""

    def __init__(
        self,
        message: str,
        step_name: str = "",
        expression: str = "",
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        super().__init__(message)
        self.step_name = step_name
        self.expression = expression
        self.expected = expected
        self.actual = actual

    def __repr__(self) -> str:
        return (
            f"AssertionFailedError(step={self.step_name!r}, expr={self.expression!r}, "
            f"expected={self.expected!r}, actual={self.actual!r})"
        )


class PlanValidationError(OrchestrationError):
    """链路校验异常：步骤引用缺失、参数格式错误等。"""

    def __init__(self, message: str, errors: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.errors: List[str] = errors or []

    def __repr__(self) -> str:
        return f"PlanValidationError(errors={self.errors!r})"


# ─────────────────────────────────────────────
# § 5. 数据模型（Dataclasses）
# ─────────────────────────────────────────────

# Python 3.10+ 支持 slots=True，此处做版本兼容
_DC_KWARGS: Dict[str, Any] = {}
if sys.version_info >= (3, 10):
    _DC_KWARGS["slots"] = True


@dataclass(**_DC_KWARGS)
class StepParam:
    """步骤参数定义。"""
    name: str
    value: str                      # 支持 ${变量} 表达式
    location: str = "body"          # body | query | header | path

    def __repr__(self) -> str:
        return f"StepParam({self.name}={self.value!r}, loc={self.location})"


@dataclass(**_DC_KWARGS)
class StepExtract:
    """步骤提取规则：从响应中提取变量。"""
    variable: str                   # 目标变量名
    jsonpath: str                   # JSONPath 表达式（简化版：用 . 分隔）

    def __repr__(self) -> str:
        return f"StepExtract({self.variable} <- {self.jsonpath})"


@dataclass(**_DC_KWARGS)
class StepAssertion:
    """步骤断言规则。"""
    expression: str                 # 断言表达式，如 "status == 200"
    expected: Any = None            # 期望值

    def __repr__(self) -> str:
        return f"StepAssertion(expr={self.expression!r}, expected={self.expected!r})"


@dataclass(**_DC_KWARGS)
class PipelineStep:
    """链路中的单个执行步骤。"""
    name: str
    method: str                                     # HTTP 方法
    path: str                                       # 路径（支持 ${var}）
    params: List[StepParam] = field(default_factory=list)
    extracts: List[StepExtract] = field(default_factory=list)
    assertions: List[StepAssertion] = field(default_factory=list)
    timeout: float = 30.0
    retries: int = 0
    cleanup: bool = False                           # 是否为清理步骤
    description: str = ""

    def __repr__(self) -> str:
        return f"PipelineStep({self.name!r}, {self.method} {self.path})"

    def __str__(self) -> str:
        return f"[{self.method}] {self.name}: {self.path}"


@dataclass
class PipelinePlan:
    """完整的链路执行计划。"""
    name: str
    steps: List[PipelineStep]
    base_url: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __repr__(self) -> str:
        return (
            f"PipelinePlan(name={self.name!r}, steps={len(self.steps)}, "
            f"id={self.plan_id[:8]}...)"
        )

    def __str__(self) -> str:
        steps_info = " -> ".join(s.name for s in self.steps)
        return f"PipelinePlan[{self.name}]: {steps_info}"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于 JSON 存储）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelinePlan":
        """从字典反序列化。"""
        steps = [
            PipelineStep(
                name=s["name"],
                method=s["method"],
                path=s["path"],
                params=[StepParam(**p) for p in s.get("params", [])],
                extracts=[StepExtract(**e) for e in s.get("extracts", [])],
                assertions=[StepAssertion(**a) for a in s.get("assertions", [])],
                timeout=s.get("timeout", 30.0),
                retries=s.get("retries", 0),
                cleanup=s.get("cleanup", False),
                description=s.get("description", ""),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            name=data["name"],
            steps=steps,
            base_url=data.get("base_url", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            plan_id=data.get("plan_id", str(uuid.uuid4())),
        )


@dataclass
class StepResult:
    """单个步骤的执行结果。"""
    step_name: str
    success: bool
    status_code: int = 0
    response_body: Any = None
    extracted: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: float = 0.0

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return (
            f"StepResult({status} {self.step_name}, "
            f"HTTP {self.status_code}, {self.elapsed_ms:.1f}ms)"
        )

    def __str__(self) -> str:
        status = "成功" if self.success else f"失败({self.error})"
        return f"{self.step_name}: {status} [{self.status_code}] {self.elapsed_ms:.1f}ms"


@dataclass
class PipelineRunResult:
    """链路完整执行结果。"""
    plan_name: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    success: bool = False
    step_results: List[StepResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)   # 累积的上下文变量
    total_elapsed_ms: float = 0.0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str = ""

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return (
            f"PipelineRunResult({status} {self.plan_name}, "
            f"{len(self.step_results)} steps, {self.total_elapsed_ms:.1f}ms)"
        )

    def __str__(self) -> str:
        lines = [f"=== 链路执行结果: {self.plan_name} ==="]
        lines.append(f"  状态: {'成功' if self.success else '失败'}")
        lines.append(f"  总耗时: {self.total_elapsed_ms:.1f}ms")
        for sr in self.step_results:
            lines.append(f"  {sr}")
        if self.error:
            lines.append(f"  错误: {self.error}")
        return "\n".join(lines)

    def summary(self) -> Dict[str, Any]:
        """返回执行摘要字典。"""
        return {
            "plan_name": self.plan_name,
            "run_id": self.run_id,
            "success": self.success,
            "total_elapsed_ms": self.total_elapsed_ms,
            "steps_total": len(self.step_results),
            "steps_passed": sum(1 for s in self.step_results if s.success),
            "steps_failed": sum(1 for s in self.step_results if not s.success),
            "context_keys": list(self.context.keys()),
            "error": self.error,
        }


# ─────────────────────────────────────────────
# § 6. 参数解析器
# ─────────────────────────────────────────────

class ParameterParser:
    """
    参数解析器：将 ${variable} 表达式替换为上下文中的实际值。

    示例：
        parser = ParameterParser({"order_id": "ORD-001"})
        result = parser.resolve("订单: ${order_id}")
        # -> "订单: ORD-001"
    """

    # 匹配 ${var_name}，变量名不含花括号
    _PATTERN: re.Pattern[str] = re.compile(r"\$\{([^{}]+)\}")

    def __init__(self, context: Optional[Dict[str, Any]] = None) -> None:
        self._context: Dict[str, Any] = context or {}

    def update(self, context: Dict[str, Any]) -> None:
        """合并新的上下文变量。"""
        self._context.update(context)

    def resolve(self, value: str) -> str:
        """替换字符串中的所有 ${var} 表达式。"""
        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            key = m.group(1).strip()
            replacement = self._context.get(key)
            if replacement is None:
                logger.warning("参数解析：变量 '%s' 未在上下文中找到", key)
                return m.group(0)  # 保留原始表达式
            return str(replacement)

        return self._PATTERN.sub(_replace, value)

    def resolve_params(self, params: List[StepParam]) -> List[StepParam]:
        """批量解析步骤参数列表。"""
        resolved = []
        for p in params:
            resolved.append(
                StepParam(
                    name=self.resolve(p.name),
                    value=self.resolve(p.value),
                    location=p.location,
                )
            )
        return resolved

    def resolve_path(self, path: str) -> str:
        """解析路径中的 ${var} 表达式（含尾部斜杠处理）。"""
        return self.resolve(path)

    def has_unresolved(self, value: str) -> bool:
        """检查字符串中是否仍有未解析的表达式。"""
        return bool(self._PATTERN.search(value))


# ─────────────────────────────────────────────
# § 7. OpenAPI 导入器
# ─────────────────────────────────────────────

class OpenAPIImporter:
    """
    从 OpenAPI 3.x / Swagger 2.x 规范字典或 JSON 文件中
    解析接口并转换为 PipelineStep 列表。
    """

    def __init__(self, spec: Dict[str, Any]) -> None:
        self._spec = spec
        self._version = self._detect_version()

    def _detect_version(self) -> str:
        if "openapi" in self._spec:
            return "3.x"
        if "swagger" in self._spec:
            return "2.x"
        return "unknown"

    @classmethod
    def from_file(cls, path: str) -> "OpenAPIImporter":
        """从 JSON 文件加载规范。"""
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
        return cls(spec)

    @classmethod
    def from_dict(cls, spec: Dict[str, Any]) -> "OpenAPIImporter":
        return cls(spec)

    def get_base_url(self) -> str:
        """提取 base URL。"""
        if self._version == "3.x":
            servers = self._spec.get("servers", [])
            if servers:
                return servers[0].get("url", "")
        elif self._version == "2.x":
            host = self._spec.get("host", "")
            base = self._spec.get("basePath", "/")
            schemes = self._spec.get("schemes", ["https"])
            scheme = schemes[0] if schemes else "https"
            return f"{scheme}://{host}{base}"
        return ""

    def list_endpoints(self) -> List[Dict[str, Any]]:
        """返回所有接口的基础信息列表。"""
        endpoints = []
        paths = self._spec.get("paths", {})
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if operation is None:
                    continue
                endpoints.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "summary": operation.get("summary", ""),
                        "operation_id": operation.get("operationId", ""),
                        "tags": operation.get("tags", []),
                        "parameters": operation.get("parameters", []),
                        "request_body": operation.get("requestBody", {}),
                    }
                )
        return endpoints

    def to_pipeline_steps(
        self,
        filter_tags: Optional[List[str]] = None,
    ) -> List[PipelineStep]:
        """将接口列表转换为 PipelineStep 列表。"""
        steps = []
        for ep in self.list_endpoints():
            if filter_tags and not any(t in ep["tags"] for t in filter_tags):
                continue
            params: List[StepParam] = []
            for param in ep.get("parameters", []):
                location = param.get("in", "query")
                name = param.get("name", "")
                # 用占位符作为默认值
                default_val = param.get("schema", {}).get("default", f"${{{name}}}")
                params.append(StepParam(name=name, value=str(default_val), location=location))
            step = PipelineStep(
                name=ep.get("operation_id") or f"{ep['method']}_{ep['path'].replace('/', '_').strip('_')}",
                method=ep["method"],
                path=ep["path"],
                params=params,
                description=ep.get("summary", ""),
            )
            steps.append(step)
        return steps

    def to_pipeline_plan(
        self,
        plan_name: str,
        filter_tags: Optional[List[str]] = None,
    ) -> PipelinePlan:
        """直接生成一个 PipelinePlan。"""
        return PipelinePlan(
            name=plan_name,
            steps=self.to_pipeline_steps(filter_tags=filter_tags),
            base_url=self.get_base_url(),
            description=f"从 OpenAPI({self._version}) 导入",
        )


# ─────────────────────────────────────────────
# § 8. 内置链路模板
# ─────────────────────────────────────────────

def _build_normal_order_pay(base_url: str = "") -> PipelinePlan:
    """
    内置模板：普通订单支付流程。
    步骤：用户登录 -> 创建订单 -> 发起支付 -> 查询支付状态
    """
    return PipelinePlan(
        name="normal_order_pay",
        base_url=base_url,
        description="普通商品下单支付完整链路",
        tags=["order", "payment"],
        steps=[
            PipelineStep(
                name="login",
                method="POST",
                path="/api/auth/login",
                params=[
                    StepParam(name="username", value="${username}", location="body"),
                    StepParam(name="password", value="${password}", location="body"),
                ],
                extracts=[
                    StepExtract(variable="access_token", jsonpath="data.token"),
                    StepExtract(variable="user_id", jsonpath="data.user_id"),
                ],
                assertions=[StepAssertion(expression="status == 200")],
                description="用户登录获取 token",
            ),
            PipelineStep(
                name="create_order",
                method="POST",
                path="/api/orders",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                    StepParam(name="product_id", value="${product_id}", location="body"),
                    StepParam(name="quantity", value="${quantity}", location="body"),
                    StepParam(name="user_id", value="${user_id}", location="body"),
                ],
                extracts=[StepExtract(variable="order_id", jsonpath="data.order_id")],
                assertions=[
                    StepAssertion(expression="status == 201"),
                    StepAssertion(expression="data.order_id != null"),
                ],
                description="创建订单",
            ),
            PipelineStep(
                name="pay_order",
                method="POST",
                path="/api/payments",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                    StepParam(name="order_id", value="${order_id}", location="body"),
                    StepParam(name="amount", value="${amount}", location="body"),
                    StepParam(name="payment_method", value="${payment_method}", location="body"),
                ],
                extracts=[StepExtract(variable="payment_id", jsonpath="data.payment_id")],
                assertions=[StepAssertion(expression="status == 200")],
                description="发起支付",
            ),
            PipelineStep(
                name="query_payment_status",
                method="GET",
                path="/api/payments/${payment_id}",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                ],
                extracts=[StepExtract(variable="payment_status", jsonpath="data.status")],
                assertions=[StepAssertion(expression="status == 200")],
                description="查询支付状态",
            ),
        ],
    )


def _build_coupon_order_pay(base_url: str = "") -> PipelinePlan:
    """
    内置模板：优惠券订单支付流程（含清理步骤）。
    步骤：登录 -> 获取优惠券 -> 创建优惠券订单 -> 支付 -> 取消订单（cleanup）
    """
    return PipelinePlan(
        name="coupon_order_pay",
        base_url=base_url,
        description="使用优惠券下单支付链路，含清理步骤",
        tags=["order", "coupon", "payment"],
        steps=[
            PipelineStep(
                name="login",
                method="POST",
                path="/api/auth/login",
                params=[
                    StepParam(name="username", value="${username}", location="body"),
                    StepParam(name="password", value="${password}", location="body"),
                ],
                extracts=[
                    StepExtract(variable="access_token", jsonpath="data.token"),
                    StepExtract(variable="user_id", jsonpath="data.user_id"),
                ],
                assertions=[StepAssertion(expression="status == 200")],
                description="用户登录",
            ),
            PipelineStep(
                name="get_coupon",
                method="GET",
                path="/api/coupons/available",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                    StepParam(name="user_id", value="${user_id}", location="query"),
                ],
                extracts=[
                    StepExtract(variable="coupon_id", jsonpath="data.coupons.0.id"),
                    StepExtract(variable="coupon_discount", jsonpath="data.coupons.0.discount"),
                ],
                assertions=[StepAssertion(expression="status == 200")],
                description="获取可用优惠券",
            ),
            PipelineStep(
                name="create_coupon_order",
                method="POST",
                path="/api/orders",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                    StepParam(name="product_id", value="${product_id}", location="body"),
                    StepParam(name="quantity", value="${quantity}", location="body"),
                    StepParam(name="coupon_id", value="${coupon_id}", location="body"),
                    StepParam(name="user_id", value="${user_id}", location="body"),
                ],
                extracts=[StepExtract(variable="order_id", jsonpath="data.order_id")],
                assertions=[StepAssertion(expression="status == 201")],
                description="使用优惠券创建订单",
            ),
            PipelineStep(
                name="pay_coupon_order",
                method="POST",
                path="/api/payments",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                    StepParam(name="order_id", value="${order_id}", location="body"),
                    StepParam(name="coupon_id", value="${coupon_id}", location="body"),
                    StepParam(name="amount", value="${amount}", location="body"),
                ],
                extracts=[StepExtract(variable="payment_id", jsonpath="data.payment_id")],
                assertions=[StepAssertion(expression="status == 200")],
                description="使用优惠券支付",
            ),
            PipelineStep(
                name="cancel_order_cleanup",
                method="DELETE",
                path="/api/orders/${order_id}",
                params=[
                    StepParam(name="Authorization", value="Bearer ${access_token}", location="header"),
                ],
                assertions=[StepAssertion(expression="status in [200, 204]")],
                cleanup=True,
                description="清理：取消测试订单",
            ),
        ],
    )


# 内置模板注册表：name -> factory function
BUILTIN_TEMPLATES: Dict[str, Any] = {
    "normal_order_pay": _build_normal_order_pay,
    "coupon_order_pay": _build_coupon_order_pay,
}


# ─────────────────────────────────────────────
# § 9. 线程安全指标收集器
# ─────────────────────────────────────────────

class MetricsCollector:
    """
    线程安全的执行指标收集器。
    使用 threading.Lock 保护内部状态。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs_total: int = 0
        self._runs_success: int = 0
        self._runs_failed: int = 0
        self._step_total: int = 0
        self._step_success: int = 0
        self._step_failed: int = 0
        self._total_elapsed_ms: float = 0.0
        self._plan_metrics: Dict[str, Dict[str, Any]] = {}

    def record_run(self, result: PipelineRunResult) -> None:
        """记录一次链路执行结果。"""
        with self._lock:
            self._runs_total += 1
            if result.success:
                self._runs_success += 1
            else:
                self._runs_failed += 1
            self._total_elapsed_ms += result.total_elapsed_ms

            for sr in result.step_results:
                self._step_total += 1
                if sr.success:
                    self._step_success += 1
                else:
                    self._step_failed += 1

            name = result.plan_name
            if name not in self._plan_metrics:
                self._plan_metrics[name] = {
                    "runs": 0,
                    "success": 0,
                    "failed": 0,
                    "total_ms": 0.0,
                }
            m = self._plan_metrics[name]
            m["runs"] += 1
            m["success"] += int(result.success)
            m["failed"] += int(not result.success)
            m["total_ms"] += result.total_elapsed_ms

    def snapshot(self) -> Dict[str, Any]:
        """返回当前指标快照（线程安全）。"""
        with self._lock:
            avg_ms = (
                self._total_elapsed_ms / self._runs_total
                if self._runs_total > 0
                else 0.0
            )
            return {
                "runs_total": self._runs_total,
                "runs_success": self._runs_success,
                "runs_failed": self._runs_failed,
                "step_total": self._step_total,
                "step_success": self._step_success,
                "step_failed": self._step_failed,
                "avg_elapsed_ms": round(avg_ms, 2),
                "per_plan": dict(self._plan_metrics),
            }

    def reset(self) -> None:
        """重置所有指标。"""
        with self._lock:
            self._runs_total = 0
            self._runs_success = 0
            self._runs_failed = 0
            self._step_total = 0
            self._step_success = 0
            self._step_failed = 0
            self._total_elapsed_ms = 0.0
            self._plan_metrics.clear()

    def __repr__(self) -> str:
        s = self.snapshot()
        return (
            f"MetricsCollector(runs={s['runs_total']}, "
            f"success={s['runs_success']}, failed={s['runs_failed']})"
        )


# ─────────────────────────────────────────────
# § 10. SQLite 持久化仓库
# ─────────────────────────────────────────────

class PipelineRepository:
    """
    SQLite 持久化仓库，存储 PipelinePlan 和执行历史。
    启用 WAL 模式提升并发读写性能。
    """

    _DDL_PLANS = """
        CREATE TABLE IF NOT EXISTS pipeline_plans (
            plan_id     TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """

    _DDL_RUNS = """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id       TEXT PRIMARY KEY,
            plan_name    TEXT NOT NULL,
            success      INTEGER NOT NULL,
            summary      TEXT NOT NULL,
            elapsed_ms   REAL NOT NULL,
            started_at   TEXT NOT NULL
        )
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """为当前线程返回/创建连接（线程本地存储）。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            # 启用 WAL 模式以提升并发性能
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            self._local.conn = conn
        return self._local.conn  # type: ignore[return-value]

    def _init_db(self) -> None:
        conn = self._connect()
        with conn:
            conn.execute(self._DDL_PLANS)
            conn.execute(self._DDL_RUNS)

    def save_plan(self, plan: PipelinePlan) -> None:
        """保存或更新链路计划。"""
        now = datetime.now(timezone.utc).isoformat()
        data = json.dumps(plan.to_dict(), ensure_ascii=False)
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO pipeline_plans (plan_id, name, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """,
                (plan.plan_id, plan.name, data, plan.created_at, now),
            )
        logger.debug("已保存链路计划: %s (%s)", plan.name, plan.plan_id[:8])

    def load_plan(self, name: str) -> Optional[PipelinePlan]:
        """按名称加载链路计划，不存在时返回 None。"""
        conn = self._connect()
        row = conn.execute(
            "SELECT data FROM pipeline_plans WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return PipelinePlan.from_dict(json.loads(row["data"]))

    def list_plans(self) -> List[Dict[str, str]]:
        """列出所有已保存的计划（仅元数据）。"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT plan_id, name, created_at, updated_at FROM pipeline_plans ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_plan(self, name: str) -> bool:
        """删除指定计划，返回是否成功。"""
        conn = self._connect()
        with conn:
            cursor = conn.execute(
                "DELETE FROM pipeline_plans WHERE name = ?", (name,)
            )
        return cursor.rowcount > 0

    def save_run_result(self, result: PipelineRunResult) -> None:
        """持久化执行结果摘要。"""
        conn = self._connect()
        summary = json.dumps(result.summary(), ensure_ascii=False)
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pipeline_runs
                (run_id, plan_name, success, summary, elapsed_ms, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.plan_name,
                    int(result.success),
                    summary,
                    result.total_elapsed_ms,
                    result.started_at,
                ),
            )

    def list_runs(self, plan_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """列出执行历史记录。"""
        conn = self._connect()
        if plan_name:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs WHERE plan_name=? ORDER BY started_at DESC LIMIT ?",
                (plan_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """关闭当前线程的数据库连接。"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def __repr__(self) -> str:
        return f"PipelineRepository(db={self._db_path!r})"


# ─────────────────────────────────────────────
# § 11. JSONPath 简化提取器
# ─────────────────────────────────────────────

def _simple_jsonpath_extract(data: Any, path: str) -> Any:
    """
    简化 JSONPath 提取：支持 "a.b.c" 和数组下标 "a.0.b"。
    不依赖第三方库，满足大多数使用场景。
    """
    keys = path.split(".")
    current = data
    for key in keys:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            with contextlib.suppress(ValueError, IndexError):
                current = current[int(key)]
        else:
            return None
    return current


# ─────────────────────────────────────────────
# § 12. HTTP 步骤执行器
# ─────────────────────────────────────────────

class HttpStepExecutor:
    """
    HTTP 步骤执行器。
    负责将 PipelineStep 翻译为 HTTP 请求并执行，提取变量，校验断言。
    """

    def __init__(self, base_url: str, parser: ParameterParser) -> None:
        self._base_url = base_url.rstrip("/")
        self._parser = parser
        # 尝试使用 requests.Session 以复用连接
        self._session: Any = None
        with contextlib.suppress(NameError):
            self._session = requests.Session()  # type: ignore[name-defined]

    def _eval_assertion(self, expression: str, status_code: int, body: Any) -> bool:
        """
        简单断言求值器（不使用 eval，保证安全性）。
        支持的表达式：
          - "status == 200"
          - "status == 201"
          - "status in [200, 204]"
          - "data.key != null"
        """
        expr = expression.strip()

        # status == N
        m = re.fullmatch(r"status\s*==\s*(\d+)", expr)
        if m:
            return status_code == int(m.group(1))

        # status in [N, M, ...]
        m = re.fullmatch(r"status\s+in\s+\[([0-9,\s]+)\]", expr)
        if m:
            codes = [int(c.strip()) for c in m.group(1).split(",")]
            return status_code in codes

        # data.path != null
        m = re.fullmatch(r"(.+?)\s*!=\s*null", expr)
        if m:
            val = _simple_jsonpath_extract(body, m.group(1).strip())
            return val is not None

        # data.path == value
        m = re.fullmatch(r"(.+?)\s*==\s*(.+)", expr)
        if m:
            val = _simple_jsonpath_extract(body, m.group(1).strip())
            expected = m.group(2).strip().strip('"').strip("'")
            return str(val) == expected

        logger.warning("不支持的断言表达式: %s（默认通过）", expression)
        return True

    def execute_step(self, step: PipelineStep) -> StepResult:
        """执行单个步骤，返回 StepResult。"""
        if self._session is None:
            logger.error("requests 库未安装，无法执行 HTTP 步骤: %s", step.name)
            return StepResult(
                step_name=step.name,
                success=False,
                error="requests 库未安装",
            )

        last_error = ""
        for attempt in range(max(step.retries + 1, 1)):
            try:
                return self._do_request(step, attempt)
            except StepExecutionError as exc:
                last_error = str(exc)
                if attempt < step.retries:
                    logger.warning(
                        "步骤 %s 第 %d 次重试（原因: %s）",
                        step.name, attempt + 1, last_error,
                    )
                    time.sleep(0.5 * (attempt + 1))
                else:
                    break

        return StepResult(
            step_name=step.name,
            success=False,
            error=last_error,
        )

    def _do_request(self, step: PipelineStep, attempt: int) -> StepResult:
        """实际发送 HTTP 请求。"""
        resolved_params = self._parser.resolve_params(step.params)
        resolved_path = self._parser.resolve_path(step.path)
        url = urljoin(self._base_url + "/", resolved_path.lstrip("/"))

        # 分组参数
        headers: Dict[str, str] = {}
        query_params: Dict[str, str] = {}
        body_data: Dict[str, Any] = {}
        path_params: Dict[str, str] = {}

        for p in resolved_params:
            if p.location == "header":
                headers[p.name] = p.value
            elif p.location == "query":
                query_params[p.name] = p.value
            elif p.location == "path":
                path_params[p.name] = p.value
            else:  # body
                body_data[p.name] = p.value

        # 替换路径参数
        for k, v in path_params.items():
            url = url.replace(f"{{{k}}}", v)

        t0 = time.perf_counter()
        try:
            resp = self._session.request(  # type: ignore[union-attr]
                method=step.method,
                url=url,
                headers=headers,
                params=query_params if query_params else None,
                json=body_data if body_data else None,
                timeout=step.timeout,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
        except Exception as exc:
            raise StepExecutionError(
                str(exc), step_name=step.name
            ) from exc

        # 解析响应体
        body: Any = None
        with contextlib.suppress(Exception):
            body = resp.json()

        # 提取变量
        extracted: Dict[str, Any] = {}
        for ex in step.extracts:
            val = _simple_jsonpath_extract(body, ex.jsonpath)
            if val is not None:
                extracted[ex.variable] = val
                self._parser.update({ex.variable: val})
            else:
                logger.warning("提取变量失败: %s (jsonpath=%s)", ex.variable, ex.jsonpath)

        # 断言校验
        assertion_errors: List[str] = []
        for assertion in step.assertions:
            passed = self._eval_assertion(assertion.expression, resp.status_code, body)
            if not passed:
                assertion_errors.append(
                    f"断言失败: {assertion.expression} "
                    f"(HTTP {resp.status_code})"
                )

        success = len(assertion_errors) == 0
        error_msg = "; ".join(assertion_errors)

        result = StepResult(
            step_name=step.name,
            success=success,
            status_code=resp.status_code,
            response_body=body,
            extracted=extracted,
            error=error_msg,
            elapsed_ms=round(elapsed_ms, 2),
        )

        if not success:
            raise StepExecutionError(
                error_msg, step_name=step.name, status_code=resp.status_code
            )

        return result


# ─────────────────────────────────────────────
# § 13. 健康检查器
# ─────────────────────────────────────────────

class HealthChecker:
    """
    检查目标服务的连通性（通过 HTTP HEAD/GET 请求）。
    """

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def check(self) -> Dict[str, Any]:
        """
        检查 base_url 的连通性，返回检查结果字典。

        返回字段：
          - reachable: bool
          - status_code: int (HTTP 状态码，0 表示连接失败)
          - latency_ms: float
          - error: str
        """
        result: Dict[str, Any] = {
            "base_url": self._base_url,
            "reachable": False,
            "status_code": 0,
            "latency_ms": 0.0,
            "error": "",
        }

        if not self._base_url:
            result["error"] = "base_url 为空"
            return result

        t0 = time.perf_counter()
        try:
            session = requests.Session()  # type: ignore[name-defined]
            resp = session.head(self._base_url, timeout=self._timeout, allow_redirects=True)
            result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            result["status_code"] = resp.status_code
            result["reachable"] = resp.status_code < 500
        except NameError:
            result["error"] = "requests 库未安装，无法进行健康检查"
        except Exception as exc:
            result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            result["error"] = str(exc)

        return result

    def __repr__(self) -> str:
        return f"HealthChecker(base_url={self._base_url!r}, timeout={self._timeout}s)"


# ─────────────────────────────────────────────
# § 14. 链路校验器
# ─────────────────────────────────────────────

class PipelineValidator:
    """
    提前校验 PipelinePlan 的合法性，发现问题尽早报告。
    """

    # 合法 HTTP 方法
    _VALID_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

    def validate(self, plan: PipelinePlan) -> List[str]:
        """
        校验 PipelinePlan，返回错误信息列表。
        列表为空表示校验通过。
        """
        errors: List[str] = []
        if not plan.name:
            errors.append("plan.name 不能为空")
        if not plan.steps:
            errors.append("plan.steps 不能为空")
            return errors  # 无步骤，后续校验无意义

        step_names: List[str] = []
        for i, step in enumerate(plan.steps):
            prefix = f"steps[{i}]({step.name!r})"

            if not step.name:
                errors.append(f"{prefix}: name 不能为空")
            if step.name in step_names:
                errors.append(f"{prefix}: 步骤名称重复")
            step_names.append(step.name)

            if step.method.upper() not in self._VALID_METHODS:
                errors.append(f"{prefix}: 无效的 HTTP 方法 {step.method!r}")

            if not step.path:
                errors.append(f"{prefix}: path 不能为空")

            if step.timeout <= 0:
                errors.append(f"{prefix}: timeout 必须大于 0")

            if step.retries < 0:
                errors.append(f"{prefix}: retries 不能为负数")

            for j, p in enumerate(step.params):
                if not p.name:
                    errors.append(f"{prefix}.params[{j}]: name 不能为空")
                if p.location not in ("body", "query", "header", "path"):
                    errors.append(f"{prefix}.params[{j}]: 无效的 location {p.location!r}")

        return errors

    def validate_or_raise(self, plan: PipelinePlan) -> None:
        """校验不通过时抛出 PlanValidationError。"""
        errors = self.validate(plan)
        if errors:
            raise PlanValidationError(
                f"链路 {plan.name!r} 校验失败，共 {len(errors)} 个错误",
                errors=errors,
            )

    def __repr__(self) -> str:
        return "PipelineValidator()"


# ─────────────────────────────────────────────
# § 15. 核心编排后端
# ─────────────────────────────────────────────

class OrchestrationBackend:
    """
    企业级 API 编排后端。

    职责：
      - 管理链路计划注册表（内置模板 + 用户自定义）
      - 执行链路（含 cleanup 步骤支持）
      - 持久化执行结果
      - 收集执行指标
      - 支持热重载注册表（reload_registry）
    """

    def __init__(
        self,
        base_url: str = "",
        db_path: str = ":memory:",
        enable_cleanup: bool = True,
        strict_assertions: bool = True,
    ) -> None:
        self._base_url = base_url
        self._enable_cleanup = enable_cleanup
        self._strict_assertions = strict_assertions

        self._registry: Dict[str, PipelinePlan] = {}
        self._lock = threading.Lock()

        self._repo = PipelineRepository(db_path)
        self._metrics = MetricsCollector()
        self._validator = PipelineValidator()

        # 加载内置模板
        self._load_builtin_templates()
        logger.info("OrchestrationBackend 初始化完成（base_url=%s）", base_url or "(未设置)")

    def _load_builtin_templates(self) -> None:
        """加载所有内置链路模板到注册表。"""
        for name, factory in BUILTIN_TEMPLATES.items():
            plan = factory(self._base_url)
            with self._lock:
                self._registry[name] = plan
        logger.debug("已加载 %d 个内置模板", len(BUILTIN_TEMPLATES))

    def reload_registry(self) -> None:
        """
        热重载注册表：
          1. 重新加载内置模板（base_url 可能已更新）
          2. 从数据库重新加载用户保存的计划
        适用于运行期间 base_url 变更或外部修改了数据库的场景。
        """
        logger.info("正在热重载链路注册表...")
        with self._lock:
            self._registry.clear()
        self._load_builtin_templates()

        # 从数据库恢复用户计划
        for meta in self._repo.list_plans():
            plan = self._repo.load_plan(meta["name"])
            if plan and meta["name"] not in BUILTIN_TEMPLATES:
                with self._lock:
                    self._registry[plan.name] = plan
        logger.info("注册表热重载完成，共 %d 个计划", len(self._registry))

    def register_plan(self, plan: PipelinePlan, save_to_db: bool = True) -> None:
        """注册自定义链路计划。"""
        self._validator.validate_or_raise(plan)
        with self._lock:
            self._registry[plan.name] = plan
        if save_to_db:
            self._repo.save_plan(plan)
        logger.info("已注册链路计划: %s", plan.name)

    def get_plan(self, name: str) -> PipelinePlan:
        """获取链路计划，不存在时抛出 RegistryError。"""
        with self._lock:
            plan = self._registry.get(name)
        if plan is None:
            # 尝试从数据库加载
            plan = self._repo.load_plan(name)
            if plan is None:
                raise RegistryError(
                    f"链路计划 {name!r} 不存在（注册表和数据库中均未找到）",
                    plan_name=name,
                )
            with self._lock:
                self._registry[name] = plan
        return plan

    def list_plans(self) -> List[str]:
        """列出所有已注册的计划名称。"""
        with self._lock:
            return list(self._registry.keys())

    def run(
        self,
        plan_name: str,
        user_inputs: Optional[Dict[str, Any]] = None,
        run_cleanup: Optional[bool] = None,
    ) -> PipelineRunResult:
        """
        执行指定链路计划。

        Args:
            plan_name:    链路名称（注册表中的 key）
            user_inputs:  用户输入参数（会合并到上下文）
            run_cleanup:  是否执行 cleanup 步骤，None 表示使用 enable_cleanup 配置

        Returns:
            PipelineRunResult 执行结果
        """
        plan = self.get_plan(plan_name)
        should_cleanup = run_cleanup if run_cleanup is not None else self._enable_cleanup

        # 初始化上下文和解析器
        context: Dict[str, Any] = {**(user_inputs or {})}
        parser = ParameterParser(context)
        executor = HttpStepExecutor(
            base_url=plan.base_url or self._base_url,
            parser=parser,
        )

        run_result = PipelineRunResult(plan_name=plan_name)
        t_start = time.perf_counter()

        logger.info("开始执行链路: %s（run_id=%s）", plan_name, run_result.run_id[:8])

        for step in plan.steps:
            # 跳过 cleanup 步骤（如果未启用）
            if step.cleanup and not should_cleanup:
                logger.debug("跳过 cleanup 步骤: %s", step.name)
                continue

            logger.debug("执行步骤: %s [%s %s]", step.name, step.method, step.path)
            try:
                step_result = executor.execute_step(step)
                run_result.step_results.append(step_result)
                # 将提取的变量合并到上下文
                run_result.context.update(step_result.extracted)
                parser.update(step_result.extracted)

                if not step_result.success and not step.cleanup:
                    if self._strict_assertions:
                        run_result.error = (
                            f"步骤 {step.name!r} 执行失败: {step_result.error}"
                        )
                        break

            except StepExecutionError as exc:
                step_result = StepResult(
                    step_name=step.name,
                    success=False,
                    error=str(exc),
                )
                run_result.step_results.append(step_result)
                if not step.cleanup:
                    run_result.error = str(exc)
                    break

        run_result.total_elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
        run_result.success = (
            not run_result.error
            and all(
                sr.success for sr in run_result.step_results
                if not any(s.cleanup and s.name == sr.step_name for s in plan.steps)
            )
        )

        # 持久化
        self._repo.save_run_result(run_result)
        self._metrics.record_run(run_result)

        log_fn = logger.info if run_result.success else logger.warning
        log_fn(
            "链路 %s 执行%s，耗时 %.1fms",
            plan_name,
            "成功" if run_result.success else "失败",
            run_result.total_elapsed_ms,
        )
        return run_result

    def get_metrics(self) -> Dict[str, Any]:
        """获取执行指标快照。"""
        return self._metrics.snapshot()

    def reset_metrics(self) -> None:
        """重置执行指标。"""
        self._metrics.reset()

    def set_base_url(self, base_url: str) -> None:
        """动态更新 base_url 并热重载注册表。"""
        self._base_url = base_url
        self.reload_registry()

    def __repr__(self) -> str:
        return (
            f"OrchestrationBackend(base_url={self._base_url!r}, "
            f"plans={len(self._registry)}, "
            f"db={self._repo._db_path!r})"
        )

    def __str__(self) -> str:
        plans = ", ".join(self.list_plans())
        return f"OrchestrationBackend [{plans}] @ {self._base_url}"


# ─────────────────────────────────────────────
# § 16. LLM 规划器（openai 可选）
# ─────────────────────────────────────────────

class LLMPlanner:
    """
    基于 LLM（OpenAI）的链路规划器。
    当 openai 库不可用时，回退到规则匹配模式。
    """

    _SYSTEM_PROMPT = (
        "你是一个 API 链路规划专家，根据用户的测试目标，"
        "从提供的 API 列表中选择合适的步骤，并以 JSON 格式输出链路计划。"
        "输出格式: {\"steps\": [{\"name\": ..., \"method\": ..., \"path\": ..., \"params\": [...]}]}"
    )

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        fallback_plans: Optional[Dict[str, str]] = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback_plans = fallback_plans or {}
        if _openai_available and api_key:
            openai.api_key = api_key  # type: ignore[name-defined]
        elif api_key:
            logger.warning("openai 库未安装，LLMPlanner 将使用规则回退模式")

    def plan(self, goal: str, available_apis: List[Dict[str, Any]]) -> Optional[PipelinePlan]:
        """
        根据目标描述和可用 API 列表生成 PipelinePlan。
        """
        if _openai_available and self._api_key:
            return self._plan_via_llm(goal, available_apis)
        return self._plan_via_rules(goal)

    def _plan_via_llm(
        self, goal: str, available_apis: List[Dict[str, Any]]
    ) -> Optional[PipelinePlan]:
        """调用 OpenAI API 生成链路计划。"""
        api_list_str = json.dumps(available_apis, ensure_ascii=False, indent=2)
        user_message = f"测试目标：{goal}\n\n可用 API 列表：\n{api_list_str}"
        try:
            client = openai.OpenAI(api_key=self._api_key)  # type: ignore[name-defined]
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = resp.choices[0].message.content or "{}"
            data = json.loads(content)
            plan_name = f"llm_plan_{uuid.uuid4().hex[:8]}"
            steps = [
                PipelineStep(
                    name=s.get("name", f"step_{i}"),
                    method=s.get("method", "GET"),
                    path=s.get("path", "/"),
                    params=[StepParam(**p) for p in s.get("params", [])],
                )
                for i, s in enumerate(data.get("steps", []))
            ]
            return PipelinePlan(name=plan_name, steps=steps, description=goal)
        except Exception as exc:
            logger.error("LLM 规划失败: %s", exc)
            return None

    def _plan_via_rules(self, goal: str) -> Optional[PipelinePlan]:
        """基于关键词的规则回退规划。"""
        goal_lower = goal.lower()
        for keyword, template_name in self._fallback_plans.items():
            if keyword in goal_lower:
                logger.info("规则匹配: 目标包含 '%s'，使用模板 '%s'", keyword, template_name)
                factory = BUILTIN_TEMPLATES.get(template_name)
                if factory:
                    return factory()
        logger.warning("规则回退规划无法匹配目标: %s", goal)
        return None

    def __repr__(self) -> str:
        mode = "LLM" if (_openai_available and self._api_key) else "规则回退"
        return f"LLMPlanner(model={self._model!r}, mode={mode})"


# ─────────────────────────────────────────────
# § 17. Pytest 草稿生成器
# ─────────────────────────────────────────────

class PytestCaseGenerator:
    """
    将 PipelinePlan 转换为 pytest 测试代码草稿。
    生成的代码可直接作为测试基础进行微调。
    """

    def generate(self, plan: PipelinePlan, base_url: str = "") -> str:
        """
        根据链路计划生成 pytest 测试代码。

        Args:
            plan:     PipelinePlan 对象
            base_url: 覆盖 plan 中的 base_url（可选）

        Returns:
            Python 源代码字符串
        """
        effective_url = base_url or plan.base_url or "http://localhost:8000"
        class_name = "".join(w.capitalize() for w in plan.name.split("_"))
        lines: List[str] = [
            "# 此文件由 PytestCaseGenerator 自动生成，请根据实际情况修改",
            "# Generated by PytestCaseGenerator - edit before production use",
            "",
            "import pytest",
            "import requests",
            "",
            f'BASE_URL = "{effective_url}"',
            "",
            "",
            f"class Test{class_name}:",
            f'    """自动生成的 {plan.name} 链路测试用例。"""',
            "",
            "    @pytest.fixture(autouse=True)",
            "    def setup(self):",
            "        self.context: dict = {}",
            "",
        ]

        for step in plan.steps:
            method_name = f"test_{step.name}"
            lines.append(f"    def {method_name}(self):")
            lines.append(f'        """步骤: {step.description or step.name}"""')

            # 构建请求参数代码
            headers: List[str] = []
            query: List[str] = []
            body: List[str] = []
            for p in step.params:
                # 提取参数的上下文键名：${var} -> var，否则原样保留
                ctx_key = p.name[2:-1] if p.name.startswith("${") and p.name.endswith("}") else p.name
                val_expr = f'self.context.get("{ctx_key}", "{p.value}")'
                if p.location == "header":
                    headers.append(f'            "{p.name}": {val_expr}')
                elif p.location == "query":
                    query.append(f'            "{p.name}": {val_expr}')
                else:
                    body.append(f'            "{p.name}": {val_expr}')

            if headers:
                lines.append(f"        headers = {{")
                lines.extend(headers)
                lines.append("        }")
            else:
                lines.append("        headers = {}")

            path = step.path
            # 将 ${var} 替换为 f-string 形式 {self.context.get("var", "")}
            # 路径模板中不含用户可控数据，替换结果仅用于生成静态测试代码
            path_fstr = re.sub(r"\$\{([^{}]+)\}", r'{self.context.get("\1", "")}', path)
            # 对 effective_url 中可能出现的双引号进行转义，确保生成代码语法正确
            safe_url = effective_url.replace('"', '\\"')
            lines.append(
                f'        url = f"{safe_url}{path_fstr}"'
            )

            call_args = ["url", "headers=headers"]
            if body:
                lines.append("        payload = {")
                lines.extend(body)
                lines.append("        }")
                call_args.append("json=payload")
            if query:
                lines.append("        params = {")
                lines.extend(query)
                lines.append("        }")
                call_args.append("params=params")

            lines.append(
                f"        resp = requests.{step.method.lower()}({', '.join(call_args)})"
            )

            # 断言
            for assertion in step.assertions:
                m = re.fullmatch(r"status\s*==\s*(\d+)", assertion.expression.strip())
                if m:
                    lines.append(f"        assert resp.status_code == {m.group(1)}")
                else:
                    lines.append(
                        f"        # 断言: {assertion.expression}"
                    )

            # 提取
            if step.extracts:
                lines.append("        data = resp.json()")
                for ex in step.extracts:
                    keys = ex.jsonpath.split(".")
                    access = "data"
                    for k in keys:
                        if k.isdigit():
                            access += f"[{k}]"
                        else:
                            access += f'.get("{k}", "")'
                    lines.append(f'        self.context["{ex.variable}"] = {access}')

            lines.append("")

        return "\n".join(lines)

    def save(self, plan: PipelinePlan, output_path: str, base_url: str = "") -> None:
        """将生成的测试代码保存到文件。"""
        code = self.generate(plan, base_url=base_url)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        logger.info("测试草稿已保存至: %s", output_path)

    def __repr__(self) -> str:
        return "PytestCaseGenerator()"


# ─────────────────────────────────────────────
# § 18. 使用示例
# ─────────────────────────────────────────────

def example_normal_order_pay() -> None:
    """
    示例 1：使用内置 normal_order_pay 模板执行普通订单支付链路。

    演示：
      - 创建 OrchestrationBackend
      - 获取预置链路计划
      - 传入 user_inputs 执行
      - 打印执行摘要
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("=== 示例 1: 普通订单支付链路 ===")

    # 1. 初始化后端（此处 base_url 为演示值，实际中替换为真实服务地址）
    backend = OrchestrationBackend(
        base_url="http://demo-api.example.com",
        db_path=":memory:",
        enable_cleanup=False,
        strict_assertions=False,   # 演示时不中断执行
    )

    # 2. 查看已注册的链路
    logger.info("已注册链路: %s", backend.list_plans())

    # 3. 获取计划（只读，不执行）
    plan = backend.get_plan("normal_order_pay")
    logger.info("链路详情: %s", plan)

    # 4. 准备用户输入参数
    user_inputs = {
        "username": "test_user",
        "password": "test_pass_123",
        "product_id": "PROD-001",
        "quantity": "2",
        "amount": "199.00",
        "payment_method": "wechat_pay",
    }

    # 5. 执行链路
    # 注意：因 demo-api.example.com 不可达，此处展示执行结果的结构
    result = backend.run("normal_order_pay", user_inputs=user_inputs)

    # 6. 打印执行摘要
    summary = result.summary()
    logger.info("执行摘要: %s", json.dumps(summary, ensure_ascii=False, indent=2))
    logger.info("上下文变量: %s", result.context)

    # 7. 查看指标
    metrics = backend.get_metrics()
    logger.info("执行指标: %s", json.dumps(metrics, ensure_ascii=False, indent=2))


def example_coupon_order_with_cleanup() -> None:
    """
    示例 2：使用内置 coupon_order_pay 模板，启用 cleanup 步骤。

    演示：
      - 启用 cleanup 步骤，执行清理资源的完整链路
      - 从 PipelineRunResult 中提取关键上下文变量
      - 展示健康检查器的使用
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("=== 示例 2: 优惠券订单支付（含 Cleanup）链路 ===")

    # 1. 健康检查（建议在执行前确认服务可达）
    base_url = "http://demo-api.example.com"
    checker = HealthChecker(base_url=base_url, timeout=3.0)
    health = checker.check()
    logger.info("健康检查结果: %s", health)

    # 2. 初始化后端，启用 cleanup
    backend = OrchestrationBackend(
        base_url=base_url,
        db_path=":memory:",
        enable_cleanup=True,        # 启用 cleanup 步骤
        strict_assertions=False,
    )

    # 3. 准备用户输入
    user_inputs = {
        "username": "coupon_tester",
        "password": "coupon_pass_456",
        "product_id": "PROD-002",
        "quantity": "1",
        "amount": "88.00",
    }

    # 4. 执行优惠券订单链路（含 cleanup）
    result = backend.run(
        "coupon_order_pay",
        user_inputs=user_inputs,
        run_cleanup=True,           # 显式启用 cleanup
    )

    # 5. 提取关键上下文变量
    context = result.context
    logger.info("提取的关键变量:")
    for key in ("access_token", "user_id", "coupon_id", "order_id", "payment_id"):
        logger.info("  %s = %s", key, context.get(key, "(未提取到)"))

    # 6. 打印完整执行结果（使用 __str__）
    logger.info("\n%s", result)

    # 7. 分析每步执行情况
    logger.info("逐步执行结果:")
    for sr in result.step_results:
        logger.info("  %r", sr)


def example_custom_plan_from_dict() -> None:
    """
    示例 3：从 JSON 字典动态构建 PipelinePlan。

    演示：
      - 从字典构建包含 extracts、assertions、params ${变量} 的自定义链路
      - 使用 PipelineValidator 校验计划
      - 保存 plan 到数据库并重新加载执行
      - 使用 PytestCaseGenerator 生成 pytest 草稿
      - 演示 OrchestrationBackend.reload_registry() 热重载
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("=== 示例 3: 自定义链路（从字典构建） ===")

    # 1. 用字典定义链路
    plan_dict: Dict[str, Any] = {
        "name": "custom_user_profile_update",
        "base_url": "http://demo-api.example.com",
        "description": "用户资料更新完整链路",
        "tags": ["user", "profile"],
        "steps": [
            {
                "name": "login",
                "method": "POST",
                "path": "/api/auth/login",
                "params": [
                    {"name": "username", "value": "${username}", "location": "body"},
                    {"name": "password", "value": "${password}", "location": "body"},
                ],
                "extracts": [
                    {"variable": "token", "jsonpath": "data.token"},
                    {"variable": "uid", "jsonpath": "data.user_id"},
                ],
                "assertions": [{"expression": "status == 200"}],
                "timeout": 10.0,
                "retries": 1,
                "cleanup": False,
                "description": "用户登录",
            },
            {
                "name": "get_profile",
                "method": "GET",
                "path": "/api/users/${uid}/profile",
                "params": [
                    {"name": "Authorization", "value": "Bearer ${token}", "location": "header"},
                ],
                "extracts": [
                    {"variable": "current_nickname", "jsonpath": "data.nickname"},
                ],
                "assertions": [
                    {"expression": "status == 200"},
                    {"expression": "data.user_id != null"},
                ],
                "timeout": 10.0,
                "retries": 0,
                "cleanup": False,
                "description": "获取用户资料",
            },
            {
                "name": "update_profile",
                "method": "PUT",
                "path": "/api/users/${uid}/profile",
                "params": [
                    {"name": "Authorization", "value": "Bearer ${token}", "location": "header"},
                    {"name": "nickname", "value": "${new_nickname}", "location": "body"},
                    {"name": "avatar_url", "value": "${avatar_url}", "location": "body"},
                ],
                "extracts": [
                    {"variable": "updated_at", "jsonpath": "data.updated_at"},
                ],
                "assertions": [{"expression": "status == 200"}],
                "timeout": 15.0,
                "retries": 1,
                "cleanup": False,
                "description": "更新用户资料",
            },
        ],
    }

    # 2. 从字典构建 PipelinePlan
    plan = PipelinePlan.from_dict(plan_dict)
    logger.info("构建的链路计划: %r", plan)

    # 3. 使用 PipelineValidator 校验
    validator = PipelineValidator()
    errors = validator.validate(plan)
    if errors:
        logger.error("校验失败: %s", errors)
        return
    logger.info("链路校验通过（无错误）")

    # 4. 使用持久化数据库（此处用 /tmp 避免污染工作目录）
    import tempfile
    import os
    tmp_db = os.path.join(tempfile.gettempdir(), "orchestration_demo.db")
    backend = OrchestrationBackend(
        base_url="http://demo-api.example.com",
        db_path=tmp_db,
        strict_assertions=False,
    )

    # 5. 注册并保存到数据库
    backend.register_plan(plan, save_to_db=True)
    logger.info("已注册计划: %s", backend.list_plans())

    # 6. 演示热重载（模拟重启后从数据库恢复）
    backend.reload_registry()
    logger.info("热重载后注册表: %s", backend.list_plans())

    # 7. 重新加载并执行（数据库中的计划在热重载后恢复）
    user_inputs = {
        "username": "jane_doe",
        "password": "secret_789",
        "new_nickname": "Janie",
        "avatar_url": "https://cdn.example.com/avatars/jane.png",
    }
    result = backend.run("custom_user_profile_update", user_inputs=user_inputs)
    logger.info("执行摘要: %s", json.dumps(result.summary(), ensure_ascii=False, indent=2))

    # 8. 生成 pytest 草稿
    generator = PytestCaseGenerator()
    pytest_code = generator.generate(plan, base_url="http://demo-api.example.com")

    # 保存到 /tmp 目录
    output_path = os.path.join(tempfile.gettempdir(), "test_custom_user_profile_update.py")
    generator.save(plan, output_path, base_url="http://demo-api.example.com")
    logger.info("Pytest 草稿已生成，路径: %s", output_path)
    logger.info("Pytest 草稿内容（前 20 行）:\n%s", "\n".join(pytest_code.splitlines()[:20]))

    # 9. 清理临时文件
    with contextlib.suppress(OSError):
        os.remove(tmp_db)


# ─────────────────────────────────────────────
# § 19. 程序入口（运行示例）
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    logger.info("api_orchestration_backend_enterprise v%s 示例开始", __version__)
    logger.info("Python %s", sys.version)

    logger.info("\n" + "─" * 60)
    example_normal_order_pay()

    logger.info("\n" + "─" * 60)
    example_coupon_order_with_cleanup()

    logger.info("\n" + "─" * 60)
    example_custom_plan_from_dict()

    logger.info("\n所有示例执行完毕。")
