"""
接口智能编排与链式执行引擎（API Chain Execution Engine）
合并单文件版 - 包含所有模块代码

运行方式：
    python api_chain_engine_all.py

演示两条业务链路：
    链路1: 商品下单完整流程 (A → C → E → G)
    链路2: 下单并支付流程  (A → C → D → E → F → G)

依赖安装：
    pip install requests requests-mock jsonpath-ng jmespath rich loguru pyyaml
"""
from __future__ import annotations

# ============================================================
# 标准库导入
# ============================================================
import base64
import copy
import hashlib
import json
import os
import random
import re
import sqlite3
import string
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

# ============================================================
# 第三方库导入
# ============================================================
import jmespath
import requests as requests_lib
import requests_mock as requests_mock_lib
import yaml
from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ============================================================
# 模块 1: config.py — 全局配置
# ============================================================

class Config:
    """全局配置"""
    BASE_URL: str = os.getenv("BASE_URL", "https://api.example.com")
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))
    DB_PATH: str = os.getenv("DB_PATH", "chain_store.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "execution.log")
    REPORT_DIR: str = os.getenv("REPORT_DIR", "reports/")
    MAX_RETRY: int = int(os.getenv("MAX_RETRY", "3"))
    RETRY_INTERVAL: float = float(os.getenv("RETRY_INTERVAL", "1.0"))
    MOCK_ENABLED: bool = os.getenv("MOCK_ENABLED", "true").lower() == "true"
    ENV: str = os.getenv("ENV", "test")  # test | staging | prod


config = Config()

# ============================================================
# 模块 2: models/api_def.py — 接口定义模型
# ============================================================

@dataclass
class APIDefinition:
    """接口定义模型，描述一个 HTTP 接口的完整信息"""
    api_id: str                        # 唯一标识，如 "user_login"
    name: str                          # 接口名称
    method: str                        # HTTP 方法：GET / POST / PUT / DELETE 等
    url: str                           # 支持模板变量，如 "{{base_url}}/api/login"
    headers: dict[str, Any] = field(default_factory=dict)   # 请求头模板
    params: dict[str, Any] = field(default_factory=dict)    # Query 参数模板
    body: dict[str, Any] = field(default_factory=dict)      # 请求体模板（支持嵌套模板变量）
    timeout: int = 30                  # 超时秒数
    description: str = ""             # 接口描述
    module: str = ""                  # 所属模块（如 "用户模块"、"订单模块"）
    tags: list[str] = field(default_factory=list)           # 标签

    def __post_init__(self) -> None:
        self.method = self.method.upper()

# ============================================================
# 模块 3: models/step.py — 步骤定义模型
# ============================================================

@dataclass
class ExtractRule:
    """响应提取规则"""
    var_name: str           # 提取后存入上下文的变量名
    source: str             # 来源: "body" | "header" | "status_code"
    extractor: str          # 提取器类型: "jsonpath" | "regex" | "jmespath" | "key"
    expression: str         # 提取表达式，如 "$.data.token" 或 "order_id=(\\d+)"
    default: Any = None     # 提取失败时的默认值


@dataclass
class AssertRule:
    """断言规则"""
    name: str               # 断言名称
    source: str             # 来源: "body" | "header" | "status_code" | "context"
    expression: str         # JSONPath 或 key
    operator: str           # 操作符: "eq" | "ne" | "gt" | "lt" | "contains" 等
    expected: Any = None    # 期望值（支持模板变量）
    message: str = ""       # 断言失败提示


@dataclass
class StepDefinition:
    """步骤定义模型"""
    step_id: str                                            # 步骤ID
    api_id: str                                             # 引用的接口ID
    name: str                                               # 步骤名称
    param_overrides: dict[str, Any] = field(default_factory=dict)       # 参数覆盖（支持模板变量）
    extracts: list[ExtractRule] = field(default_factory=list)           # 响应提取规则列表
    assertions: list[AssertRule] = field(default_factory=list)          # 断言规则列表
    depends_on: list[str] = field(default_factory=list)                 # 依赖的步骤ID列表
    on_failure: str = "stop"                                            # 失败策略: "stop" | "continue" | "skip_next"
    pre_scripts: list[str] = field(default_factory=list)                # 前置脚本（Python 表达式）
    post_scripts: list[str] = field(default_factory=list)               # 后置脚本

# ============================================================
# 模块 4: models/chain.py — 链路模型
# ============================================================

@dataclass
class RequestRecord:
    """请求记录"""
    method: str
    url: str
    headers: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: Any = None


@dataclass
class ResponseRecord:
    """响应记录"""
    status_code: int = 0
    headers: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    text: str = ""


@dataclass
class AssertionRecord:
    """断言记录"""
    name: str
    passed: bool
    expected: Any
    actual: Any
    operator: str
    message: str = ""
    error: str | None = None


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    api_id: str
    name: str
    status: str                                                         # "success" | "failed" | "skipped"
    request: RequestRecord = field(default_factory=RequestRecord)
    response: ResponseRecord = field(default_factory=ResponseRecord)
    extractions: dict[str, Any] = field(default_factory=dict)          # 本步骤提取的变量
    assertions: list[AssertionRecord] = field(default_factory=list)    # 断言记录
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class ChainDefinition:
    """链路定义"""
    chain_id: str
    name: str
    description: str = ""
    steps: list[StepDefinition] = field(default_factory=list)          # 有序步骤列表
    global_variables: dict[str, Any] = field(default_factory=dict)    # 全局变量
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ChainResult:
    """链路执行结果"""
    chain_id: str
    chain_name: str
    status: str                                                          # "success" | "failed"
    step_results: list[StepResult] = field(default_factory=list)
    context_snapshot: dict[str, Any] = field(default_factory=dict)     # 执行完成后的上下文快照
    total_duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)              # 统计摘要

# ============================================================
# 模块 5: core/context.py — 上下文管理器
# ============================================================

