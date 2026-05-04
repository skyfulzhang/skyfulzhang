"""断言引擎测试"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pytest
import requests_mock as requests_mock_lib

from core.assertion import AssertionEngine
from core.context import ExecutionContext
from models.step import AssertRule


@pytest.fixture
def engine():
    return AssertionEngine()


@pytest.fixture
def context():
    ctx = ExecutionContext()
    ctx.set("expected_code", 0)
    return ctx


def make_response(status_code: int = 200, body: dict = None, headers: dict = None):
    """构建模拟 Response 对象"""
    with requests_mock_lib.Mocker() as m:
        m.get("http://test.local/", status_code=status_code,
              json=body or {}, headers=headers or {})
        import requests
        resp = requests.get("http://test.local/")
    return resp


class TestStatusCodeAssertions:
    """状态码断言"""

    def test_status_code_eq_pass(self, engine, context):
        resp = make_response(200)
        rule = AssertRule(name="状态码200", source="status_code", expression="status_code",
                          operator="eq", expected=200)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_status_code_eq_fail(self, engine, context):
        resp = make_response(404)
        rule = AssertRule(name="状态码200", source="status_code", expression="status_code",
                          operator="eq", expected=200)
        record = engine.run_single(resp, rule, context)
        assert record.passed is False
        assert record.actual == 404

    def test_status_code_ne(self, engine, context):
        resp = make_response(200)
        rule = AssertRule(name="非500", source="status_code", expression="status_code",
                          operator="ne", expected=500)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True


class TestBodyAssertions:
    """响应体断言"""

    def test_jsonpath_eq(self, engine, context):
        resp = make_response(200, body={"code": 0, "message": "success"})
        rule = AssertRule(name="code=0", source="body", expression="$.code",
                          operator="eq", expected=0)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_jsonpath_exists(self, engine, context):
        resp = make_response(200, body={"data": {"token": "abc"}})
        rule = AssertRule(name="token存在", source="body", expression="$.data.token",
                          operator="exists", expected=None)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_jsonpath_not_none(self, engine, context):
        resp = make_response(200, body={"data": {"token": "abc"}})
        rule = AssertRule(name="token不为None", source="body", expression="$.data.token",
                          operator="not_none", expected=None)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_contains(self, engine, context):
        resp = make_response(200, body={"message": "login success"})
        rule = AssertRule(name="消息包含success", source="body", expression="$.message",
                          operator="contains", expected="success")
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_gt(self, engine, context):
        resp = make_response(200, body={"data": {"stock": 100}})
        rule = AssertRule(name="库存>0", source="body", expression="$.data.stock",
                          operator="gt", expected=0)
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_in_operator(self, engine, context):
        resp = make_response(200, body={"data": {"status": "paid"}})
        rule = AssertRule(name="状态在列表中", source="body", expression="$.data.status",
                          operator="in", expected=["pending", "paid", "cancelled"])
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_regex_operator(self, engine, context):
        resp = make_response(200, body={"data": {"order_id": "ORD20240001"}})
        rule = AssertRule(name="order_id格式正确", source="body", expression="$.data.order_id",
                          operator="regex", expected=r"^ORD\d+$")
        record = engine.run_single(resp, rule, context)
        assert record.passed is True

    def test_startswith(self, engine, context):
        resp = make_response(200, body={"data": {"order_no": "NO20240001001"}})
        rule = AssertRule(name="order_no以NO开头", source="body", expression="$.data.order_no",
                          operator="startswith", expected="NO")
        record = engine.run_single(resp, rule, context)
        assert record.passed is True


class TestRunAssertions:
    """批量断言执行"""

    def test_all_pass(self, engine, context):
        resp = make_response(200, body={"code": 0, "data": {"token": "abc"}})
        rules = [
            AssertRule(name="状态码", source="status_code", expression="status_code",
                       operator="eq", expected=200),
            AssertRule(name="code=0", source="body", expression="$.code",
                       operator="eq", expected=0),
        ]
        records = engine.run_assertions(resp, rules, context)
        assert len(records) == 2
        assert all(r.passed for r in records)

    def test_partial_fail(self, engine, context):
        resp = make_response(200, body={"code": 1, "message": "error"})
        rules = [
            AssertRule(name="状态码", source="status_code", expression="status_code",
                       operator="eq", expected=200),
            AssertRule(name="code=0", source="body", expression="$.code",
                       operator="eq", expected=0),
        ]
        records = engine.run_assertions(resp, rules, context)
        assert records[0].passed is True
        assert records[1].passed is False

    def test_empty_rules(self, engine, context):
        resp = make_response(200)
        records = engine.run_assertions(resp, [], context)
        assert records == []


class TestUnsupportedOperator:
    """不支持的操作符"""

    def test_unknown_operator_returns_failed_record(self, engine, context):
        resp = make_response(200, body={"code": 0})
        rule = AssertRule(name="测试", source="body", expression="$.code",
                          operator="unknown_op", expected=0)
        record = engine.run_single(resp, rule, context)
        assert record.passed is False
        assert record.error is not None
