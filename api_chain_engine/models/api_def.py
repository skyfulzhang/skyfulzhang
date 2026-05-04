# -*- coding: utf-8 -*-
"""
接口定义模型
描述一个 HTTP 接口的元数据，支持模板变量
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class APIDefinition:
    """
    接口定义：描述一个 HTTP 接口的完整元信息。
    url / headers / params / body 中均可使用 {{变量名}} 模板语法。
    """
    api_id: str                                    # 唯一标识，如 "user_login"
    name: str                                      # 接口中文名称
    method: str                                    # HTTP 方法: GET POST PUT DELETE PATCH
    url: str                                       # 接口地址，支持模板: {{base_url}}/api/login
    module: str = "默认模块"                         # 所属模块，用于注册中心分组展示
    description: str = ""                          # 接口描述
    tags: List[str] = field(default_factory=list)  # 标签列表
    headers: Dict[str, Any] = field(default_factory=dict)   # 请求头模板
    params: Dict[str, Any] = field(default_factory=dict)    # Query 参数模板
    body: Optional[Dict[str, Any]] = field(default_factory=dict)  # 请求体模板
    timeout: int = 30                              # 超时秒数
    content_type: str = "application/json"         # 请求 Content-Type
    auth_required: bool = True                     # 是否需要鉴权

    def __post_init__(self):
        self.method = self.method.upper()
        if self.method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
            raise ValueError(f"不支持的 HTTP 方法: {self.method}")

    def to_dict(self) -> dict:
        return {
            "api_id": self.api_id,
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "module": self.module,
            "description": self.description,
            "tags": self.tags,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
            "timeout": self.timeout,
            "content_type": self.content_type,
            "auth_required": self.auth_required,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "APIDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
