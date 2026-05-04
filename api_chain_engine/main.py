"""
接口智能编排与链式执行引擎 - CLI 入口 & 交互式演示

运行方式：
    cd api_chain_engine
    python main.py

演示两条业务链路：
    链路1: 商品下单完整流程 (A → C → E → G)
    链路2: 下单并支付流程  (A → C → D → E → F → G)
"""
from __future__ import annotations
import sys
import os

# 将当前目录加入 sys.path 方便模块导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests_mock as requests_mock_lib
from rich.console import Console
from rich.panel import Panel
from rich import box

from config import config
from apis.ecommerce_apis import create_registry, MOCK_RESPONSES
from models.chain import ChainDefinition
from models.step import StepDefinition, ExtractRule, AssertRule
from core.registry import APIRegistry
from core.context import ExecutionContext
from core.parser import ParameterParser
from core.extractor import ResponseExtractor
from core.assertion import AssertionEngine
from core.executor import ChainExecutor
from core.tracer import ExecutionTracer
from core.cleaner import DataCleaner
from storage.sqlite_store import ChainStore

console = Console()


# ──────────────────────────────────────────────
# 构建链路定义
# ──────────────────────────────────────────────

def build_chain1() -> ChainDefinition:
    """链路1：商品下单完整流程 (A → C → E → G)"""
    return ChainDefinition(
        chain_id="ecommerce_order_chain",
        name="商品下单完整流程",
        description="用户登录 → 搜索商品 → 创建订单 → 查询订单",
        global_variables={
            "base_url": config.BASE_URL,
            "username": "test_user",
            "password": "Test@123",
            "keyword": "iPhone",
            "page": 1,
            "size": 10,
            "quantity": 1,
            "address": "北京市朝阳区xx路xx号",
        },
        tags=["ecommerce", "order", "smoke"],
        steps=[
            # Step1: 用户登录
            StepDefinition(
                step_id="step_login",
                api_id="user_login",
                name="用户登录",
                param_overrides={},
                extracts=[
                    ExtractRule(
                        var_name="token",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.token",
                        default=None,
                    ),
                    ExtractRule(
                        var_name="user_id",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.user_id",
                        default=None,
                    ),
                ],
                assertions=[
                    AssertRule(
                        name="状态码为200",
                        source="status_code",
                        expression="status_code",
                        operator="eq",
                        expected=200,
                        message="登录接口状态码应为200",
                    ),
                    AssertRule(
                        name="业务码为0",
                        source="body",
                        expression="$.code",
                        operator="eq",
                        expected=0,
                        message="登录业务码应为0",
                    ),
                    AssertRule(
                        name="token不为空",
                        source="body",
                        expression="$.data.token",
                        operator="exists",
                        expected=None,
                        message="登录成功后应返回token",
                    ),
                ],
                on_failure="stop",
            ),
            # Step2: 搜索商品
            StepDefinition(
                step_id="step_search",
                api_id="search_product",
                name="搜索商品",
                param_overrides={},
                extracts=[
                    ExtractRule(
                        var_name="product_id",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.list[0].product_id",
                        default=None,
                    ),
                    ExtractRule(
                        var_name="product_name",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.list[0].product_name",
                        default=None,
                    ),
                    ExtractRule(
                        var_name="price",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.list[0].price",
                        default=None,
                    ),
                ],
                assertions=[
                    AssertRule(
                        name="状态码为200",
                        source="status_code",
                        expression="status_code",
                        operator="eq",
                        expected=200,
                        message="搜索接口状态码应为200",
                    ),
                    AssertRule(
                        name="商品列表不为空",
                        source="body",
                        expression="$.data.list",
                        operator="exists",
                        expected=None,
                        message="搜索结果不应为空",
                    ),
                ],
                on_failure="stop",
            ),
            # Step3: 创建订单（依赖 user_id, product_id）
            StepDefinition(
                step_id="step_create_order",
                api_id="create_order",
                name="创建订单",
                param_overrides={
                    "body": {
                        "sku_id": "SKU_DEFAULT",  # 链路1中没有查详情，使用默认值
                    }
                },
                extracts=[
                    ExtractRule(
                        var_name="order_id",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.order_id",
                        default=None,
                    ),
                    ExtractRule(
                        var_name="order_no",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.order_no",
                        default=None,
                    ),
                ],
                assertions=[
                    AssertRule(
                        name="状态码为200",
                        source="status_code",
                        expression="status_code",
                        operator="eq",
                        expected=200,
                        message="创建订单接口状态码应为200",
                    ),
                    AssertRule(
                        name="订单ID不为空",
                        source="body",
                        expression="$.data.order_id",
                        operator="exists",
                        expected=None,
                        message="创建订单后应返回order_id",
                    ),
                    AssertRule(
                        name="业务码为0",
                        source="body",
                        expression="$.code",
                        operator="eq",
                        expected=0,
                        message="创建订单业务码应为0",
                    ),
                ],
                depends_on=["step_login", "step_search"],
                on_failure="stop",
            ),
            # Step4: 查询订单（依赖 order_id）
            StepDefinition(
                step_id="step_query_order",
                api_id="query_order",
                name="查询订单",
                param_overrides={},
                extracts=[
                    ExtractRule(
                        var_name="order_status",
                        source="body",
                        extractor="jsonpath",
                        expression="$.data.order_status",
                        default=None,
                    ),
                ],
                assertions=[
                    AssertRule(
                        name="状态码为200",
                        source="status_code",
                        expression="status_code",
                        operator="eq",
                        expected=200,
                        message="查询订单接口状态码应为200",
                    ),
                    AssertRule(
                        name="订单状态为待支付",
                        source="body",
                        expression="$.data.order_status",
                        operator="in",
                        expected=["pending_payment", "paid"],
                        message="订单应处于待支付或已支付状态",
                    ),
                ],
                depends_on=["step_create_order"],
                on_failure="continue",
            ),
        ],
    )


