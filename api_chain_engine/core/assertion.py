"""断言引擎 - 支持丰富的断言操作符"""
from __future__ import annotations
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import requests
    from core.context import ExecutionContext
    from models.step import AssertRule

from models.chain import AssertionRecord


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
        response: "requests.Response",
        rules: list["AssertRule"],
        context: "ExecutionContext",
    ) -> list[AssertionRecord]:
        """执行所有断言规则"""
        records: list[AssertionRecord] = []
        for rule in rules:
            record = self.run_single(response, rule, context)
            records.append(record)
        return records

    def run_single(
        self,
        response: "requests.Response",
        rule: "AssertRule",
        context: "ExecutionContext",
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

    # ──────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────

    def _get_actual(
        self,
        response: "requests.Response",
        rule: "AssertRule",
        context: "ExecutionContext",
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
        # 简单 key 路径
        parts = expression.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _resolve_expected(self, expected: Any, context: "ExecutionContext") -> Any:
        """解析期望值（支持模板变量）"""
        if isinstance(expected, str) and "{{" in expected:
            return context.get(expected.strip("{{").strip("}}"))
        return expected
