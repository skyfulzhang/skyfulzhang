# -*- coding: utf-8 -*-
"""
步骤定义模型
描述链路中的一个执行步骤，包含参数覆盖、提取规则、断言规则
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ExtractRule:
    """
    响应提取规则：从接口响应中提取值存入上下文

    示例:
        ExtractRule(var_name="token", source="body", extractor="jsonpath", expression="$.data.token")
        ExtractRule(var_name="order_id", source="body", extractor="jsonpath", expression="$.data.order_id")
        ExtractRule(var_name="request_id", source="header", extractor="key", expression="X-Request-Id")
    """
    var_name: str          # 提取后存入上下文的变量名
    source: str            # 来源: "body" | "header" | "status_code"
    extractor: str         # 提取器: "jsonpath" | "jmespath" | "regex" | "key"
    expression: str        # 提取表达式
    default: Any = None    # 提取失败时的默认值

    def to_dict(self) -> dict:
        return {
            "var_name": self.var_name,
            "source": self.source,
            "extractor": self.extractor,
            "expression": self.expression,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractRule":
        return cls(**data)


@dataclass
class AssertRule:
    """
    断言规则：校验接口响应是否符合预期

    示例:
        AssertRule(name="状态码校验", source="status_code", expression="", operator="eq", expected=200)
        AssertRule(name="业务码校验", source="body", expression="$.code", operator="eq", expected=0)
        AssertRule(name="token存在", source="body", expression="$.data.token", operator="exists", expected=None)
    """
    name: str              # 断言名称
    source: str            # 来源: "body" | "header" | "status_code" | "context"
    expression: str        # JSONPath / Header Key / Context Key
    operator: str          # 操作符，见 AssertionEngine.OPERATORS
    expected: Any = None   # 期望值（支持模板变量 {{var}}）
    message: str = ""      # 断言失败时的自定义提示

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "expression": self.expression,
            "operator": self.operator,
            "expected": self.expected,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssertRule":
        return cls(**data)


@dataclass
class StepDefinition:
    """
    步骤定义：链路中的一个执行单元
    - 引用一个已注册的接口 (api_id)
    - 通过 param_overrides 覆盖接口默认参数（支持 {{变量}} 模板引用上下文）
    - 通过 extracts 提取响应变量供后续步骤使用
    - 通过 assertions 校验接口响应
    """
    step_id: str                                                  # 步骤唯一ID
    api_id: str                                                   # 引用的接口ID
    name: str                                                     # 步骤名称
    param_overrides: dict = field(default_factory=dict)           # 参数覆盖（含模板变量）
    extracts: List[ExtractRule] = field(default_factory=list)     # 响应提取规则
    assertions: List[AssertRule] = field(default_factory=list)    # 断言规则
    depends_on: List[str] = field(default_factory=list)           # 依赖的步骤ID
    on_failure: str = "stop"                                      # 失败策略: stop|continue|skip_next
    pre_scripts: List[str] = field(default_factory=list)          # 前置脚本（Python 表达式）
    post_scripts: List[str] = field(default_factory=list)         # 后置脚本
    retry: int = 0                                                # 失败重试次数
    sleep_before: float = 0.0                                     # 执行前等待秒数

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "api_id": self.api_id,
            "name": self.name,
            "param_overrides": self.param_overrides,
            "extracts": [e.to_dict() for e in self.extracts],
            "assertions": [a.to_dict() for a in self.assertions],
            "depends_on": self.depends_on,
            "on_failure": self.on_failure,
            "pre_scripts": self.pre_scripts,
            "post_scripts": self.post_scripts,
            "retry": self.retry,
            "sleep_before": self.sleep_before,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StepDefinition":
        d = dict(data)
        d["extracts"] = [ExtractRule.from_dict(e) for e in d.get("extracts", [])]
        d["assertions"] = [AssertRule.from_dict(a) for a in d.get("assertions", [])]
        return cls(**d)
