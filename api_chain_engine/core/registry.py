# -*- coding: utf-8 -*-
"""
接口注册中心
支持按模块、标签查询，提供树形展示，是整个引擎的接口元数据管理入口。
"""
from typing import Optional
from loguru import logger
from models.api_def import APIDefinition


class APIRegistry:
    """
    接口注册中心（单例模式）
    负责注册、查询、管理所有 APIDefinition。
    """

    _instance: Optional["APIRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._apis: dict[str, APIDefinition] = {}
        return cls._instance

    # ------------------------------------------------------------------ #
    #  注册
    # ------------------------------------------------------------------ #

    def register(self, api: APIDefinition) -> None:
        """注册单个接口，重复注册时覆盖并发出警告"""
        if api.api_id in self._apis:
            logger.warning(f"[Registry] 接口已存在，将覆盖注册: {api.api_id}")
        self._apis[api.api_id] = api
        logger.debug(f"[Registry] 注册接口: [{api.module}] {api.api_id} - {api.name}")

    def register_batch(self, apis: list[APIDefinition]) -> None:
        """批量注册接口"""
        for api in apis:
            self.register(api)
        logger.info(f"[Registry] 批量注册完成，共 {len(apis)} 个接口")

    # ------------------------------------------------------------------ #
    #  查询
    # ------------------------------------------------------------------ #

    def get(self, api_id: str) -> APIDefinition:
        """按 api_id 获取接口定义，不存在时抛出异常"""
        if api_id not in self._apis:
            raise KeyError(f"[Registry] 接口未注册: '{api_id}'，请先调用 register()")
        return self._apis[api_id]

    def list_all(self) -> list[APIDefinition]:
        """返回所有已注册接口"""
        return list(self._apis.values())

    def list_by_module(self, module: str) -> list[APIDefinition]:
        """按模块名过滤接口"""
        return [api for api in self._apis.values() if api.module == module]

    def list_by_tag(self, tag: str) -> list[APIDefinition]:
        """按标签过滤接口"""
        return [api for api in self._apis.values() if tag in api.tags]

    def search(self, keyword: str) -> list[APIDefinition]:
        """关键词模糊搜索（匹配 api_id / name / description / tags）"""
        kw = keyword.lower()
        results = []
        for api in self._apis.values():
            if (
                kw in api.api_id.lower()
                or kw in api.name.lower()
                or kw in api.description.lower()
                or any(kw in t.lower() for t in api.tags)
            ):
                results.append(api)
        return results

    def exists(self, api_id: str) -> bool:
        return api_id in self._apis

    # ------------------------------------------------------------------ #
    #  展示
    # ------------------------------------------------------------------ #

    def show_tree(self) -> str:
        """按模块生成树形结构字符串"""
        modules: dict[str, list[APIDefinition]] = {}
        for api in self._apis.values():
            modules.setdefault(api.module, []).append(api)

        lines = ["📦 接口注册中心"]
        module_list = sorted(modules.keys())
        for i, module in enumerate(module_list):
            is_last_module = i == len(module_list) - 1
            branch = "└──" if is_last_module else "├──"
            lines.append(f"  {branch} 📁 {module}")
            apis = modules[module]
            for j, api in enumerate(apis):
                is_last_api = j == len(apis) - 1
                api_branch = "    └──" if is_last_module else "│   └──" if is_last_api else "│   ├──"
                if is_last_module:
                    api_branch = "    └──" if is_last_api else "    ├──"
                method_color = {
                    "GET": "🟢", "POST": "🔵", "PUT": "🟡",
                    "DELETE": "🔴", "PATCH": "🟠"
                }.get(api.method, "⚪")
                lines.append(f"  {api_branch} {method_color} [{api.method:6s}] {api.api_id} - {api.name}")
        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有注册（测试用）"""
        self._apis.clear()

    def __len__(self) -> int:
        return len(self._apis)

    def __repr__(self) -> str:
        return f"<APIRegistry apis={len(self._apis)}>"
