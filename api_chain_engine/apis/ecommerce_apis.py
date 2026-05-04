"""示例电商接口封装 - 7个业务接口定义"""
from __future__ import annotations
from models.api_def import APIDefinition
from models.step import StepDefinition, ExtractRule, AssertRule
from core.registry import APIRegistry


def get_ecommerce_apis() -> list[APIDefinition]:
    """返回所有电商示例接口定义"""
    return [
        # A: 用户登录
        APIDefinition(
            api_id="user_login",
            name="用户登录",
            method="POST",
            url="{{base_url}}/api/auth/login",
            headers={"Content-Type": "application/json"},
            params={},
            body={
                "username": "{{username}}",
                "password": "{{password}}",
            },
            timeout=30,
            description="用户登录接口，返回 token 和 user_id",
            module="用户模块",
            tags=["auth", "user"],
        ),
        # B: 获取用户信息
        APIDefinition(
            api_id="get_user_profile",
            name="获取用户信息",
            method="GET",
            url="{{base_url}}/api/users/{{user_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="根据 user_id 获取用户详细信息",
            module="用户模块",
            tags=["user", "profile"],
        ),
        # C: 搜索商品
        APIDefinition(
            api_id="search_product",
            name="搜索商品",
            method="GET",
            url="{{base_url}}/api/products/search",
            headers={"Authorization": "Bearer {{token}}"},
            params={
                "keyword": "{{keyword}}",
                "page": "{{page}}",
                "size": "{{size}}",
            },
            body={},
            timeout=30,
            description="根据关键词搜索商品，返回商品列表",
            module="商品模块",
            tags=["product", "search"],
        ),
        # D: 获取商品详情
        APIDefinition(
            api_id="get_product_detail",
            name="商品详情",
            method="GET",
            url="{{base_url}}/api/products/{{product_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="根据 product_id 获取商品详情，返回 stock 和 sku_id",
            module="商品模块",
            tags=["product", "detail"],
        ),
        # E: 创建订单
        APIDefinition(
            api_id="create_order",
            name="创建订单",
            method="POST",
            url="{{base_url}}/api/orders",
            headers={
                "Authorization": "Bearer {{token}}",
                "Content-Type": "application/json",
            },
            params={},
            body={
                "user_id": "{{user_id}}",
                "product_id": "{{product_id}}",
                "sku_id": "{{sku_id}}",
                "quantity": "{{quantity}}",
                "address": "{{address}}",
            },
            timeout=30,
            description="创建订单，依赖 user_id、product_id、sku_id 从上下文获取",
            module="订单模块",
            tags=["order", "create"],
        ),
        # F: 支付订单
        APIDefinition(
            api_id="pay_order",
            name="支付订单",
            method="POST",
            url="{{base_url}}/api/orders/{{order_id}}/pay",
            headers={
                "Authorization": "Bearer {{token}}",
                "Content-Type": "application/json",
            },
            params={},
            body={
                "payment_method": "{{payment_method}}",
                "amount": "{{amount}}",
            },
            timeout=30,
            description="支付订单，依赖 order_id 从上下文获取",
            module="支付模块",
            tags=["order", "payment"],
        ),
        # G: 查询订单
        APIDefinition(
            api_id="query_order",
            name="查询订单",
            method="GET",
            url="{{base_url}}/api/orders/{{order_id}}",
            headers={"Authorization": "Bearer {{token}}"},
            params={},
            body={},
            timeout=30,
            description="查询订单详情，依赖 order_id 从上下文获取",
            module="订单模块",
            tags=["order", "query"],
        ),
    ]


def create_registry() -> APIRegistry:
    """创建并注册所有电商接口，返回注册中心"""
    registry = APIRegistry()
    registry.register_batch(get_ecommerce_apis())
    return registry


# ──────────────────────────────────────────────
# Mock 响应数据（用于测试）
# ──────────────────────────────────────────────

MOCK_RESPONSES: dict[str, dict] = {
    "user_login": {
        "code": 0,
        "message": "登录成功",
        "data": {
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.mock_token",
            "user_id": "10086",
            "username": "test_user",
        },
    },
    "get_user_profile": {
        "code": 0,
        "message": "success",
        "data": {
            "user_id": "10086",
            "nickname": "测试用户",
            "vip_level": 3,
            "email": "test@example.com",
        },
    },
    "search_product": {
        "code": 0,
        "message": "success",
        "data": {
            "total": 100,
            "list": [
                {
                    "product_id": "P20240001",
                    "product_name": "iPhone 15 Pro",
                    "price": 8999.00,
                    "cover": "https://example.com/iphone15.jpg",
                }
            ],
        },
    },
    "get_product_detail": {
        "code": 0,
        "message": "success",
        "data": {
            "product_id": "P20240001",
            "product_name": "iPhone 15 Pro",
            "price": 8999.00,
            "stock": 500,
            "sku_id": "SKU_IPHONE15_BLACK_256G",
            "specs": {"color": "黑色", "storage": "256G"},
        },
    },
    "create_order": {
        "code": 0,
        "message": "订单创建成功",
        "data": {
            "order_id": "ORD20240001",
            "order_no": "NO20240001001",
            "status": "pending_payment",
            "total_amount": 8999.00,
        },
    },
    "pay_order": {
        "code": 0,
        "message": "支付成功",
        "data": {
            "order_id": "ORD20240001",
            "pay_status": "paid",
            "transaction_id": "TXN20240001",
            "paid_at": "2024-01-01 10:00:00",
        },
    },
    "query_order": {
        "code": 0,
        "message": "success",
        "data": {
            "order_id": "ORD20240001",
            "order_no": "NO20240001001",
            "order_status": "paid",
            "items": [
                {
                    "product_id": "P20240001",
                    "product_name": "iPhone 15 Pro",
                    "quantity": 1,
                    "price": 8999.00,
                }
            ],
        },
    },
}
