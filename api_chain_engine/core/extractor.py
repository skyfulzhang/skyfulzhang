"""响应提取器 - 从接口响应中提取变量存入上下文"""
from __future__ import annotations
import re
import json
from typing import Any, TYPE_CHECKING

import jmespath

if TYPE_CHECKING:
    import requests
    from core.context import ExecutionContext
    from models.step import ExtractRule


class ResponseExtractor:
    """从接口响应中提取变量存入上下文"""

    def extract(
        self,
        response: "requests.Response",
        rules: list["ExtractRule"],
        context: "ExecutionContext",
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
            except Exception as e:
                extracted[rule.var_name] = rule.default
                context.set(rule.var_name, rule.default)
        return extracted

    def _extract_one(self, response: "requests.Response", rule: "ExtractRule") -> Any:
        """根据提取规则提取单个值"""
        source = rule.source.lower()
        extractor_type = rule.extractor.lower()

        if source == "status_code":
            return response.status_code

        if source == "header":
            return self._header_extract(response, rule.expression)

        # body 提取
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
            # 如果有分组则返回第一个分组，否则返回整个匹配
            return m.group(1) if m.lastindex else m.group(0)
        except Exception as e:
            raise ValueError(f"正则提取失败 [{pattern}]: {e}") from e

    def _header_extract(self, response: "requests.Response", key: str) -> Any:
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
