# -*- coding: utf-8 -*-
"""
链路模型
定义链路的输入（ChainDefinition）和输出（ChainResult）数据结构
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime

from .step import StepDefinition


@dataclass
class ChainDefinition:
    """
    链路定义
    描述一条完整的接口执行链路，包含有序步骤和全局变量。
    保存时只存结构和模板，不存具体参数值。
    """
    chain_id: str
    name: str
    description: str = ""
    steps: List[StepDefinition] = field(default_factory=list)
    global_variables: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, data: Dict[str, Any]) -> "ChainDefinition":
        steps = [StepDefinition.from_dict(s) for s in data.get("steps", [])]
        return cls(
            chain_id=data["chain_id"],
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            global_variables=data.get("global_variables", {}),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


@dataclass
class RequestRecord:
    """请求记录"""
    method: str
    url: str
    headers: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
        }


@dataclass
class ResponseRecord:
    """响应记录"""
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = None
    duration_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "body": self.body,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class AssertionRecord:
    """单条断言执行记录"""
    name: str
    passed: bool
    operator: str
    actual: Any
    expected: Any
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
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
    status: str                                         # success | failed | skipped | error
    request: Optional[RequestRecord] = None
    response: Optional[ResponseRecord] = None
    extractions: Dict[str, Any] = field(default_factory=dict)
    assertions: List[AssertionRecord] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def assertion_passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    @property
    def assertion_total(self) -> int:
        return len(self.assertions)

    @property
    def assertion_pass_count(self) -> int:
        return sum(1 for a in self.assertions if a.passed)

    def to_dict(self) -> Dict[str, Any]:
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
            "started_at": self.started_at,
        }


@dataclass
class CleanupResult:
    """数据清理结果"""
    task_name: str
    success: bool
    message: str = ""
    error: Optional[str] = None


@dataclass
class ChainResult:
    """链路执行完整结果"""
    chain_id: str
    chain_name: str
    status: str                                             # success | failed
    step_results: List[StepResult] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: Optional[str] = None

    @property
    def summary(self) -> Dict[str, Any]:
        total = len(self.step_results)
        success = sum(1 for s in self.step_results if s.status == "success")
        failed = sum(1 for s in self.step_results if s.status == "failed")
        skipped = sum(1 for s in self.step_results if s.status == "skipped")
        total_assertions = sum(s.assertion_total for s in self.step_results)
        passed_assertions = sum(s.assertion_pass_count for s in self.step_results)
        return {
            "total_steps": total,
            "success_steps": success,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_assertions": total_assertions,
            "passed_assertions": passed_assertions,
            "failed_assertions": total_assertions - passed_assertions,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "status": self.status,
            "step_results": [s.to_dict() for s in self.step_results],
            "context_snapshot": self.context_snapshot,
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "error": self.error,
        }