def build_chain2() -> ChainDefinition:
    """链路2：下单并支付流程 (A → C → D → E → F → G)"""
    return ChainDefinition(
        chain_id="ecommerce_pay_chain",
        name="下单并支付完整流程",
        description="用户登录 → 搜索商品 → 获取商品详情 → 创建订单 → 支付订单 → 查询订单",
        global_variables={
            "base_url": config.BASE_URL,
            "username": "test_user",
            "password": "Test@123",
            "keyword": "iPhone",
            "page": 1,
            "size": 10,
            "quantity": 1,
            "address": "上海市浦东新区xx路xx号",
            "payment_method": "alipay",
            "amount": 8999.00,
        },
        tags=["ecommerce", "order", "payment", "e2e"],
        steps=[
            # Step1: 用户登录
            StepDefinition(
                step_id="step_login",
                api_id="user_login",
                name="用户登录",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="token", source="body", extractor="jsonpath",
                                expression="$.data.token", default=None),
                    ExtractRule(var_name="user_id", source="body", extractor="jsonpath",
                                expression="$.data.user_id", default=None),
                ],
                assertions=[
                    AssertRule(name="登录成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="登录接口应返回200"),
                    AssertRule(name="token存在", source="body", expression="$.data.token",
                               operator="exists", expected=None, message="应返回token"),
                ],
                on_failure="stop",
            ),
            # Step2: 搜索商品
            StepDefinition(
                step_id="step_search",
                api_id="search_product",
                name="搜索商品",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="product_id", source="body", extractor="jsonpath",
                                expression="$.data.list[0].product_id", default=None),
                ],
                assertions=[
                    AssertRule(name="搜索成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="搜索接口应返回200"),
                ],
                on_failure="stop",
            ),
            # Step3: 获取商品详情（依赖 product_id）
            StepDefinition(
                step_id="step_product_detail",
                api_id="get_product_detail",
                name="获取商品详情",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="sku_id", source="body", extractor="jsonpath",
                                expression="$.data.sku_id", default=None),
                    ExtractRule(var_name="stock", source="body", extractor="jsonpath",
                                expression="$.data.stock", default=None),
                ],
                assertions=[
                    AssertRule(name="商品详情获取成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="商品详情接口应返回200"),
                    AssertRule(name="库存充足", source="body", expression="$.data.stock",
                               operator="gt", expected=0, message="商品库存应大于0"),
                ],
                depends_on=["step_search"],
                on_failure="stop",
            ),
            # Step4: 创建订单
            StepDefinition(
                step_id="step_create_order",
                api_id="create_order",
                name="创建订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="order_id", source="body", extractor="jsonpath",
                                expression="$.data.order_id", default=None),
                    ExtractRule(var_name="order_no", source="body", extractor="jsonpath",
                                expression="$.data.order_no", default=None),
                ],
                assertions=[
                    AssertRule(name="创建订单成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="创建订单接口应返回200"),
                    AssertRule(name="order_id存在", source="body", expression="$.data.order_id",
                               operator="exists", expected=None, message="应返回order_id"),
                ],
                depends_on=["step_login", "step_search", "step_product_detail"],
                on_failure="stop",
            ),
            # Step5: 支付订单（依赖 order_id）
            StepDefinition(
                step_id="step_pay_order",
                api_id="pay_order",
                name="支付订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="pay_status", source="body", extractor="jsonpath",
                                expression="$.data.pay_status", default=None),
                    ExtractRule(var_name="transaction_id", source="body", extractor="jsonpath",
                                expression="$.data.transaction_id", default=None),
                ],
                assertions=[
                    AssertRule(name="支付成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="支付接口应返回200"),
                    AssertRule(name="支付状态为paid", source="body", expression="$.data.pay_status",
                               operator="eq", expected="paid", message="支付状态应为paid"),
                ],
                depends_on=["step_create_order"],
                on_failure="stop",
            ),
            # Step6: 查询订单
            StepDefinition(
                step_id="step_query_order",
                api_id="query_order",
                name="查询订单",
                param_overrides={},
                extracts=[
                    ExtractRule(var_name="order_status", source="body", extractor="jsonpath",
                                expression="$.data.order_status", default=None),
                ],
                assertions=[
                    AssertRule(name="查询成功", source="status_code", expression="status_code",
                               operator="eq", expected=200, message="查询订单接口应返回200"),
                    AssertRule(name="订单状态为已支付", source="body", expression="$.data.order_status",
                               operator="eq", expected="paid", message="订单状态应为paid"),
                ],
                depends_on=["step_pay_order"],
                on_failure="continue",
            ),
        ],
    )


