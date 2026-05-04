# -*- coding: utf-8 -*-
"""
链路模型：链路定义 + 执行结果
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime

from .step import StepDefinition


@dataclass
class ChainDefinition:
    """
    链路定义：一组有序步骤构成的业务流程。
    保存时只保存结构和参数模板，不保存具体参数值。
    """
    chain_id: str
    name: str
    description: str = ""
    steps: List[StepDefinition] = field(default_factory=list)
    global_variables: Dict[str, Any] = field(default_factory=dict)  # 全局变量模板
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "global_variables": self.global_variables,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChainDefinition":
        d = dict(data)
        d["steps"] = [StepDefinition.from_dict(s) for s in d.get("steps", [])]
        return cls(**d)


@dataclass
class RequestRecord:
    """请求记录快照"""
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Optional[Any] = None

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
        }


@dataclass
class ResponseRecord:
    """响应记录快照"""
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "body": self.body,
            "raw_text": self.raw_text,
        }


@dataclass
class AssertionRecord:
    """单条断言执行结果"""
    name: str
    passed: bool
    operator: str
    actual: Any
    expected: Any
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "operator": self.operator,
            "actual": self.actual,
            "expected": self.expected,
            "message": self.message,
            "error": self.error,
        }


@dataclass
class StepResult:
    """单步骤执行结果"""
    step_id: str
    api_id: str
    name: str
    status: str                                                   # success | failed | skipped | error
    request: Optional[RequestRecord] = None
    response: Optional[ResponseRecord] = None
    extractions: Dict[str, Any] = field(default_factory=dict)    # 本步骤提取的变量
    assertions: List[AssertionRecord] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    retry_count: int = 0

    @property
    def assertion_passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    @property
    def assertion_summary(self) -> str:
        total = len(self.assertions)
        passed = sum(1 for a in self.assertions if a.passed)
        return f"{passed}/{total}"

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "api_id": self.api_id,
            "name": self.name,
            "status": self.status,
            "request": self.request.to_dict() if self.request else None,
            "response": self.response.to_dict() if self.response else None,
            "extractions": self.extractions,
            "assertions": [a.to_dict() for a in self.assertions],
            "duration_ms": self.duration_ms,
            "error": self.error,
            "retry_count": self.retry_count,
        }


@dataclass
class ChainResult:
    """链路执行结果"""
    chain_id: str
    chain_name: str
    status: str                                                    # success | failed
    step_results: List[StepResult] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    error: Optional[str] = None

    @property
    def summary(self) -> dict:
        total = len(self.step_results)
        success = sum(1 for r in self.step_results if r.status == "success")
        failed = sum(1 for r in self.step_results if r.status == "failed")
        skipped = sum(1 for r in self.step_results if r.status == "skipped")
        total_assertions = sum(len(r.assertions) for r in self.step_results)
        passed_assertions = sum(sum(1 for a in r.assertions if a.passed) for r in self.step_results)
        return {
            "total_steps": total,
            "success_steps": success,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_assertions": total_assertions,
            "passed_assertions": passed_assertions,
            "failed_assertions": total_assertions - passed_assertions,
        }

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "status": self.status,
            "step_results": [r.to_dict() for r in self.step_results],
            "context_snapshot": self.context_snapshot,
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "summary": self.summary,
        }


@dataclass
class CleanupResult:
    """清理任务执行结果"""
    task_name: str
    success: bool
    message: str = ""
    error: Optional[str] = None
