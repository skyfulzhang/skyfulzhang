"""链路模型"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .step import StepDefinition


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
