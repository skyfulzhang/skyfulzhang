"""接口定义模型"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class APIDefinition:
    """接口定义模型，描述一个 HTTP 接口的完整信息"""
    api_id: str                        # 唯一标识，如 "user_login"
    name: str                          # 接口名称
    method: str                        # HTTP 方法：GET / POST / PUT / DELETE 等
    url: str                           # 支持模板变量，如 "{{base_url}}/api/login"
    headers: dict[str, Any] = field(default_factory=dict)   # 请求头模板
    params: dict[str, Any] = field(default_factory=dict)    # Query 参数模板
    body: dict[str, Any] = field(default_factory=dict)      # 请求体模板（支持嵌套模板变量）
    timeout: int = 30                  # 超时秒数
    description: str = ""             # 接口描述
    module: str = ""                  # 所属模块（如 "用户模块"、"订单模块"）
    tags: list[str] = field(default_factory=list)           # 标签

    def __post_init__(self) -> None:
        self.method = self.method.upper()
