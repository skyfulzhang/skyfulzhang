"""参数解析引擎 - 支持 {{}} 模板语法"""
from __future__ import annotations
import re
import os
import uuid
import random
import string
import hashlib
import base64
import time
from datetime import datetime
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import ExecutionContext

# 模板变量匹配正则：{{variable}} 或 {{$func(args)}}
_TEMPLATE_PATTERN = re.compile(r'\{\{(.+?)\}\}')


class ParameterParser:
    """
    参数解析引擎，支持以下语法：
    - {{variable_name}}           从上下文获取变量
    - {{step_id.field}}           从指定步骤响应获取字段
    - {{$random_int(1,100)}}      内置函数：随机整数
    - {{$random_str(8)}}          内置函数：随机字符串
    - {{$uuid}}                   内置函数：UUID
    - {{$timestamp}}              内置函数：当前时间戳
    - {{$date_now(%Y-%m-%d)}}     内置函数：格式化日期
    - {{$env(ENV_VAR_NAME)}}      内置函数：读取环境变量
    - {{$md5(value)}}             内置函数：MD5 哈希
    - {{$base64(value)}}          内置函数：Base64 编码
    """

    def __init__(self) -> None:
        self._custom_functions: dict[str, Callable] = {}

    # ──────────────────────────────────────────────
    # 公开 API
    # ──────────────────────────────────────────────

    def parse(self, template: Any, context: "ExecutionContext") -> Any:
        """解析任意类型模板"""
        if isinstance(template, str):
            return self.parse_string(template, context)
        if isinstance(template, dict):
            return self.parse_dict(template, context)
        if isinstance(template, list):
            return self.parse_list(template, context)
        return template

    def parse_string(self, template: str, context: "ExecutionContext") -> Any:
        """解析字符串模板，返回替换后的值"""
        if not isinstance(template, str):
            return template

        # 如果整个字符串就是一个模板变量，直接返回原始类型（[^{}]+ 防止匹配嵌套花括号）
        full_match = re.fullmatch(r'\{\{([^{}]+?)\}\}', template)
        if full_match:
            return self._resolve_expression(full_match.group(1).strip(), context)

        # 否则做字符串替换
        def replacer(m: re.Match) -> str:
            value = self._resolve_expression(m.group(1).strip(), context)
            return str(value) if value is not None else m.group(0)

        return _TEMPLATE_PATTERN.sub(replacer, template)

    def parse_dict(self, template: dict, context: "ExecutionContext") -> dict:
        """递归解析字典"""
        return {key: self.parse(value, context) for key, value in template.items()}

    def parse_list(self, template: list, context: "ExecutionContext") -> list:
        """递归解析列表"""
        return [self.parse(item, context) for item in template]

    def register_function(self, name: str, func: Callable) -> None:
        """注册自定义函数"""
        self._custom_functions[name] = func

    # ──────────────────────────────────────────────
    # 私有：表达式求值
    # ──────────────────────────────────────────────

    def _resolve_expression(self, expr: str, context: "ExecutionContext") -> Any:
        """解析单个模板表达式"""
        expr = expr.strip()

        # 内置函数
        if expr.startswith("$"):
            return self._call_builtin(expr[1:], context)

        # step_id.field 形式
        if "." in expr:
            parts = expr.split(".", 1)
            step_id, field = parts[0], parts[1]
            step_data = context.get_step_result(step_id)
            if step_data and field in step_data:
                return step_data[field]
            # 尝试从上下文直接获取
            return context.get(expr)

        # 普通变量
        return context.get(expr)

    def _call_builtin(self, func_expr: str, context: "ExecutionContext") -> Any:
        """调用内置函数"""
        # 解析函数名和参数：func_name(arg1,arg2) 或 func_name
        m = re.match(r'^(\w+)(?:\((.*)?\))?$', func_expr, re.DOTALL)
        if not m:
            return None

        func_name = m.group(1)
        raw_args = m.group(2) or ""
        args = [a.strip() for a in raw_args.split(",") if a.strip()] if raw_args else []

        # 先查自定义函数
        if func_name in self._custom_functions:
            return self._custom_functions[func_name](*args)

        # 内置函数分发
        return self._dispatch_builtin(func_name, args)

    def _dispatch_builtin(self, name: str, args: list[str]) -> Any:
        """内置函数分发"""
        if name == "uuid":
            return str(uuid.uuid4())

        if name == "timestamp":
            return int(time.time())

        if name == "random_int":
            lo = int(args[0]) if len(args) > 0 else 0
            hi = int(args[1]) if len(args) > 1 else 100
            return random.randint(lo, hi)

        if name == "random_str":
            length = int(args[0]) if args else 8
            return "".join(random.choices(string.ascii_letters + string.digits, k=length))

        if name == "date_now":
            fmt = args[0] if args else "%Y-%m-%d %H:%M:%S"
            return datetime.now().strftime(fmt)

        if name == "env":
            var_name = args[0] if args else ""
            return os.getenv(var_name, "")

        if name == "md5":
            value = args[0] if args else ""
            return hashlib.md5(value.encode()).hexdigest()

        if name == "base64":
            value = args[0] if args else ""
            return base64.b64encode(value.encode()).decode()

        return None