class ExecutionContext:
    """链路执行上下文，管理变量作用域"""

    SCOPE_GLOBAL = "global"
    SCOPE_CHAIN = "chain"
    SCOPE_STEP = "step"

    def __init__(self, global_variables: dict[str, Any] | None = None) -> None:
        self._global: dict[str, Any] = dict(global_variables or {})
        self._chain: dict[str, Any] = {}
        self._step: dict[str, Any] = {}
        # 用于步骤间数据共享的步骤结果存储
        self._step_results: dict[str, Any] = {}

    def set(self, key: str, value: Any, scope: str = "chain") -> None:
        """设置变量"""
        if scope == self.SCOPE_GLOBAL:
            self._global[key] = value
        elif scope == self.SCOPE_STEP:
            self._step[key] = value
        else:
            self._chain[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取变量，优先级：step > chain > global"""
        if key in self._step:
            return self._step[key]
        if key in self._chain:
            return self._chain[key]
        if key in self._global:
            return self._global[key]
        return default

    def merge(self, data: dict[str, Any], scope: str = "chain") -> None:
        """批量设置变量"""
        for key, value in data.items():
            self.set(key, value, scope)

    def snapshot(self) -> dict[str, Any]:
        """返回当前上下文快照（合并所有作用域）"""
        result: dict[str, Any] = {}
        result.update(self._global)
        result.update(self._chain)
        result.update(self._step)
        return copy.deepcopy(result)

    def resolve_template(self, template: Any) -> Any:
        """委托给 parser 解析模板（避免循环依赖，在 executor 中注入 parser）"""
        return template

    def clear_step_scope(self) -> None:
        """清除步骤级变量"""
        self._step.clear()

    def set_step_result(self, step_id: str, data: dict[str, Any]) -> None:
        """保存步骤结果到上下文（用于 step_id.field 引用）"""
        self._step_results[step_id] = data
        # 同时写入 chain 作用域方便直接引用
        for key, value in data.items():
            self._chain[key] = value

    def get_step_result(self, step_id: str) -> dict[str, Any]:
        """获取某步骤的提取结果"""
        return self._step_results.get(step_id, {})

    def to_dict(self) -> dict[str, Any]:
        """返回完整上下文字典"""
        return {
            "global": copy.deepcopy(self._global),
            "chain": copy.deepcopy(self._chain),
            "step": copy.deepcopy(self._step),
        }

    def __repr__(self) -> str:
        return f"ExecutionContext(global={len(self._global)}, chain={len(self._chain)}, step={len(self._step)})"

# ============================================================
# 模块 6: core/parser.py — 参数解析引擎
# ============================================================

# 模板变量匹配正则：{{variable}} 或 {{$func(args)}}
_TEMPLATE_PATTERN = re.compile(r'\{\{(.+?)\}\}')


class ParameterParser:
    """
    参数解析引擎，支持以下语法：
    - {{variable_name}}           从上下文获取变量
    - {{step_id.field}}           从指定步骤响应获取字段
    - {{$random_int(1,100)}}      内置函数：随机整数
    - {{$random_str(8)}}          内置函数：随机字符串
    - {{$uuid}}                   内置函数：UUID
    - {{$timestamp}}              内置函数：当前时间戳
    - {{$date_now(%Y-%m-%d)}}     内置函数：格式化日期
    - {{$env(ENV_VAR_NAME)}}      内置函数：读取环境变量
    - {{$md5(value)}}             内置函数：MD5 哈希
    - {{$base64(value)}}          内置函数：Base64 编码
    """

    def __init__(self) -> None:
        self._custom_functions: dict[str, Callable] = {}

    def parse(self, template: Any, context: ExecutionContext) -> Any:
        """解析任意类型模板"""
        if isinstance(template, str):
            return self.parse_string(template, context)
        if isinstance(template, dict):
            return self.parse_dict(template, context)
        if isinstance(template, list):
            return self.parse_list(template, context)
        return template

    def parse_string(self, template: str, context: ExecutionContext) -> Any:
        """解析字符串模板，返回替换后的值"""
        if not isinstance(template, str):
            return template

        # 如果整个字符串就是一个模板变量，直接返回原始类型。
        # 注意：使用 [^{}]+ 而不是 .+ 以防止对多变量 URL 模式（如 {{base_url}}/api/orders/{{order_id}}）
        # 进行错误的全匹配（fullmatch 会因回溯而把两个变量之间的内容也纳入单个表达式）。
        full_match = re.fullmatch(r'\{\{([^{}]+?)\}\}', template)
        if full_match:
            return self._resolve_expression(full_match.group(1).strip(), context)

        # 否则做字符串替换
        def replacer(m: re.Match) -> str:
            value = self._resolve_expression(m.group(1).strip(), context)
            return str(value) if value is not None else m.group(0)

        return _TEMPLATE_PATTERN.sub(replacer, template)

    def parse_dict(self, template: dict, context: ExecutionContext) -> dict:
        """递归解析字典"""
        return {key: self.parse(value, context) for key, value in template.items()}

    def parse_list(self, template: list, context: ExecutionContext) -> list:
        """递归解析列表"""
        return [self.parse(item, context) for item in template]

    def register_function(self, name: str, func: Callable) -> None:
        """注册自定义函数"""
        self._custom_functions[name] = func

    def _resolve_expression(self, expr: str, context: ExecutionContext) -> Any:
        """解析单个模板表达式"""
        expr = expr.strip()

        # 内置函数
        if expr.startswith("$"):
            return self._call_builtin(expr[1:], context)

        # step_id.field 形式
        if "." in expr:
            parts = expr.split(".", 1)
            step_id, fld = parts[0], parts[1]
            step_data = context.get_step_result(step_id)
            if step_data and fld in step_data:
                return step_data[fld]
            return context.get(expr)

        # 普通变量
        return context.get(expr)

    def _call_builtin(self, func_expr: str, context: ExecutionContext) -> Any:
        """调用内置函数"""
        m = re.match(r'^(\w+)(?:\((.*)?\))?$', func_expr, re.DOTALL)
        if not m:
            return None

        func_name = m.group(1)
        raw_args = m.group(2) or ""
        args = [a.strip() for a in raw_args.split(",") if a.strip()] if raw_args else []

        if func_name in self._custom_functions:
            return self._custom_functions[func_name](*args)

        return self._dispatch_builtin(func_name, args)

    def _dispatch_builtin(self, name: str, args: list[str]) -> Any:
        """内置函数分发"""
        if name == "uuid":
            return str(uuid.uuid4())
        if name == "timestamp":
            return int(time.time())
        if name == "random_int":
            lo = int(args[0]) if len(args) > 0 else 0
            hi = int(args[1]) if len(args) > 1 else 100
            return random.randint(lo, hi)
        if name == "random_str":
            length = int(args[0]) if args else 8
            return "".join(random.choices(string.ascii_letters + string.digits, k=length))
        if name == "date_now":
            fmt = args[0] if args else "%Y-%m-%d %H:%M:%S"
            return datetime.now().strftime(fmt)
        if name == "env":
            var_name = args[0] if args else ""
            return os.getenv(var_name, "")
        if name == "md5":
            value = args[0] if args else ""
            return hashlib.md5(value.encode()).hexdigest()
        if name == "base64":
            value = args[0] if args else ""
            return base64.b64encode(value.encode()).decode()
        return None

# ============================================================
# 模块 7: core/extractor.py — 响应提取器
# ============================================================

class ResponseExtractor:
    """从接口响应中提取变量存入上下文"""

    def extract(
        self,
        response: requests_lib.Response,
        rules: list[ExtractRule],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """执行所有提取规则，返回提取结果字典，并存入上下文"""
        extracted: dict[str, Any] = {}
        for rule in rules:
            try:
                value = self._extract_one(response, rule)
                if value is None:
                    value = rule.default
                extracted[rule.var_name] = value
                context.set(rule.var_name, value)
            except Exception:
                extracted[rule.var_name] = rule.default
                context.set(rule.var_name, rule.default)
        return extracted

    def _extract_one(self, response: requests_lib.Response, rule: ExtractRule) -> Any:
        """根据提取规则提取单个值"""
        source = rule.source.lower()
        extractor_type = rule.extractor.lower()

        if source == "status_code":
            return response.status_code

        if source == "header":
            return self._header_extract(response, rule.expression)

        if source == "body":
            try:
                body_data = response.json()
            except Exception:
                body_data = response.text

            if extractor_type == "jsonpath":
                return self._jsonpath_extract(body_data, rule.expression)
            if extractor_type == "jmespath":
                return self._jmespath_extract(body_data, rule.expression)
            if extractor_type == "regex":
                return self._regex_extract(response.text, rule.expression)
            if extractor_type == "key":
                return self._key_extract(body_data, rule.expression)

        return None

    def _jsonpath_extract(self, data: Any, expression: str) -> Any:
        """JSONPath 提取"""
        try:
            from jsonpath_ng.ext import parse as jsonpath_parse
            jsonpath_expr = jsonpath_parse(expression)
            matches = jsonpath_expr.find(data)
            if not matches:
                return None
            return matches[0].value if len(matches) == 1 else [m.value for m in matches]
        except Exception as e:
            raise ValueError(f"JSONPath 提取失败 [{expression}]: {e}") from e

    def _jmespath_extract(self, data: Any, expression: str) -> Any:
        """JMESPath 提取"""
        try:
            return jmespath.search(expression, data)
        except Exception as e:
            raise ValueError(f"JMESPath 提取失败 [{expression}]: {e}") from e

    def _regex_extract(self, text: str, pattern: str) -> Any:
        """正则提取"""
        try:
            m = re.search(pattern, text)
            if not m:
                return None
            return m.group(1) if m.lastindex else m.group(0)
        except Exception as e:
            raise ValueError(f"正则提取失败 [{pattern}]: {e}") from e

    def _header_extract(self, response: requests_lib.Response, key: str) -> Any:
        """Header 提取（大小写不敏感）"""
        return response.headers.get(key) or response.headers.get(key.lower())

    def _key_extract(self, data: Any, key: str) -> Any:
        """简单 key 路径提取，支持 a.b.c 形式"""
        parts = key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

# ============================================================
# 模块 8: core/assertion.py — 断言引擎
# ============================================================

class AssertionEngine:
    """断言引擎，支持丰富的断言操作符"""

    OPERATORS: dict[str, Any] = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: float(a) > float(b),
        "gte": lambda a, b: float(a) >= float(b),
        "lt": lambda a, b: float(a) < float(b),
        "lte": lambda a, b: float(a) <= float(b),
        "contains": lambda a, b: b in a,
        "not_contains": lambda a, b: b not in a,
        "startswith": lambda a, b: str(a).startswith(str(b)),
        "endswith": lambda a, b: str(a).endswith(str(b)),
        "exists": lambda a, _: a is not None,
        "is_none": lambda a, _: a is None,
        "not_none": lambda a, _: a is not None,
        "regex": lambda a, b: bool(re.search(str(b), str(a))),
        "in": lambda a, b: a in b,
        "not_in": lambda a, b: a not in b,
        "length_eq": lambda a, b: len(a) == int(b),
        "length_gt": lambda a, b: len(a) > int(b),
        "type_is": lambda a, b: type(a).__name__ == str(b),
    }

    def run_assertions(
        self,
        response: requests_lib.Response,
        rules: list[AssertRule],
        context: ExecutionContext,
    ) -> list[AssertionRecord]:
        """执行所有断言规则"""
        records: list[AssertionRecord] = []
        for rule in rules:
            record = self.run_single(response, rule, context)
            records.append(record)
        return records

    def run_single(
        self,
        response: requests_lib.Response,
        rule: AssertRule,
        context: ExecutionContext,
    ) -> AssertionRecord:
        """执行单条断言"""
        try:
            actual = self._get_actual(response, rule, context)
            expected = self._resolve_expected(rule.expected, context)
            op_func = self.OPERATORS.get(rule.operator)
            if op_func is None:
                raise ValueError(f"不支持的断言操作符: {rule.operator}")
            passed = bool(op_func(actual, expected))
            message = rule.message if not passed else ""
            return AssertionRecord(
                name=rule.name,
                passed=passed,
                expected=expected,
                actual=actual,
                operator=rule.operator,
                message=message,
            )
        except Exception as e:
            return AssertionRecord(
                name=rule.name,
                passed=False,
                expected=rule.expected,
                actual=None,
                operator=rule.operator,
                message=rule.message or str(e),
                error=str(e),
            )

    def _get_actual(
        self,
        response: requests_lib.Response,
        rule: AssertRule,
        context: ExecutionContext,
    ) -> Any:
        """从响应或上下文中获取实际值"""
        source = rule.source.lower()

        if source == "status_code":
            return response.status_code

        if source == "header":
            return response.headers.get(rule.expression) or response.headers.get(rule.expression.lower())

        if source == "context":
            return context.get(rule.expression)

        if source == "body":
            try:
                body = response.json()
            except Exception:
                body = response.text
            return self._extract_value(body, rule.expression)

        return None

    def _extract_value(self, data: Any, expression: str) -> Any:
        """从数据中提取值（支持 JSONPath 和简单 key）"""
        if expression.startswith("$.") or expression == "$":
            try:
                from jsonpath_ng.ext import parse as jsonpath_parse
                matches = jsonpath_parse(expression).find(data)
                if not matches:
                    return None
                return matches[0].value if len(matches) == 1 else [m.value for m in matches]
            except Exception:
                return None
        parts = expression.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _resolve_expected(self, expected: Any, context: ExecutionContext) -> Any:
        """解析期望值（支持模板变量）"""
        if isinstance(expected, str) and "{{" in expected:
            return context.get(expected.strip("{{").strip("}}"))
        return expected

# ============================================================
# 模块 9: core/cleaner.py — 数据清理器
# ============================================================

@dataclass
class CleanupResult:
    """清理任务执行结果"""
    task_name: str
    success: bool
    error: str | None = None


@dataclass
class _CleanupTask:
    name: str
    func: Callable
    args: dict[str, Any] = field(default_factory=dict)


class DataCleaner:
    """
    执行后数据清理器，支持注册清理任务
    - 支持按顺序逆向清理（后创建的先删除）
    - 支持条件清理（仅测试环境）
    - 与链路执行上下文集成
    """

    def __init__(self) -> None:
        self._tasks: list[_CleanupTask] = []

    def register(
        self,
        task_name: str,
        cleanup_func: Callable,
        args: dict[str, Any] | None = None,
    ) -> None:
        """注册清理任务"""
        self._tasks.append(_CleanupTask(name=task_name, func=cleanup_func, args=args or {}))

    def register_api_cleanup(self, step_id: str, api_id: str, params: dict[str, Any]) -> None:
        """注册接口级清理（用于调用删除类接口）"""
        def _api_cleanup(**kw: Any) -> None:
            pass

        self._tasks.append(_CleanupTask(name=f"api_cleanup:{step_id}:{api_id}", func=_api_cleanup, args=params))

    def run_all(self, context: ExecutionContext) -> list[CleanupResult]:
        """逆序执行所有清理任务"""
        results: list[CleanupResult] = []
        for task in reversed(self._tasks):
            result = self._run_task(task, context)
            results.append(result)
        return results

    def run_selective(self, task_names: list[str]) -> list[CleanupResult]:
        """按名称执行指定清理任务"""
        results: list[CleanupResult] = []
        for task in reversed(self._tasks):
            if task.name in task_names:
                result = self._run_task(task, None)
                results.append(result)
        return results

    def clear(self) -> None:
        """清空所有清理任务"""
        self._tasks.clear()

    def _run_task(self, task: _CleanupTask, context: ExecutionContext | None) -> CleanupResult:
        """执行单个清理任务"""
        try:
            task.func(**task.args)
            return CleanupResult(task_name=task.name, success=True)
        except Exception as e:
            return CleanupResult(task_name=task.name, success=False, error=str(e))

# ============================================================
# 模块 10: core/registry.py — 接口注册中心
# ============================================================

class APIRegistry:
    """接口注册中心，支持模块化管理"""

    def __init__(self) -> None:
        self._apis: dict[str, APIDefinition] = {}

    def register(self, api: APIDefinition) -> None:
        """注册单个接口"""
        self._apis[api.api_id] = api

    def register_batch(self, apis: list[APIDefinition]) -> None:
        """批量注册接口"""
        for api in apis:
            self.register(api)

    def get(self, api_id: str) -> APIDefinition:
        """获取接口定义，不存在则抛出异常"""
        if api_id not in self._apis:
            raise KeyError(f"接口 '{api_id}' 未注册，已注册接口: {list(self._apis.keys())}")
        return self._apis[api_id]

    def list_all(self) -> list[APIDefinition]:
        """列出所有接口"""
        return list(self._apis.values())

    def list_by_module(self, module: str) -> list[APIDefinition]:
        """按模块列出接口"""
        return [api for api in self._apis.values() if api.module == module]

    def list_by_tag(self, tag: str) -> list[APIDefinition]:
        """按标签列出接口"""
        return [api for api in self._apis.values() if tag in api.tags]

    def search(self, keyword: str) -> list[APIDefinition]:
        """关键字搜索接口（名称、描述、api_id、模块）"""
        keyword_lower = keyword.lower()
        results = []
        for api in self._apis.values():
            if (keyword_lower in api.api_id.lower()
                    or keyword_lower in api.name.lower()
                    or keyword_lower in api.description.lower()
                    or keyword_lower in api.module.lower()):
                results.append(api)
        return results

    def show_tree(self) -> str:
        """按模块展示接口树形结构"""
        modules: dict[str, list[APIDefinition]] = {}
        for api in self._apis.values():
            module = api.module or "未分类"
            modules.setdefault(module, []).append(api)

        lines = ["接口注册中心\n" + "=" * 40]
        for module, apis in sorted(modules.items()):
            lines.append(f"📦 {module}")
            for i, api in enumerate(apis):
                prefix = "└──" if i == len(apis) - 1 else "├──"
                lines.append(f"   {prefix} [{api.method:6s}] {api.api_id}: {api.name}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._apis)

    def __contains__(self, api_id: str) -> bool:
        return api_id in self._apis

# ============================================================
# 模块 11: core/tracer.py — 可观测性与追踪
# ============================================================

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

    def on_chain_start(self, chain: ChainDefinition, context: ExecutionContext) -> None:
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

    def on_step_start(self, step: StepDefinition, request_data: dict) -> None:
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
            safe_body = self._mask_sensitive(body)
            console.print(f"  [cyan]➤[/cyan] Body: {json.dumps(safe_body, ensure_ascii=False, default=str)}")

        logger.info(f"步骤开始: {step.step_id} - {step.name} | {method} {url}")

    def on_step_end(self, step_result: StepResult) -> None:
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

        if step_result.extractions:
            parts = []
            for k, v in step_result.extractions.items():
                val_str = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
                parts.append(f"{k}={val_str}")
            console.print(f"  [magenta]📤 提取变量:[/magenta] {', '.join(parts)}")

        if step_result.assertions:
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

        if step_result.error:
            console.print(f"  [red]  ⚠️  错误: {step_result.error}[/red]")

        logger.info(
            f"步骤结束: {step_result.step_id} | 状态={status} | "
            f"耗时={duration:.0f}ms | 断言={sum(1 for a in step_result.assertions if a.passed)}/{len(step_result.assertions)}"
        )

    def on_chain_end(self, result: ChainResult) -> None:
        """链路结束回调"""
        self.print_summary(result)
        logger.info(
            f"链路结束: {result.chain_id} | 状态={result.status} | "
            f"耗时={result.total_duration_ms:.0f}ms"
        )

    def print_summary(self, result: ChainResult) -> None:
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

    def generate_report(self, result: ChainResult, output_path: str | None = None) -> str:
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

    def _build_html_report(self, result: ChainResult) -> str:
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

# ============================================================
# 模块 12: core/executor.py — 链式执行器（核心）
# ============================================================

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
        registry: APIRegistry,
        tracer: ExecutionTracer,
        parser: ParameterParser,
        extractor: ResponseExtractor,
        assertion_engine: AssertionEngine,
    ) -> None:
        self.registry = registry
        self.tracer = tracer
        self.parser = parser
        self.extractor = extractor
        self.assertion_engine = assertion_engine
        self._session = requests_lib.Session()

    def execute(
        self,
        chain: ChainDefinition,
        runtime_variables: dict[str, Any] | None = None,
    ) -> ChainResult:
        """执行完整链路"""
        started_at = datetime.now().isoformat()
        start_time = time.time()

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

            if step_result.extractions:
                context.set_step_result(step.step_id, step_result.extractions)

            self.tracer.on_step_end(step_result)

            if step_result.status == "failed":
                on_failure = getattr(step, "on_failure", "stop")
                if on_failure == "stop":
                    skip_remaining = True
                elif on_failure == "skip_next":
                    skip_remaining = True
                # "continue" 策略：继续执行

        total_duration_ms = (time.time() - start_time) * 1000
        finished_at = datetime.now().isoformat()

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

        for script in (step.pre_scripts or []):
            try:
                self._run_script(script, context)
            except Exception:
                pass

        try:
            api = self.registry.get(step.api_id)
            request_data = self._build_request(api, step, context)
            request_record = RequestRecord(
                method=request_data["method"],
                url=request_data["url"],
                headers=request_data.get("headers", {}),
                params=request_data.get("params", {}),
                body=request_data.get("json") or request_data.get("data"),
            )

            self.tracer.on_step_start(step, request_data)

            response = self._send_request(request_data)
            duration_ms = (time.time() - start_time) * 1000

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

            extractions = self.extractor.extract(response, step.extracts or [], context)
            assertion_records = self.assertion_engine.run_assertions(
                response, step.assertions or [], context
            )

            for script in (step.post_scripts or []):
                try:
                    self._run_script(script, context)
                except Exception:
                    pass

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
        merged_headers = dict(api.headers or {})
        merged_params = dict(api.params or {})
        merged_body = copy.deepcopy(api.body or {})

        overrides = step.param_overrides or {}
        merged_headers.update(overrides.get("headers", {}))
        merged_params.update(overrides.get("params", {}))

        body_overrides = overrides.get("body", {})
        if body_overrides:
            merged_body.update(body_overrides)

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
        chain: ChainDefinition,
        runtime_variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """干跑模式：不发送真实请求，只解析模板参数"""
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

# ============================================================
# 模块 13: storage/sqlite_store.py — SQLite 持久化存储
# ============================================================

class ChainStore:
    """
    链路模板持久化（SQLite）
    只保存链路结构和参数模板，不保存本次执行的具体参数值
    """

    def __init__(self, db_path: str = "chain_store.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # WAL（Write-Ahead Logging）模式：提升并发读取性能，避免读写互相阻塞，
        # 适合多线程/多进程同时读取链路模板的使用场景。
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    tags TEXT,
                    global_variables TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    api_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    param_overrides TEXT,
                    extracts TEXT,
                    assertions TEXT,
                    depends_on TEXT,
                    on_failure TEXT DEFAULT 'stop',
                    pre_scripts TEXT,
                    post_scripts TEXT,
                    FOREIGN KEY (chain_id) REFERENCES chains(chain_id)
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms REAL,
                    result_summary TEXT
                );
            """)

    def save_chain(self, chain: ChainDefinition) -> None:
        """保存链路（存在则更新）"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM chains WHERE chain_id = ?", (chain.chain_id,)
            ).fetchone()
            if existing:
                self.update_chain(chain)
                return

            conn.execute(
                """INSERT INTO chains (chain_id, name, description, tags, global_variables, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain.chain_id,
                    chain.name,
                    chain.description,
                    json.dumps(chain.tags, ensure_ascii=False),
                    json.dumps(chain.global_variables, ensure_ascii=False),
                    chain.created_at or now,
                    chain.updated_at or now,
                ),
            )
            self._save_steps(conn, chain)

    def load_chain(self, chain_id: str) -> ChainDefinition:
        """加载链路定义"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM chains WHERE chain_id = ?", (chain_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"链路 '{chain_id}' 不存在")

            steps = self._load_steps(conn, chain_id)
            return ChainDefinition(
                chain_id=row["chain_id"],
                name=row["name"],
                description=row["description"] or "",
                steps=steps,
                global_variables=json.loads(row["global_variables"] or "{}"),
                tags=json.loads(row["tags"] or "[]"),
                created_at=row["created_at"] or "",
                updated_at=row["updated_at"] or "",
            )

    def list_chains(self) -> list[dict[str, Any]]:
        """列出所有链路摘要"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT chain_id, name, description, tags, created_at, updated_at FROM chains"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_chain(self, chain_id: str) -> None:
        """删除链路"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM steps WHERE chain_id = ?", (chain_id,))
            conn.execute("DELETE FROM chains WHERE chain_id = ?", (chain_id,))

    def update_chain(self, chain: ChainDefinition) -> None:
        """更新链路"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE chains SET name=?, description=?, tags=?, global_variables=?, updated_at=?
                   WHERE chain_id=?""",
                (
                    chain.name,
                    chain.description,
                    json.dumps(chain.tags, ensure_ascii=False),
                    json.dumps(chain.global_variables, ensure_ascii=False),
                    now,
                    chain.chain_id,
                ),
            )
            conn.execute("DELETE FROM steps WHERE chain_id = ?", (chain.chain_id,))
            self._save_steps(conn, chain)

    def save_execution_summary(self, result: ChainResult) -> None:
        """保存执行摘要"""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO executions (chain_id, status, started_at, finished_at, duration_ms, result_summary)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    result.chain_id,
                    result.status,
                    result.started_at,
                    result.finished_at,
                    result.total_duration_ms,
                    json.dumps(result.summary, ensure_ascii=False),
                ),
            )

    def get_execution_history(self, chain_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取执行历史"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM executions WHERE chain_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (chain_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def export_chain_yaml(self, chain_id: str, file_path: str) -> None:
        """导出链路为 YAML"""
        chain = self.load_chain(chain_id)
        data = self._chain_to_dict(chain)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def import_chain_yaml(self, file_path: str) -> ChainDefinition:
        """从 YAML 导入链路"""
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        chain = self._dict_to_chain(data)
        self.save_chain(chain)
        return chain

    def _save_steps(self, conn: sqlite3.Connection, chain: ChainDefinition) -> None:
        for order, step in enumerate(chain.steps):
            conn.execute(
                """INSERT INTO steps
                   (chain_id, step_id, step_order, api_id, name, param_overrides,
                    extracts, assertions, depends_on, on_failure, pre_scripts, post_scripts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain.chain_id,
                    step.step_id,
                    order,
                    step.api_id,
                    step.name,
                    json.dumps(step.param_overrides or {}, ensure_ascii=False),
                    json.dumps([self._extract_rule_to_dict(r) for r in (step.extracts or [])], ensure_ascii=False),
                    json.dumps([self._assert_rule_to_dict(r) for r in (step.assertions or [])], ensure_ascii=False),
                    json.dumps(step.depends_on or [], ensure_ascii=False),
                    step.on_failure or "stop",
                    json.dumps(step.pre_scripts or [], ensure_ascii=False),
                    json.dumps(step.post_scripts or [], ensure_ascii=False),
                ),
            )

    def _load_steps(self, conn: sqlite3.Connection, chain_id: str) -> list[StepDefinition]:
        rows = conn.execute(
            "SELECT * FROM steps WHERE chain_id = ? ORDER BY step_order", (chain_id,)
        ).fetchall()
        steps = []
        for row in rows:
            extracts_data = json.loads(row["extracts"] or "[]")
            assertions_data = json.loads(row["assertions"] or "[]")
            steps.append(
                StepDefinition(
                    step_id=row["step_id"],
                    api_id=row["api_id"],
                    name=row["name"],
                    param_overrides=json.loads(row["param_overrides"] or "{}"),
                    extracts=[self._dict_to_extract_rule(d) for d in extracts_data],
                    assertions=[self._dict_to_assert_rule(d) for d in assertions_data],
                    depends_on=json.loads(row["depends_on"] or "[]"),
                    on_failure=row["on_failure"] or "stop",
                    pre_scripts=json.loads(row["pre_scripts"] or "[]"),
                    post_scripts=json.loads(row["post_scripts"] or "[]"),
                )
            )
        return steps

    @staticmethod
    def _extract_rule_to_dict(rule: ExtractRule) -> dict:
        return {
            "var_name": rule.var_name,
            "source": rule.source,
            "extractor": rule.extractor,
            "expression": rule.expression,
            "default": rule.default,
        }

    @staticmethod
    def _dict_to_extract_rule(d: dict) -> ExtractRule:
        return ExtractRule(
            var_name=d["var_name"],
            source=d["source"],
            extractor=d["extractor"],
            expression=d["expression"],
            default=d.get("default"),
        )

    @staticmethod
    def _assert_rule_to_dict(rule: AssertRule) -> dict:
        return {
            "name": rule.name,
            "source": rule.source,
            "expression": rule.expression,
            "operator": rule.operator,
            "expected": rule.expected,
            "message": rule.message,
        }

    @staticmethod
    def _dict_to_assert_rule(d: dict) -> AssertRule:
        return AssertRule(
            name=d["name"],
            source=d["source"],
            expression=d["expression"],
            operator=d["operator"],
            expected=d.get("expected"),
            message=d.get("message", ""),
        )

    def _chain_to_dict(self, chain: ChainDefinition) -> dict:
        return {
            "chain_id": chain.chain_id,
            "name": chain.name,
            "description": chain.description,
            "global_variables": chain.global_variables,
            "tags": chain.tags,
            "created_at": chain.created_at,
            "updated_at": chain.updated_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "api_id": s.api_id,
                    "name": s.name,
                    "param_overrides": s.param_overrides,
                    "extracts": [self._extract_rule_to_dict(r) for r in s.extracts],
                    "assertions": [self._assert_rule_to_dict(r) for r in s.assertions],
                    "depends_on": s.depends_on,
                    "on_failure": s.on_failure,
                    "pre_scripts": s.pre_scripts,
                    "post_scripts": s.post_scripts,
                }
                for s in chain.steps
            ],
        }

    def _dict_to_chain(self, data: dict) -> ChainDefinition:
        steps = []
        for s in data.get("steps", []):
            steps.append(
                StepDefinition(
                    step_id=s["step_id"],
                    api_id=s["api_id"],
                    name=s["name"],
                    param_overrides=s.get("param_overrides", {}),
                    extracts=[self._dict_to_extract_rule(r) for r in s.get("extracts", [])],
                    assertions=[self._dict_to_assert_rule(r) for r in s.get("assertions", [])],
                    depends_on=s.get("depends_on", []),
                    on_failure=s.get("on_failure", "stop"),
                    pre_scripts=s.get("pre_scripts", []),
                    post_scripts=s.get("post_scripts", []),
                )
            )
        return ChainDefinition(
            chain_id=data["chain_id"],
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            global_variables=data.get("global_variables", {}),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

# ============================================================
# 模块 14: apis/ecommerce_apis.py — 电商接口定义 & Mock 数据
# ============================================================

def get_ecommerce_apis() -> list[APIDefinition]:
    """返回所有电商示例接口定义"""
    return [
        # A: 用户登录
        APIDefinition(
            api_id="user_login",
            name="用户登录",
            method="POST",
            url="{{base_url}}/api/auth/login",
            headers={"Content-Type": "application/json"},
            params={},
            body={"username": "{{username}}", "password": "{{password}}"},
            timeout=30,
            description="用户登录接口，返回 token 和 user_id",
            module="用户模块",
            tags=["auth", "user"],
        ),
        # B: 获取用户信息
        APIDefinition(
            api_id="get_user_profile",
            name="获取用户信息",
            method="GET",
            url="{{base_url}}/api/users/{{user_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="根据 user_id 获取用户详细信息",
            module="用户模块",
            tags=["user", "profile"],
        ),
        # C: 搜索商品
        APIDefinition(
            api_id="search_product",
            name="搜索商品",
            method="GET",
            url="{{base_url}}/api/products/search",
            headers={"Authorization": "Bearer {{token}}"},
            params={"keyword": "{{keyword}}", "page": "{{page}}", "size": "{{size}}"},
            body={},
            timeout=30,
            description="根据关键词搜索商品，返回商品列表",
            module="商品模块",
            tags=["product", "search"],
        ),
        # D: 获取商品详情
        APIDefinition(
            api_id="get_product_detail",
            name="商品详情",
            method="GET",
            url="{{base_url}}/api/products/{{product_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="根据 product_id 获取商品详情，返回 stock 和 sku_id",
            module="商品模块",
            tags=["product", "detail"],
        ),
        # E: 创建订单
        APIDefinition(
            api_id="create_order",
            name="创建订单",
            method="POST",
            url="{{base_url}}/api/orders",
            headers={"Authorization": "Bearer {{token}}", "Content-Type": "application/json"},
            params={},
            body={
                "user_id": "{{user_id}}",
                "product_id": "{{product_id}}",
                "sku_id": "{{sku_id}}",
                "quantity": "{{quantity}}",
                "address": "{{address}}",
            },
            timeout=30,
            description="创建订单，依赖 user_id、product_id、sku_id 从上下文获取",
            module="订单模块",
            tags=["order", "create"],
        ),
        # F: 支付订单
        APIDefinition(
            api_id="pay_order",
            name="支付订单",
            method="POST",
            url="{{base_url}}/api/orders/{{order_id}}/pay",
            headers={"Authorization": "Bearer {{token}}", "Content-Type": "application/json"},
            params={},
            body={"payment_method": "{{payment_method}}", "amount": "{{amount}}"},
            timeout=30,
            description="支付订单，依赖 order_id 从上下文获取",
            module="支付模块",
            tags=["order", "payment"],
        ),
        # G: 查询订单
        APIDefinition(
            api_id="query_order",
            name="查询订单",
            method="GET",
            url="{{base_url}}/api/orders/{{order_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="查询订单详情，依赖 order_id 从上下文获取",
            module="订单模块",
            tags=["order", "query"],
        ),
    ]


def create_registry() -> APIRegistry:
    """创建并注册所有电商接口，返回注册中心"""
    registry = APIRegistry()
    registry.register_batch(get_ecommerce_apis())
    return registry


MOCK_RESPONSES: dict[str, dict] = {
    "user_login": {
        "code": 0,
        "message": "登录成功",
        "data": {
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.mock_token",
            "user_id": "10086",
            "username": "test_user",
        },
    },
    "get_user_profile": {
        "code": 0,
        "message": "success",
        "data": {"user_id": "10086", "nickname": "测试用户", "vip_level": 3, "email": "test@example.com"},
    },
    "search_product": {
        "code": 0,
        "message": "success",
        "data": {
            "total": 100,
            "list": [{"product_id": "P20240001", "product_name": "iPhone 15 Pro", "price": 8999.00,
                       "cover": "https://example.com/iphone15.jpg"}],
        },
    },
    "get_product_detail": {
        "code": 0,
        "message": "success",
        "data": {
            "product_id": "P20240001",
            "product_name": "iPhone 15 Pro",
            "price": 8999.00,
            "stock": 500,
            "sku_id": "SKU_IPHONE15_BLACK_256G",
            "specs": {"color": "黑色", "storage": "256G"},
        },
    },
    "create_order": {
        "code": 0,
        "message": "订单创建成功",
        "data": {"order_id": "ORD20240001", "order_no": "NO20240001001",
                  "status": "pending_payment", "total_amount": 8999.00},
    },
    "pay_order": {
        "code": 0,
        "message": "支付成功",
        "data": {"order_id": "ORD20240001", "pay_status": "paid",
                  "transaction_id": "TXN20240001", "paid_at": "2024-01-01 10:00:00"},
    },
    "query_order": {
        "code": 0,
        "message": "success",
        "data": {
            "order_id": "ORD20240001",
            "order_no": "NO20240001001",
            "order_status": "paid",
            "items": [{"product_id": "P20240001", "product_name": "iPhone 15 Pro",
                        "quantity": 1, "price": 8999.00}],
        },
    },
}

# ============================================================
# 模块 15: main.py — CLI 入口 & 演示
# ============================================================

def build_chain1() -> ChainDefinition:
    """链路1：商品下单完整流程 (A → C → E → G)"""
    return ChainDefinition(
        chain_id="ecommerce_order_chain",
        name="商品下单完整流程",
        description="用户登录 → 搜索商品 → 创建订单 → 查询订单",
        global_variables={
            "base_url": config.BASE_URL,
            "username": "test_user",
            "password": "Test@123",
            "keyword": "iPhone",
            "page": 1,
            "size": 10,
            "quantity": 1,
            "address": "北京市朝阳区xx路xx号",
        },
        tags=["ecommerce", "order", "smoke"],
        steps=[
            StepDefinition(
                step_id="step_login",
                api_id="user_login",
                name="用户登录",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="token", source="body", extractor="jsonpath",
                                expression="$.data.token", default=None),
                    ExtractRule(var_name="user_id", source="body", extractor="jsonpath",
                                expression="$.data.user_id", default=None),
                ],
                assertions=[
                    AssertRule(name="状态码为200", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="登录接口状态码应为200"),
                    AssertRule(name="业务码为0", source="body", expression="$.code",
                               operator="eq", expected=0, message="登录业务码应为0"),
                    AssertRule(name="token不为空", source="body", expression="$.data.token",
                               operator="exists", expected=None, message="登录成功后应返回token"),
                ],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_search",
                api_id="search_product",
                name="搜索商品",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="product_id", source="body", extractor="jsonpath",
                                expression="$.data.list[0].product_id", default=None),
                    ExtractRule(var_name="product_name", source="body", extractor="jsonpath",
                                expression="$.data.list[0].product_name", default=None),
                    ExtractRule(var_name="price", source="body", extractor="jsonpath",
                                expression="$.data.list[0].price", default=None),
                ],
                assertions=[
                    AssertRule(name="状态码为200", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="搜索接口状态码应为200"),
                    AssertRule(name="商品列表不为空", source="body", expression="$.data.list",
                               operator="exists", expected=None, message="搜索结果不应为空"),
                ],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_create_order",
                api_id="create_order",
                name="创建订单",
                param_overrides={"body": {"sku_id": "SKU_DEFAULT"}},
                extracts=[
                    ExtractRule(var_name="order_id", source="body", extractor="jsonpath",
                                expression="$.data.order_id", default=None),
                    ExtractRule(var_name="order_no", source="body", extractor="jsonpath",
                                expression="$.data.order_no", default=None),
                ],
                assertions=[
                    AssertRule(name="状态码为200", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="创建订单接口状态码应为200"),
                    AssertRule(name="订单ID不为空", source="body", expression="$.data.order_id",
                               operator="exists", expected=None, message="创建订单后应返回order_id"),
                    AssertRule(name="业务码为0", source="body", expression="$.code",
                               operator="eq", expected=0, message="创建订单业务码应为0"),
                ],
                depends_on=["step_login", "step_search"],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_query_order",
                api_id="query_order",
                name="查询订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="order_status", source="body", extractor="jsonpath",
                                expression="$.data.order_status", default=None),
                ],
                assertions=[
                    AssertRule(name="状态码为200", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="查询订单接口状态码应为200"),
                    AssertRule(name="订单状态为待支付", source="body", expression="$.data.order_status",
                               operator="in", expected=["pending_payment", "paid"],
                               message="订单应处于待支付或已支付状态"),
                ],
                depends_on=["step_create_order"],
                on_failure="continue",
            ),
        ],
    )


