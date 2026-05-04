# -*- coding: utf-8 -*-
"""
步骤定义模型
描述链路中的单个执行步骤，包含参数覆盖、提取规则、断言规则
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExtractRule:
    """
    响应提取规则

    示例:
        ExtractRule(var_name="token", source="body", extractor="jsonpath", expression="$.data.token")
        ExtractRule(var_name="order_id", source="body", extractor="jsonpath", expression="$.data.order_id")
        ExtractRule(var_name="trace_id", source="header", extractor="key", expression="X-Trace-Id")
    """
    var_name: str           # 提取后存入上下文的变量名
    source: str             # 来源: body | header | status_code
    extractor: str          # jsonpath | jmespath | regex | key
    expression: str         # 提取表达式
    default: Any = None     # 提取失败时的默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "var_name": self.var_name,
            "source": self.source,
            "extractor": self.extractor,
            "expression": self.expression,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractRule":
        return cls(**data)


@dataclass
class AssertRule:
    """
    断言规则

    示例:
        AssertRule(name="状态码为200", source="status_code", expression="", operator="eq", expected=200)
        AssertRule(name="code为0", source="body", expression="$.code", operator="eq", expected=0)
        AssertRule(name="token存在", source="body", expression="$.data.token", operator="exists", expected=None)
    """
    name: str               # 断言名称
    source: str             # body | header | status_code | context
    expression: str         # JSONPath 或 key（status_code 时留空）
    operator: str           # eq | ne | gt | gte | lt | lte | contains | not_contains
                            # startswith | endswith | exists | is_none | not_none
                            # regex | in | not_in | length_eq | length_gt | type_is
    expected: Any = None    # 期望值（支持模板变量）
    message: str = ""       # 断言失败提示

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "expression": self.expression,
            "operator": self.operator,
            "expected": self.expected,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssertRule":
        return cls(**data)


@dataclass
class StepDefinition:
    """
    步骤定义模型

    一个步骤对应链路中的一个接口调用节点，包含：
    - 引用的接口ID
    - 参数覆盖（可使用模板变量引用上下文）
    - 响应提取规则
    - 断言规则
    - 依赖关系
    - 失败策略
    """
    step_id: str                                    # 步骤唯一ID
    api_id: str                                     # 引用的接口ID
    name: str                                       # 步骤名称
    param_overrides: Dict[str, Any] = field(default_factory=dict)   # 参数覆盖
    extracts: List[ExtractRule] = field(default_factory=list)        # 提取规则
    assertions: List[AssertRule] = field(default_factory=list)       # 断言规则
    depends_on: List[str] = field(default_factory=list)              # 依赖步骤ID
    on_failure: str = "stop"                        # stop | continue | skip_next
    pre_scripts: List[str] = field(default_factory=list)             # 前置脚本
    post_scripts: List[str] = field(default_factory=list)            # 后置脚本
    skip: bool = False                              # 是否跳过此步骤
    description: str = ""                           # 步骤描述

    def to_dict(self) -> Dict[str, Any]:
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
            "skip": self.skip,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepDefinition":
        extracts = [ExtractRule.from_dict(e) for e in data.get("extracts", [])]
        assertions = [AssertRule.from_dict(a) for a in data.get("assertions", [])]
        return cls(
            step_id=data["step_id"],
            api_id=data["api_id"],
            name=data["name"],
            param_overrides=data.get("param_overrides", {}),
            extracts=extracts,
            assertions=assertions,
            depends_on=data.get("depends_on", []),
            on_failure=data.get("on_failure", "stop"),
            pre_scripts=data.get("pre_scripts", []),
            post_scripts=data.get("post_scripts", []),
            skip=data.get("skip", False),
            description=data.get("description", ""),
        )
