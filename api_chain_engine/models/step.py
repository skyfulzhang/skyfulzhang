"""步骤定义模型"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


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
