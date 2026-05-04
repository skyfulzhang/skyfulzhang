# -*- coding: utf-8 -*-
"""
步骤定义模型
描述链路中一个执行步骤的完整配置，包括参数覆盖、提取规则、断言规则等
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExtractRule:
    """
    响应提取规则：从接口响应中提取变量存入上下文
    """
    var_name: str           # 提取后存入上下文的变量名
    source: str             # 来源: body | header | status_code | response_time
    extractor: str          # 提取器: jsonpath | jmespath | regex | key
    expression: str         # 提取表达式，如 "$.data.token"
    default: Any = None     # 提取失败时的默认值
    description: str = ""   # 说明

    def to_dict(self) -> dict:
        return {
            "var_name": self.var_name,
            "source": self.source,
            "extractor": self.extractor,
            "expression": self.expression,
            "default": self.default,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractRule":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AssertRule:
    """
    断言规则：对接口响应进行校验
    """
    name: str               # 断言名称，如 "校验状态码"
    source: str             # 来源: body | header | status_code | context
    expression: str         # JSONPath 或字段 key，如 "$.code" 或 "status_code"
    operator: str           # 操作符，如 eq | ne | contains | exists 等
    expected: Any = None    # 期望值（支持模板变量）
    message: str = ""       # 断言失败时的提示信息

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
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StepDefinition:
    """
    链路步骤定义，引用一个接口，并配置该步骤的参数覆盖、提取和断言规则。
    """
    step_id: str                                        # 步骤唯一ID，如 "step_login"
    api_id: str                                         # 引用的接口ID
    name: str                                           # 步骤名称
    param_overrides: dict = field(default_factory=dict) # 参数覆盖（支持模板变量）
    extracts: list = field(default_factory=list)        # ExtractRule 列表
    assertions: list = field(default_factory=list)      # AssertRule 列表
    depends_on: list = field(default_factory=list)      # 依赖步骤ID列表
    on_failure: str = "stop"                            # 失败策略: stop | continue | skip_next
    pre_scripts: list = field(default_factory=list)     # 前置 Python 表达式
    post_scripts: list = field(default_factory=list)    # 后置 Python 表达式
    description: str = ""                               # 步骤描述
    enabled: bool = True                                # 是否启用

    def __post_init__(self):
        # 将 dict 转换为对象
        self.extracts = [
            ExtractRule.from_dict(e) if isinstance(e, dict) else e
            for e in self.extracts
        ]
        self.assertions = [
            AssertRule.from_dict(a) if isinstance(a, dict) else a
            for a in self.assertions
        ]

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
            "description": self.description,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StepDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
