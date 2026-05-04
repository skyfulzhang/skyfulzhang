"""电商完整链路集成测试"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests_mock as requests_mock_lib

from apis.ecommerce_apis import create_registry, MOCK_RESPONSES
from core.executor import ChainExecutor
from core.tracer import ExecutionTracer
from core.parser import ParameterParser
from core.extractor import ResponseExtractor
from core.assertion import AssertionEngine
from config import config


def build_executor():
    registry = create_registry()
    return ChainExecutor(
        registry=registry,
        tracer=ExecutionTracer(),
        parser=ParameterParser(),
        extractor=ResponseExtractor(),
        assertion_engine=AssertionEngine(),
    )


def setup_mock_adapter(m: requests_mock_lib.Mocker) -> None:
    """配置 mock 响应"""
    base = config.BASE_URL
    m.post(f"{base}/api/auth/login", json=MOCK_RESPONSES["user_login"])
    m.get(f"{base}/api/products/search", json=MOCK_RESPONSES["search_product"])
    m.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_product_detail"],
          additional_matcher=lambda req: "/api/products/" in req.url and "search" not in req.url)
    m.post(f"{base}/api/orders", json=MOCK_RESPONSES["create_order"])
    m.post(requests_mock_lib.ANY, json=MOCK_RESPONSES["pay_order"],
           additional_matcher=lambda req: "/pay" in req.url)
    m.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["query_order"],
          additional_matcher=lambda req: "/api/orders/" in req.url)
    m.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_user_profile"],
          additional_matcher=lambda req: "/api/users/" in req.url)


class TestEcommerceChain1:
    """链路1：商品下单完整流程 (A → C → E → G)"""

    def test_chain1_success(self):
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        assert result.status == "success"
        assert len(result.step_results) == 4

    def test_chain1_step_login_extracts_token(self):
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        login_result = result.step_results[0]
        assert "token" in login_result.extractions
        assert login_result.extractions["token"] is not None
        assert "user_id" in login_result.extractions

    def test_chain1_step_search_extracts_product(self):
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        search_result = result.step_results[1]
        assert "product_id" in search_result.extractions
        assert search_result.extractions["product_id"] == "P20240001"

    def test_chain1_step_create_order_extracts_order_id(self):
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        order_result = result.step_results[2]
        assert "order_id" in order_result.extractions
        assert order_result.extractions["order_id"] == "ORD20240001"

    def test_chain1_all_assertions_pass(self):
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        summary = result.summary
        assert summary["total_assertions"] > 0
        assert summary["passed_assertions"] == summary["total_assertions"]

    def test_chain1_context_propagation(self):
        """验证上下文在步骤间传递"""
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        # 上下文快照中应包含各步骤提取的变量
        snapshot = result.context_snapshot
        assert "token" in snapshot
        assert "user_id" in snapshot
        assert "product_id" in snapshot
        assert "order_id" in snapshot


class TestEcommerceChain2:
    """链路2：下单并支付流程 (A → C → D → E → F → G)"""

    def test_chain2_success(self):
        from main import build_chain2, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain2()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        assert result.status == "success"
        assert len(result.step_results) == 6

    def test_chain2_pay_status_is_paid(self):
        from main import build_chain2, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain2()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        pay_result = result.step_results[4]  # step5: pay_order
        assert "pay_status" in pay_result.extractions
        assert pay_result.extractions["pay_status"] == "paid"

    def test_chain2_order_status_is_paid(self):
        from main import build_chain2, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain2()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        query_result = result.step_results[5]  # step6: query_order
        assert "order_status" in query_result.extractions
        assert query_result.extractions["order_status"] == "paid"

    def test_chain2_summary_stats(self):
        from main import build_chain2, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain2()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        summary = result.summary
        assert summary["total_steps"] == 6
        assert summary["success_steps"] == 6
        assert summary["failed_steps"] == 0
        assert summary["skipped_steps"] == 0


class TestSQLitePersistence:
    """SQLite 持久化测试"""

    def test_save_and_load_chain(self, tmp_path):
        from storage.sqlite_store import ChainStore
        from main import build_chain1

        store = ChainStore(str(tmp_path / "test.db"))
        chain = build_chain1()
        store.save_chain(chain)

        loaded = store.load_chain(chain.chain_id)
        assert loaded.chain_id == chain.chain_id
        assert loaded.name == chain.name
        assert len(loaded.steps) == len(chain.steps)

    def test_save_execution_summary(self, tmp_path):
        from storage.sqlite_store import ChainStore
        from main import build_chain1, build_executor as main_build_executor
        executor = main_build_executor()
        chain = build_chain1()

        with requests_mock_lib.Mocker() as m:
            setup_mock_adapter(m)
            result = executor.execute(chain)

        store = ChainStore(str(tmp_path / "test.db"))
        store.save_chain(chain)
        store.save_execution_summary(result)

        history = store.get_execution_history(chain.chain_id)
        assert len(history) == 1
        assert history[0]["status"] == "success"

    def test_export_and_import_yaml(self, tmp_path):
        from storage.sqlite_store import ChainStore
        from main import build_chain1

        store = ChainStore(str(tmp_path / "test.db"))
        chain = build_chain1()
        store.save_chain(chain)

        yaml_path = str(tmp_path / "chain.yaml")
        store.export_chain_yaml(chain.chain_id, yaml_path)
        assert os.path.exists(yaml_path)

        # 删除再从 YAML 导入
        store.delete_chain(chain.chain_id)
        imported = store.import_chain_yaml(yaml_path)
        assert imported.chain_id == chain.chain_id
        assert len(imported.steps) == len(chain.steps)

    def test_list_chains(self, tmp_path):
        from storage.sqlite_store import ChainStore
        from main import build_chain1, build_chain2

        store = ChainStore(str(tmp_path / "test.db"))
        store.save_chain(build_chain1())
        store.save_chain(build_chain2())

        chains = store.list_chains()
        assert len(chains) == 2
        chain_ids = [c["chain_id"] for c in chains]
        assert "ecommerce_order_chain" in chain_ids
        assert "ecommerce_pay_chain" in chain_ids

    def test_delete_chain(self, tmp_path):
        from storage.sqlite_store import ChainStore
        from main import build_chain1

        store = ChainStore(str(tmp_path / "test.db"))
        chain = build_chain1()
        store.save_chain(chain)
        store.delete_chain(chain.chain_id)

        with pytest.raises(KeyError):
            store.load_chain(chain.chain_id)


class TestAPIRegistry:
    """接口注册中心测试"""

    def test_all_apis_registered(self):
        registry = create_registry()
        assert len(registry) == 7

    def test_get_api(self):
        registry = create_registry()
        api = registry.get("user_login")
        assert api.api_id == "user_login"
        assert api.method == "POST"

    def test_list_by_module(self):
        registry = create_registry()
        user_apis = registry.list_by_module("用户模块")
        assert len(user_apis) == 2  # user_login, get_user_profile

    def test_search(self):
        registry = create_registry()
        results = registry.search("订单")
        api_ids = [a.api_id for a in results]
        assert "create_order" in api_ids
        assert "query_order" in api_ids

    def test_show_tree(self):
        registry = create_registry()
        tree = registry.show_tree()
        assert "用户模块" in tree
        assert "商品模块" in tree
        assert "订单模块" in tree
        assert "支付模块" in tree

    def test_unknown_api_raises_key_error(self):
        registry = create_registry()
        with pytest.raises(KeyError):
            registry.get("nonexistent_api")