def build_chain2() -> ChainDefinition:
    """链路2：下单并支付流程 (A → C → D → E → F → G)"""
    return ChainDefinition(
        chain_id="ecommerce_pay_chain",
        name="下单并支付完整流程",
        description="用户登录 → 搜索商品 → 获取商品详情 → 创建订单 → 支付订单 → 查询订单",
        global_variables={
            "base_url": config.BASE_URL,
            "username": "test_user",
            "password": "Test@123",
            "keyword": "iPhone",
            "page": 1,
            "size": 10,
            "quantity": 1,
            "address": "上海市浦东新区xx路xx号",
            "payment_method": "alipay",
            "amount": 8999.00,
        },
        tags=["ecommerce", "order", "payment", "e2e"],
        steps=[
            StepDefinition(
                step_id="step_login",
                api_id="user_login",
                name="用户登录",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="token", source="body", extractor="jsonpath",
                                expression="$.data.token", default=None),
                    ExtractRule(var_name="user_id", source="body", extractor="jsonpath",
                                expression="$.data.user_id", default=None),
                ],
                assertions=[
                    AssertRule(name="登录成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="登录接口应返回200"),
                    AssertRule(name="token存在", source="body", expression="$.data.token",
                               operator="exists", expected=None, message="应返回token"),
                ],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_search",
                api_id="search_product",
                name="搜索商品",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="product_id", source="body", extractor="jsonpath",
                                expression="$.data.list[0].product_id", default=None),
                ],
                assertions=[
                    AssertRule(name="搜索成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="搜索接口应返回200"),
                ],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_product_detail",
                api_id="get_product_detail",
                name="获取商品详情",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="sku_id", source="body", extractor="jsonpath",
                                expression="$.data.sku_id", default=None),
                    ExtractRule(var_name="stock", source="body", extractor="jsonpath",
                                expression="$.data.stock", default=None),
                ],
                assertions=[
                    AssertRule(name="商品详情获取成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="商品详情接口应返回200"),
                    AssertRule(name="库存充足", source="body", expression="$.data.stock",
                               operator="gt", expected=0, message="商品库存应大于0"),
                ],
                depends_on=["step_search"],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_create_order",
                api_id="create_order",
                name="创建订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="order_id", source="body", extractor="jsonpath",
                                expression="$.data.order_id", default=None),
                    ExtractRule(var_name="order_no", source="body", extractor="jsonpath",
                                expression="$.data.order_no", default=None),
                ],
                assertions=[
                    AssertRule(name="创建订单成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="创建订单接口应返回200"),
                    AssertRule(name="order_id存在", source="body", expression="$.data.order_id",
                               operator="exists", expected=None, message="应返回order_id"),
                ],
                depends_on=["step_login", "step_search", "step_product_detail"],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_pay_order",
                api_id="pay_order",
                name="支付订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="pay_status", source="body", extractor="jsonpath",
                                expression="$.data.pay_status", default=None),
                    ExtractRule(var_name="transaction_id", source="body", extractor="jsonpath",
                                expression="$.data.transaction_id", default=None),
                ],
                assertions=[
                    AssertRule(name="支付成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="支付接口应返回200"),
                    AssertRule(name="支付状态为paid", source="body", expression="$.data.pay_status",
                               operator="eq", expected="paid", message="支付状态应为paid"),
                ],
                depends_on=["step_create_order"],
                on_failure="stop",
            ),
            StepDefinition(
                step_id="step_query_order",
                api_id="query_order",
                name="查询订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="order_status", source="body", extractor="jsonpath",
                                expression="$.data.order_status", default=None),
                ],
                assertions=[
                    AssertRule(name="查询成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="查询订单接口应返回200"),
                    AssertRule(name="订单状态为已支付", source="body", expression="$.data.order_status",
                               operator="eq", expected="paid", message="订单状态应为paid"),
                ],
                depends_on=["step_pay_order"],
                on_failure="continue",
            ),
        ],
    )


