# -*- coding: utf-8 -*-
"""
接口定义模型
描述一个 HTTP 接口的完整元数据，支持模板变量
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class APIDefinition:
    """
    接口定义模型

    Attributes:
        api_id:      唯一标识，如 "user_login"
        name:        接口名称，如 "用户登录"
        method:      HTTP 方法: GET | POST | PUT | DELETE | PATCH
        url:         URL 支持模板变量，如 "{{base_url}}/api/login"
        headers:     请求头模板，支持变量，如 {"Authorization": "Bearer {{token}}"}
        params:      Query 参数模板
        body:        请求体模板（支持嵌套模板变量）
        timeout:     超时秒数
        description: 接口描述
        module:      所属模块，如 "用户模块"、"订单模块"
        tags:        标签列表
        retry:       失败重试次数
    """
    api_id: str
    name: str
    method: str
    url: str
    headers: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 30
    description: str = ""
    module: str = "默认模块"
    tags: List[str] = field(default_factory=list)
    retry: int = 0

    def __post_init__(self):
        self.method = self.method.upper()
        if self.method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
            raise ValueError(f"不支���的 HTTP 方法: {self.method}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_id": self.api_id,
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
            "timeout": self.timeout,
            "description": self.description,
            "module": self.module,
            "tags": self.tags,
            "retry": self.retry,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "APIDefinition":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
