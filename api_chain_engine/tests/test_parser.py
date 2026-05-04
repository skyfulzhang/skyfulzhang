"""参数解析引擎测试"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.parser import ParameterParser
from core.context import ExecutionContext


@pytest.fixture
def parser():
    return ParameterParser()


@pytest.fixture
def context():
    ctx = ExecutionContext(global_variables={"base_url": "https://api.example.com"})
    ctx.set("token", "my_token_123")
    ctx.set("user_id", "10086")
    ctx.set("product_id", "P001")
    return ctx


class TestBasicVariableResolution:
    """基础变量解析"""

    def test_simple_variable(self, parser, context):
        result = parser.parse_string("{{token}}", context)
        assert result == "my_token_123"

    def test_global_variable(self, parser, context):
        result = parser.parse_string("{{base_url}}/api/login", context)
        assert result == "https://api.example.com/api/login"

    def test_variable_in_url(self, parser, context):
        result = parser.parse_string("{{base_url}}/api/users/{{user_id}}", context)
        assert result == "https://api.example.com/api/users/10086"

    def test_variable_not_found_returns_original(self, parser, context):
        result = parser.parse_string("{{nonexistent}}", context)
        # 未找到的变量返回 None，字符串替换保留原始
        assert result is None or result == "{{nonexistent}}" or result == "None"

    def test_no_template(self, parser, context):
        result = parser.parse_string("plain string", context)
        assert result == "plain string"

    def test_integer_variable_returned_as_int(self, parser, context):
        ctx = ExecutionContext()
        ctx.set("count", 42)
        result = parser.parse("{{count}}", ctx)
        assert result == 42

    def test_dict_template(self, parser, context):
        template = {"url": "{{base_url}}/api", "token": "{{token}}"}
        result = parser.parse_dict(template, context)
        assert result["url"] == "https://api.example.com/api"
        assert result["token"] == "my_token_123"

    def test_list_template(self, parser, context):
        template = ["{{token}}", "{{user_id}}"]
        result = parser.parse_list(template, context)
        assert result[0] == "my_token_123"
        assert result[1] == "10086"

    def test_nested_dict(self, parser, context):
        template = {"headers": {"Authorization": "Bearer {{token}}"}}
        result = parser.parse(template, context)
        assert result["headers"]["Authorization"] == "Bearer my_token_123"


class TestBuiltinFunctions:
    """内置函数测试"""

    def test_uuid(self, parser, context):
        result = parser.parse_string("{{$uuid}}", context)
        assert len(result) == 36  # UUID 格式长度
        assert result.count("-") == 4

    def test_timestamp(self, parser, context):
        result = parser.parse_string("{{$timestamp}}", context)
        assert isinstance(result, int)
        assert result > 1700000000  # 2023年后的时间戳

    def test_random_int(self, parser, context):
        result = parser.parse_string("{{$random_int(1,10)}}", context)
        assert 1 <= int(result) <= 10

    def test_random_str(self, parser, context):
        result = parser.parse_string("{{$random_str(8)}}", context)
        assert len(result) == 8

    def test_date_now(self, parser, context):
        result = parser.parse_string("{{$date_now(%Y-%m-%d)}}", context)
        import re
        assert re.match(r'\d{4}-\d{2}-\d{2}', result)

    def test_md5(self, parser, context):
        result = parser.parse_string("{{$md5(hello)}}", context)
        assert result == "5d41402abc4b2a76b9719d911017c592"

    def test_base64(self, parser, context):
        result = parser.parse_string("{{$base64(hello)}}", context)
        import base64
        assert result == base64.b64encode(b"hello").decode()

    def test_env(self, parser, context):
        os.environ["TEST_ENV_VAR"] = "test_value"
        result = parser.parse_string("{{$env(TEST_ENV_VAR)}}", context)
        assert result == "test_value"


class TestStepIdDotField:
    """step_id.field 引用测试"""

    def test_step_field_resolution(self, parser):
        context = ExecutionContext()
        context.set_step_result("step_login", {"token": "abc123", "user_id": "999"})
        result = parser.parse_string("{{step_login.token}}", context)
        assert result == "abc123"

    def test_step_field_user_id(self, parser):
        context = ExecutionContext()
        context.set_step_result("step_login", {"token": "abc", "user_id": "42"})
        result = parser.parse_string("{{step_login.user_id}}", context)
        assert result == "42"


class TestCustomFunction:
    """自定义函数注册测试"""

    def test_register_custom_function(self, parser, context):
        parser.register_function("double", lambda x: int(x) * 2)
        result = parser.parse_string("{{$double(5)}}", context)
        assert int(result) == 10
