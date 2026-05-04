# -*- coding: utf-8 -*-
"""
接口定义模型
描述一个 HTTP 接口的完整元信息，支持模板变量
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class APIDefinition:
    """
    接口定义，描述一个可复用的 HTTP 接口元信息。
    URL、Headers、Body 均支持 {{variable}} 模板语法。
    """
    api_id: str                        # 唯一标识，如 "user_login"
    name: str                          # 接口名称，如 "用户登录"
    method: str                        # HTTP 方法：GET POST PUT DELETE PATCH
    url: str                           # URL 模板，如 "{{base_url}}/api/auth/login"
    module: str = "默认模块"            # 所属模块，用于分组展示
    description: str = ""              # 接口描述
    headers: dict = field(default_factory=dict)   # 请求头模板
    params: dict = field(default_factory=dict)    # Query 参数模板
    body: dict = field(default_factory=dict)      # 请求体模板（JSON）
    form_data: dict = field(default_factory=dict) # 表单数据模板
    timeout: int = 30                  # 超时秒数
    tags: list = field(default_factory=list)      # 标签列表
    author: str = ""                   # 接口维护人
    version: str = "v1"               # 接口版本

    def __post_init__(self):
        self.method = self.method.upper()

    def to_dict(self) -> dict:
        return {
            "api_id": self.api_id,
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "module": self.module,
            "description": self.description,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
            "form_data": self.form_data,
            "timeout": self.timeout,
            "tags": self.tags,
            "author": self.author,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "APIDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
