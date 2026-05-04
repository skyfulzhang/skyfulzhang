# -*- coding: utf-8 -*-
"""
参数解析引擎
将模板字符串中的 {{variable}} 替换为上下文中的实际值，
并支持 {{$function(args)}} 内置函数调用。
"""
import re
import uuid
import random
import string
import hashlib
import base64
import os
from datetime import datetime
from typing import Any, Callable
from loguru import logger


class ParameterParser:
    """
    模板解析引擎，支持以下语法：

      {{variable_name}}           - 从上下文获取变量
      {{step_id.field}}           - 从指定步骤响应获取字段（通过上下文 step_responses）
      {{$random_int(1,100)}}      - 随机整数
      {{$random_str(8)}}          - 随机字母数字字符串
      {{$random_float(1.0,9.9)}}  - 随机浮点数
      {{$uuid}}                   - UUID4
      {{$timestamp}}              - 当前秒级时间戳
      {{$timestamp_ms}}           - 当前毫秒级时间戳
      {{$date_now(%Y-%m-%d)}}     - 格式化日期
      {{$env(ENV_VAR_NAME)}}      - 读取环境变量
      {{$md5(value)}}             - MD5 哈希（小写十六进制）
      {{$base64(value)}}          - Base64 编码
      {{$upper(value)}}           - 转大写
      {{$lower(value)}}           - 转小写
    """

    # 匹配 {{...}} 模板占位符
    _PATTERN = re.compile(r"\{\{(.+?)\}\}")

    def __init__(self):
        self._custom_functions: dict[str, Callable] = {}

    # ------------------------------------------------------------------ #
    #  公开 API
    # ------------------------------------------------------------------ #

    def parse(self, template: Any, context) -> Any:
        """递归解析任意类型的模板（str / dict / list / 其他原始类型）"""
        if isinstance(template, str):
            return self.parse_string(template, context)
        if isinstance(template, dict):
            return self.parse_dict(template, context)
        if isinstance(template, list):
            return self.parse_list(template, context)
        return template  # int / float / bool / None 直接返回

    def parse_string(self, template: str, context) -> Any:
        """
        解析字符串模板。
        若整个字符串就是一个占位符（如 {{user_id}}），返回原始类型（int/dict/…）。
        若字符串包含多个占位符或混合文本，则全部替换为字符串后拼接。
        """
        matches = self._PATTERN.findall(template)
        if not matches:
            return template

        # 纯单占位符：返回原始值以保留类型
        if template.strip() == f"{{{{{matches[0]}}}}}":
            return self._resolve(matches[0].strip(), context)

        # 多占位符或混合文本：全部转为字符串替换
        def replacer(m):
            val = self._resolve(m.group(1).strip(), context)
            return str(val) if val is not None else ""

        return self._PATTERN.sub(replacer, template)

    def parse_dict(self, template: dict, context) -> dict:
        """递归解析字典"""
        return {k: self.parse(v, context) for k, v in template.items()}

    def parse_list(self, template: list, context) -> list:
        """递归解析列表"""
        return [self.parse(item, context) for item in template]

    def register_function(self, name: str, func: Callable) -> None:
        """注册自定义内置函数，使用 {{$name(args)}} 调用"""
        self._custom_functions[name] = func
        logger.debug(f"[Parser] 注册自定义函数: ${name}")

    # ------------------------------------------------------------------ #
    #  内部解析
    # ------------------------------------------------------------------ #

    def _resolve(self, expr: str, context) -> Any:
        """解析单个表达式"""
        # 内置函数调用
        if expr.startswith("$"):
            return self._call_builtin(expr[1:], context)

        # step_id.field 形式（从步骤响应中取值）
        if "." in expr:
            parts = expr.split(".", 1)
            step_resp = context.get_step_response(parts[0])
            if step_resp is not None and isinstance(step_resp, dict):
                return step_resp.get(parts[1])

        # 普通变量
        val = context.get(expr)
        if val is None:
            logger.warning(f"[Parser] 变量未找到: '{expr}'，将保留原始占位符")
            return f"{{{{{expr}}}}}"
        return val

    def _call_builtin(self, func_expr: str, context) -> Any:
        """调用内置或自定义函数"""
        # 无参函数
        if func_expr in ("uuid", "uuid4"):
            return str(uuid.uuid4())
        if func_expr == "timestamp":
            return int(datetime.now().timestamp())
        if func_expr == "timestamp_ms":
            return int(datetime.now().timestamp() * 1000)

        # 有参函数：解析函数名和参数
        m = re.match(r"(\w+)\((.*)\)$", func_expr)
        if not m:
            # 自定义无参函数
            if func_expr in self._custom_functions:
                return self._custom_functions[func_expr]()
            logger.warning(f"[Parser] 未知内置函数: ${func_expr}")
            return f"{{{{${func_expr}}}}}"

        name, raw_args = m.group(1), m.group(2)
        args = [a.strip() for a in raw_args.split(",")] if raw_args.strip() else []

        # 自定义函数优先
        if name in self._custom_functions:
            return self._custom_functions[name](*args)

        return self._dispatch_builtin(name, args, context)

    def _dispatch_builtin(self, name: str, args: list[str], context) -> Any:
        """分发到具体内置函数实现"""
        try:
            if name == "random_int":
                lo, hi = int(args[0]), int(args[1])
                return random.randint(lo, hi)

            if name == "random_str":
                length = int(args[0]) if args else 8
                chars = string.ascii_letters + string.digits
                return "".join(random.choices(chars, k=length))

            if name == "random_float":
                lo, hi = float(args[0]), float(args[1])
                return round(random.uniform(lo, hi), 2)

            if name == "date_now":
                fmt = args[0] if args else "%Y-%m-%d %H:%M:%S"
                return datetime.now().strftime(fmt)

            if name == "env":
                env_key = args[0] if args else ""
                val = os.getenv(env_key)
                if val is None:
                    logger.warning(f"[Parser] 环境变量未设置: {env_key}")
                return val

            if name == "md5":
                val = args[0] if args else ""
                return hashlib.md5(val.encode()).hexdigest()

            if name == "base64":
                val = args[0] if args else ""
                return base64.b64encode(val.encode()).decode()

            if name == "upper":
                return args[0].upper() if args else ""

            if name == "lower":
                return args[0].lower() if args else ""

        except (IndexError, ValueError) as e:
            logger.error(f"[Parser] 内置函数 ${name} 参数错误: {e}")
            return None

        logger.warning(f"[Parser] 未知内置函数: ${name}")
        return f"{{{{${name}({','.join(args)})}}}}"