# ──────────────────────────────────────────────
# 构建执行引擎
# ──────────────────────────────────────────────

def build_executor() -> ChainExecutor:
    """构建链式执行器"""
    registry = create_registry()
    tracer = ExecutionTracer()
    parser = ParameterParser()
    extractor = ResponseExtractor()
    assertion_engine = AssertionEngine()
    return ChainExecutor(
        registry=registry,
        tracer=tracer,
        parser=parser,
        extractor=extractor,
        assertion_engine=assertion_engine,
    )


# ──────────────────────────────────────────────
# Mock 请求拦截
# ──────────────────────────────────────────────

def setup_mock(mock_adapter: requests_mock_lib.Mocker) -> None:
    """配置 mock 响应"""
    from apis.ecommerce_apis import MOCK_RESPONSES
    import json

    base = config.BASE_URL

    # 用户登录
    mock_adapter.post(f"{base}/api/auth/login", json=MOCK_RESPONSES["user_login"])
    # 获取用户信息 (匹配任意 user_id)
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_user_profile"],
                     additional_matcher=lambda req: "/api/users/" in req.url)
    # 搜索商品
    mock_adapter.get(f"{base}/api/products/search", json=MOCK_RESPONSES["search_product"])
    # 商品详情
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["get_product_detail"],
                     additional_matcher=lambda req: "/api/products/" in req.url and "search" not in req.url)
    # 创建订单
    mock_adapter.post(f"{base}/api/orders", json=MOCK_RESPONSES["create_order"])
    # 支付订单
    mock_adapter.post(requests_mock_lib.ANY, json=MOCK_RESPONSES["pay_order"],
                      additional_matcher=lambda req: "/pay" in req.url)
    # 查询订单
    mock_adapter.get(requests_mock_lib.ANY, json=MOCK_RESPONSES["query_order"],
                     additional_matcher=lambda req: "/api/orders/" in req.url)


# ──────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────

def main() -> None:
    console.print(Panel.fit(
        "[bold cyan]🔗 接口智能编排与链式执行引擎[/bold cyan]\n"
        "[dim]API Chain Execution Engine v1.0.0[/dim]",
        box=box.DOUBLE,
        style="blue",
    ))

    # 初始化存储
    store = ChainStore(config.DB_PATH)

    # 构建执行器
    executor = build_executor()

    # 使用 requests_mock 拦截请求
    with requests_mock_lib.Mocker() as mock:
        setup_mock(mock)

        # ─────────────── 链路1 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 演示链路1: 商品下单完整流程 (A → C → E → G)[/bold yellow]")
        console.print("=" * 60)

        chain1 = build_chain1()
        result1 = executor.execute(chain1)

        # 保存链路模板
        store.save_chain(chain1)
        store.save_execution_summary(result1)
        console.print(f"[green]✅ 链路模板已保存到 SQLite: {config.DB_PATH}[/green]")

        # 生成报告
        executor.tracer.generate_report(result1)

        # ─────────────── 链路2 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 演示链路2: 下单并支付完整流程 (A → C → D → E → F → G)[/bold yellow]")
        console.print("=" * 60)

        chain2 = build_chain2()
        result2 = executor.execute(chain2)

        store.save_chain(chain2)
        store.save_execution_summary(result2)
        console.print(f"[green]✅ 链路模板已保存到 SQLite: {config.DB_PATH}[/green]")

        executor.tracer.generate_report(result2)

        # ─────────────── 验证加载 ───────────────
        console.print("\n" + "=" * 60)
        console.print("[bold yellow]▶ 验证: 从 SQLite 重新加载链路并执行[/bold yellow]")
        console.print("=" * 60)

        loaded_chain = store.load_chain("ecommerce_order_chain")
        console.print(f"[green]✅ 成功加载链路: {loaded_chain.name}[/green]")

        result_loaded = executor.execute(loaded_chain)
        console.print(
            f"重新执行结果: [{'green' if result_loaded.status == 'success' else 'red'}]"
            f"{'✅ SUCCESS' if result_loaded.status == 'success' else '❌ FAILED'}[/]"
        )

    # 显示已保存的链路列表
    console.print("\n[bold]📋 已保存链路列表:[/bold]")
    chains = store.list_chains()
    for c in chains:
        console.print(f"  • {c['chain_id']}: {c['name']}")

    console.print("\n[bold green]🎉 演示完成！[/bold green]")


if __name__ == "__main__":
    main()