def build_executor() -> ChainExecutor:
    """构建链式执行器"""
    registry = create_registry()
    tracer = ExecutionTracer()
    parser = ParameterParser()
    extractor = ResponseExtractor()
    assertion_engine = AssertionEngine()
    return ChainExecutor(
        registry=registry,
        tracer=tracer,
        parser=parser,
        extractor=extractor,
        assertion_engine=assertion_engine,
    )


def setup_mock(mock_adapter: requests_mock_lib.Mocker) -> None:
    """配置 mock 响应"""
    base = config.BASE_URL

    mock_adapter.post(f"{base}/api/auth/login", json=MOCK_RESPONSES["user_login"])
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_user_profile"],
                     additional_matcher=lambda req: "/api/users/" in req.url)
    mock_adapter.get(f"{base}/api/products/search", json=MOCK_RESPONSES["search_product"])
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_product_detail"],
                     additional_matcher=lambda req: "/api/products/" in req.url and "search" not in req.url)
    mock_adapter.post(f"{base}/api/orders", json=MOCK_RESPONSES["create_order"])
    mock_adapter.post(requests_mock_lib.ANY, json=MOCK_RESPONSES["pay_order"],
                      additional_matcher=lambda req: "/pay" in req.url)
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["query_order"],
                     additional_matcher=lambda req: "/api/orders/" in req.url)


