# -*- coding: utf-8 -*-
"""
链路定义与执行结果模型
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class RequestRecord:
    """请求记录"""
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    body: Any = None
    curl: str = ""  # 等价 cURL 命令，方便排查

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
            "curl": self.curl,
        }


@dataclass
class ResponseRecord:
    """响应记录"""
    status_code: int = 0
    headers: dict = field(default_factory=dict)
    body: Any = None
    raw_text: str = ""
    duration_ms: float = 0.0
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "body": self.body,
            "raw_text": self.raw_text,
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
        }


@dataclass
class AssertionRecord:
    """单条断言执行结果"""
    name: str
    passed: bool
    operator: str
    expression: str
    actual: Any
    expected: Any
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "operator": self.operator,
            "expression": self.expression,
            "actual": self.actual,
            "expected": self.expected,
            "message": self.message,
            "error": self.error,
        }


@dataclass
class StepResult:
    """单步执行结果"""
    step_id: str
    api_id: str
    name: str
    status: str = "pending"           # pending | success | failed | skipped
    request: Optional[RequestRecord] = None
    response: Optional[ResponseRecord] = None
    extractions: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)   # list[AssertionRecord]
    duration_ms: float = 0.0
    error: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""

    @property
    def assertion_passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    @property
    def failed_assertions(self) -> list:
        return [a for a in self.assertions if not a.passed]

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
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class CleanupResult:
    """数据清理任务执行结果"""
    task_name: str
    success: bool
    message: str = ""
    error: str = ""


@dataclass
class ChainDefinition:
    """链路定义，描述一条完整的接口调用链路"""
    chain_id: str
    name: str
    description: str = ""
    steps: list = field(default_factory=list)              # list[StepDefinition]
    global_variables: dict = field(default_factory=dict)   # 全局变量（base_url 等）
    tags: list = field(default_factory=list)
    author: str = ""
    version: str = "1.0"
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
            "author": self.author,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ChainResult:
    """链路执行结果"""
    chain_id: str
    chain_name: str
    status: str = "pending"           # success | failed | aborted
    step_results: list = field(default_factory=list)   # list[StepResult]
    context_snapshot: dict = field(default_factory=dict)
    total_duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""

    @property
    def summary(self) -> dict:
        total = len(self.step_results)
        success = sum(1 for s in self.step_results if s.status == "success")
        failed = sum(1 for s in self.step_results if s.status == "failed")
        skipped = sum(1 for s in self.step_results if s.status == "skipped")
        total_assertions = sum(len(s.assertions) for s in self.step_results)
        passed_assertions = sum(
            sum(1 for a in s.assertions if a.passed) for s in self.step_results
        )
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
            "step_results": [s.to_dict() for s in self.step_results],
            "context_snapshot": self.context_snapshot,
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
        }
