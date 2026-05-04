# 接口智能编排与链式执行引擎

**API Chain Execution Engine** — 面向测试工程师的接口自动化编排平台

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-orange)](https://pytest.org)

---

## 项目架构图

```
api_chain_engine/
┌─────────────────────────────────────────────────────────────────────┐
│                    接口智能编排与链式执行引擎                            │
│                 API Chain Execution Engine v1.0                     │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
    ┌───────────┬────────┴────────┬────────────┬────────────┐
    ▼           ▼                 ▼            ▼            ▼
┌───────┐ ┌─────────┐     ┌──────────┐ ┌──────────┐ ┌──────────┐
│接口注册│ │上下文管理│     │参数解析引擎│ │ 响应提取器│ │ 断言引擎 │
│Registry│ │Context  │     │  Parser  │ │Extractor │ │Assertion │
└───┬───┘ └────┬────┘     └────┬─────┘ └────┬─────┘ └────┬─────┘
    │          │               │             │             │
    └──────────┴───────────────┼─────────────┴─────────────┘
                               │
                     ┌─────────▼──────────┐
                     │   链式执行器 (核心)   │
                     │   ChainExecutor    │
                     │                   │
                     │  A → C → E → G    │
                     └─────────┬─────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                       ▼
 ┌────────────┐        ┌──────────────┐        ┌────────────┐
 │ 可观测追踪  │        │  SQLite 存储  │        │  数据清理器 │
 │  Tracer    │        │  ChainStore  │        │  Cleaner  │
 │(彩色控制台) │        │ (链路模板持久化)│        │(清理测试数据)│
 └────────────┘        └──────────────┘        └────────────┘

models/          ── 数据模型层 (APIDefinition, StepDefinition, ChainDefinition)
apis/            ── 接口封装层 (电商7个示例接口 + Mock响应)
storage/         ── 持久化层 (SQLite)
tests/           ── 单元测试 + 集成测试 (67个用例)
```

---

## 快速开始（3步）

### 第1步：安装依赖

```bash
cd api_chain_engine
pip install -r requirements.txt
```

### 第2步：运行演示

```bash
python main.py
```

输出两条完整业务链路的彩色执行报告，并在 `reports/` 目录生成 HTML 报告。

### 第3步：运行测试

```bash
pytest tests/ -v
```

---

## 核心概念说明

### 接口注册中心（APIRegistry）

所有业务接口统一注册，支持按模块、标签查询：

```python
from core.registry import APIRegistry
from models.api_def import APIDefinition

registry = APIRegistry()
registry.register(APIDefinition(
    api_id="user_login",
    name="用户登录",
    method="POST",
    url="{{base_url}}/api/auth/login",
    body={"username": "{{username}}", "password": "{{password}}"},
    module="用户模块",
    tags=["auth"],
))

# 查询
api = registry.get("user_login")
user_apis = registry.list_by_module("用户模块")
print(registry.show_tree())   # 树形展示
```

### 上下文管理器（ExecutionContext）

跨步骤变量共享，三级作用域：

```python
from core.context import ExecutionContext

ctx = ExecutionContext(global_variables={"base_url": "https://api.example.com"})
ctx.set("token", "xxx", scope="chain")    # 链路级（跨步骤共享）
ctx.set("temp", "yyy", scope="step")      # 步骤级（步骤结束自动清除）

value = ctx.get("token")         # 优先级: step > chain > global
snapshot = ctx.snapshot()        # 获取当前所有变量快照
```

### 链路定义（ChainDefinition）

按业务顺序定义步骤：

```python
from models.chain import ChainDefinition
from models.step import StepDefinition, ExtractRule, AssertRule

chain = ChainDefinition(
    chain_id="my_chain",
    name="我的测试链路",
    global_variables={"base_url": "https://api.example.com"},
    steps=[
        StepDefinition(
            step_id="step1",
            api_id="user_login",
            name="登录",
            extracts=[
                ExtractRule(var_name="token", source="body",
                            extractor="jsonpath", expression="$.data.token"),
            ],
            assertions=[
                AssertRule(name="登录成功", source="status_code",
                           expression="status_code", operator="eq", expected=200),
            ],
        ),
        # ... 更多步骤
    ],
)
```

---

## 完整的链路定义示例（YAML 格式）

通过 `ChainStore` 导出的 YAML 格式：

```yaml
chain_id: ecommerce_order_chain
name: 商品下单完整流程
description: 用户登录 → 搜索商品 → 创建订单 → 查询订单
global_variables:
  base_url: https://api.example.com
  username: test_user
  password: Test@123
  keyword: iPhone
  quantity: 1
tags: [ecommerce, order, smoke]

steps:
  - step_id: step_login
    api_id: user_login
    name: 用户登录
    on_failure: stop
    extracts:
      - var_name: token
        source: body
        extractor: jsonpath
        expression: $.data.token
      - var_name: user_id
        source: body
        extractor: jsonpath
        expression: $.data.user_id
    assertions:
      - name: 状态码为200
        source: status_code
        expression: status_code
        operator: eq
        expected: 200

  - step_id: step_search
    api_id: search_product
    name: 搜索商品
    depends_on: [step_login]
    extracts:
      - var_name: product_id
        source: body
        extractor: jsonpath
        expression: $.data.list[0].product_id

  - step_id: step_create_order
    api_id: create_order
    name: 创建订单
    depends_on: [step_login, step_search]
    extracts:
      - var_name: order_id
        source: body
        extractor: jsonpath
        expression: $.data.order_id

  - step_id: step_query_order
    api_id: query_order
    name: 查询订单
    depends_on: [step_create_order]
    assertions:
      - name: 订单状态正常
        source: body
        expression: $.data.order_status
        operator: in
        expected: [pending_payment, paid]
```

---

## 参数模板语法说明

引擎支持 `{{}}` 风格的模板语法，在步骤执行前自动解析：

| 语法 | 说明 | 示例 |
|------|------|------|
| `{{variable}}` | 从上下文获取变量 | `{{token}}` → `eyJhbG...` |
| `{{step_id.field}}` | 从指定步骤结果获取 | `{{step_login.user_id}}` |
| `{{$uuid}}` | 生成 UUID | `{{$uuid}}` → `4b6f1...` |
| `{{$timestamp}}` | 当前时间戳（秒） | `{{$timestamp}}` → `1700000000` |
| `{{$random_int(1,100)}}` | 随机整数 | `{{$random_int(1,100)}}` → `42` |
| `{{$random_str(8)}}` | 随机字符串 | `{{$random_str(8)}}` → `Xk3mPq9z` |
| `{{$date_now(%Y-%m-%d)}}` | 格式化日期 | `{{$date_now(%Y-%m-%d)}}` → `2024-01-01` |
| `{{$env(API_KEY)}}` | 读取环境变量 | `{{$env(API_KEY)}}` → `sk-xxx` |
| `{{$md5(value)}}` | MD5 哈希 | `{{$md5(hello)}}` → `5d41402a...` |
| `{{$base64(value)}}` | Base64 编码 | `{{$base64(hello)}}` → `aGVsbG8=` |

支持注册自定义函数：
```python
from core.parser import ParameterParser
parser = ParameterParser()
parser.register_function("my_func", lambda x: x.upper())
# 使用：{{$my_func(hello)}} → HELLO
```

---

## 断言操作符说明

| 操作符 | 说明 | 示例 expected |
|--------|------|--------------|
| `eq` | 等于 | `200` |
| `ne` | 不等于 | `500` |
| `gt` | 大于 | `0` |
| `gte` | 大于等于 | `1` |
| `lt` | 小于 | `100` |
| `lte` | 小于等于 | `99` |
| `contains` | 包含（字符串/列表） | `"success"` |
| `not_contains` | 不包含 | `"error"` |
| `startswith` | 以...开头 | `"ORD"` |
| `endswith` | 以...结尾 | `"_001"` |
| `exists` | 不为 None | `null` |
| `is_none` | 为 None | `null` |
| `not_none` | 不为 None | `null` |
| `regex` | 正则匹配 | `"^ORD\\d+$"` |
| `in` | 在列表中 | `["paid","pending"]` |
| `not_in` | 不在列表中 | `["cancelled"]` |
| `length_eq` | 长度等于 | `10` |
| `length_gt` | 长度大于 | `0` |
| `type_is` | 类型判断 | `"str"` |

---

## 响应提取规则示例

支持 4 种提取方式：

```python
from models.step import ExtractRule

# JSONPath 提取
ExtractRule(var_name="token", source="body", extractor="jsonpath",
            expression="$.data.token")

# JMESPath 提取
ExtractRule(var_name="items", source="body", extractor="jmespath",
            expression="data.list[*].product_id")

# 正则提取
ExtractRule(var_name="order_id", source="body", extractor="regex",
            expression=r"order_id\":\"(\w+)\"")

# Header 提取
ExtractRule(var_name="request_id", source="header", extractor="key",
            expression="X-Request-Id")

# 状态码提取
ExtractRule(var_name="status", source="status_code", extractor="key",
            expression="status_code")
```

---

## CLI 使用方法

### 运行完整演示

```bash
cd api_chain_engine
python main.py
```

### 使用 Python API

```python
from core.executor import ChainExecutor
from core.registry import APIRegistry
from core.tracer import ExecutionTracer
from core.parser import ParameterParser
from core.extractor import ResponseExtractor
from core.assertion import AssertionEngine
from storage.sqlite_store import ChainStore

# 构建执行器
executor = ChainExecutor(
    registry=registry,
    tracer=ExecutionTracer(),
    parser=ParameterParser(),
    extractor=ResponseExtractor(),
    assertion_engine=AssertionEngine(),
)

# 执行链路
result = executor.execute(chain)

# 保存链路
store = ChainStore("chain_store.db")
store.save_chain(chain)

# 加载并重新执行
loaded_chain = store.load_chain("my_chain_id")
result = executor.execute(loaded_chain)

# 导出为 YAML
store.export_chain_yaml("my_chain_id", "my_chain.yaml")

# 干跑（不发请求，只解析参数）
dry_results = executor.dry_run(chain)
```

---

## 扩展开发指南

### 1. 添加新接口

```python
from models.api_def import APIDefinition
from core.registry import APIRegistry

registry = APIRegistry()
registry.register(APIDefinition(
    api_id="my_api",
    name="我的接口",
    method="POST",
    url="{{base_url}}/api/my_endpoint",
    headers={"Authorization": "Bearer {{token}}"},
    body={"param1": "{{var1}}", "param2": "{{var2}}"},
    module="我的模块",
    tags=["custom"],
))
```

### 2. 注册自定义模板函数

```python
from core.parser import ParameterParser

parser = ParameterParser()
# 注册自定义函数
parser.register_function("now_ms", lambda: str(int(time.time() * 1000)))
parser.register_function("sign", lambda data, key: hmac_sign(data, key))
```

### 3. 注册清理任务

```python
from core.cleaner import DataCleaner

cleaner = DataCleaner()
cleaner.register("delete_test_user", lambda user_id: delete_user(user_id), {"user_id": "10086"})
cleaner.register_api_cleanup("step_create_order", "delete_order", {"order_id": "ORD001"})

# 执行清理（逆序）
results = cleaner.run_all(context)
```

### 4. 自定义失败策略

```python
StepDefinition(
    step_id="step1",
    api_id="my_api",
    on_failure="continue",   # 失败后继续执行后续步骤
    # on_failure="stop"      # 失败后停止链路（默认）
    # on_failure="skip_next" # 跳过下一步
)
```

### 5. 前置/后置脚本

```python
StepDefinition(
    step_id="step1",
    api_id="my_api",
    pre_scripts=[
        "context.set('timestamp', int(__import__('time').time()))",
    ],
    post_scripts=[
        "print('step1 completed, order_id =', context.get('order_id'))",
    ],
)
```

---

## 项目文件结构

```
api_chain_engine/
├── README.md                      # 项目文档
├── requirements.txt               # 依赖包列表
├── main.py                        # CLI 入口 & 交互式演示
├── config.py                      # 全局配置
├── conftest.py                    # pytest 配置
├── pytest.ini                     # pytest 设置
├── core/
│   ├── __init__.py
│   ├── registry.py                # 接口注册中心
│   ├── context.py                 # 上下文管理器
│   ├── parser.py                  # 参数解析引擎（模板渲染）
│   ├── extractor.py               # 响应提取器（JSONPath/JMESPath/regex）
│   ├── assertion.py               # 断言与校验引擎
│   ├── executor.py                # 链式执行器（核心）
│   ├── tracer.py                  # 可观测性与追踪
│   └── cleaner.py                 # 数据清理器
├── models/
│   ├── __init__.py
│   ├── api_def.py                 # 接口定义模型
│   ├── step.py                    # 步骤定义模型
│   └── chain.py                   # 链路模型
├── storage/
│   ├── __init__.py
│   └── sqlite_store.py            # SQLite 持久化
├── apis/
│   ├── __init__.py
│   └── ecommerce_apis.py          # 电商示例接口（7个）
├── tests/
│   ├── __init__.py
│   ├── test_executor.py           # 执行器单元测试
│   ├── test_parser.py             # 参数解析引擎测试
│   ├── test_assertion.py          # 断言引擎测试
│   └── test_ecommerce_chain.py    # 电商链路集成测试
└── reports/                       # HTML 执行报告（自动生成）
```

---

## 示例电商接口

| 接口ID | 名称 | 方法 | 路径 | 提取变量 |
|--------|------|------|------|---------|
| A: `user_login` | 用户登录 | POST | `/api/auth/login` | `token`, `user_id` |
| B: `get_user_profile` | 用户信息 | GET | `/api/users/{{user_id}}` | `nickname`, `vip_level` |
| C: `search_product` | 搜索商品 | GET | `/api/products/search` | `product_id`, `price` |
| D: `get_product_detail` | 商品详情 | GET | `/api/products/{{product_id}}` | `stock`, `sku_id` |
| E: `create_order` | 创建订单 | POST | `/api/orders` | `order_id`, `order_no` |
| F: `pay_order` | 支付订单 | POST | `/api/orders/{{order_id}}/pay` | `pay_status`, `transaction_id` |
| G: `query_order` | 查询订单 | GET | `/api/orders/{{order_id}}` | `order_status`, `items` |

---

## 技术选型

| 组件 | 技术 | 用途 |
|------|------|------|
| HTTP 请求 | `requests` | 发起真实接口调用 |
| Mock 测试 | `requests-mock` | 单元测试拦截请求 |
| JSONPath | `jsonpath-ng` | 响应体变量提取 |
| JMESPath | `jmespath` | 响应体变量提取 |
| 控制台输出 | `rich` | 彩色报告、表格、面板 |
| 日志 | `loguru` | 结构化日志记录 |
| 数据库 | `sqlite3` | 链路模板持久化 |
| 序列化 | `json` + `pyyaml` | 数据格式转换 |
| 测试 | `pytest` + `pytest-cov` | 单元测试 + 覆盖率 |