def main() -> None:
    console.print(Panel.fit(
        "[bold cyan]🔗 接口智能编排与链式执行引擎[/bold cyan]\n"
        "[dim]API Chain Execution Engine v1.0.0 — 合并单文件版[/dim]",
        box=box.DOUBLE,
        style="blue",
    ))

    store = ChainStore(config.DB_PATH)
    executor = build_executor()

    with requests_mock_lib.Mocker() as mock:
        setup_mock(mock)

        # ─────────────── 链路1 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 演示链路1: 商品下单完整流程 (A → C → E → G)[/bold yellow]")
        console.print("=" * 60)

        chain1 = build_chain1()
        result1 = executor.execute(chain1)

        store.save_chain(chain1)
        store.save_execution_summary(result1)
        console.print(f"[green]✅ 链路模板已保存到 SQLite: {config.DB_PATH}[/green]")
        executor.tracer.generate_report(result1)

        # ─────────────── 链路2 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 演示链路2: 下单并支付完整流程 (A → C → D → E → F → G)[/bold yellow]")
        console.print("=" * 60)

        chain2 = build_chain2()
        result2 = executor.execute(chain2)

        store.save_chain(chain2)
        store.save_execution_summary(result2)
        console.print(f"[green]✅ 链路模板已保存到 SQLite: {config.DB_PATH}[/green]")
        executor.tracer.generate_report(result2)

        # ─────────────── 验证加载 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 验证: 从 SQLite 重新加载链路并执行[/bold yellow]")
        console.print("=" * 60)

        loaded_chain = store.load_chain("ecommerce_order_chain")
        console.print(f"[green]✅ 成功加载链路: {loaded_chain.name}[/green]")

        result_loaded = executor.execute(loaded_chain)
        console.print(
            f"重新执行结果: [{'green' if result_loaded.status == 'success' else 'red'}]"
            f"{'✅ SUCCESS' if result_loaded.status == 'success' else '❌ FAILED'}[/]"
        )

    console.print("\n[bold]📋 已保存链路列表:[/bold]")
    chains = store.list_chains()
    for c in chains:
        console.print(f"  • {c['chain_id']}: {c['name']}")

    console.print("\n[bold green]🎉 演示完成！[/bold green]")


if __name__ == "__main__":
    main()
