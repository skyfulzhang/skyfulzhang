"""接口注册中心"""
from __future__ import annotations
from typing import Any
from models.api_def import APIDefinition


class APIRegistry:
    """接口注册中心，支持模块化管理"""

    def __init__(self) -> None:
        self._apis: dict[str, APIDefinition] = {}

    def register(self, api: APIDefinition) -> None:
        """注册单个接口"""
        self._apis[api.api_id] = api

    def register_batch(self, apis: list[APIDefinition]) -> None:
        """批量注册接口"""
        for api in apis:
            self.register(api)

    def get(self, api_id: str) -> APIDefinition:
        """获取接口定义，不存在则抛出异常"""
        if api_id not in self._apis:
            raise KeyError(f"接口 '{api_id}' 未注册，已注册接口: {list(self._apis.keys())}")
        return self._apis[api_id]

    def list_all(self) -> list[APIDefinition]:
        """列出所有接口"""
        return list(self._apis.values())

    def list_by_module(self, module: str) -> list[APIDefinition]:
        """按模块列出接口"""
        return [api for api in self._apis.values() if api.module == module]

    def list_by_tag(self, tag: str) -> list[APIDefinition]:
        """按标签列出接口"""
        return [api for api in self._apis.values() if tag in api.tags]

    def search(self, keyword: str) -> list[APIDefinition]:
        """关键字搜索接口（名称、描述、api_id、模块）"""
        keyword_lower = keyword.lower()
        results = []
        for api in self._apis.values():
            if (keyword_lower in api.api_id.lower()
                    or keyword_lower in api.name.lower()
                    or keyword_lower in api.description.lower()
                    or keyword_lower in api.module.lower()):
                results.append(api)
        return results

    def show_tree(self) -> str:
        """按模块展示接口树形结构"""
        modules: dict[str, list[APIDefinition]] = {}
        for api in self._apis.values():
            module = api.module or "未分类"
            modules.setdefault(module, []).append(api)

        lines = ["接口注册中心\n" + "=" * 40]
        for module, apis in sorted(modules.items()):
            lines.append(f"📦 {module}")
            for i, api in enumerate(apis):
                prefix = "└──" if i == len(apis) - 1 else "├──"
                lines.append(f"   {prefix} [{api.method:6s}] {api.api_id}: {api.name}")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._apis)

    def __contains__(self, api_id: str) -> bool:
        return api_id in self._apis
