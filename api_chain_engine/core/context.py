"""上下文管理器"""
from __future__ import annotations
from typing import Any
import copy


class ExecutionContext:
    """链路执行上下文，管理变量作用域"""

    SCOPE_GLOBAL = "global"
    SCOPE_CHAIN = "chain"
    SCOPE_STEP = "step"

    def __init__(self, global_variables: dict[str, Any] | None = None) -> None:
        self._global: dict[str, Any] = dict(global_variables or {})
        self._chain: dict[str, Any] = {}
        self._step: dict[str, Any] = {}
        # 用于步骤间数据共享的步骤结果存储
        self._step_results: dict[str, Any] = {}

    def set(self, key: str, value: Any, scope: str = "chain") -> None:
        """设置变量"""
        if scope == self.SCOPE_GLOBAL:
            self._global[key] = value
        elif scope == self.SCOPE_STEP:
            self._step[key] = value
        else:
            self._chain[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取变量，优先级：step > chain > global"""
        if key in self._step:
            return self._step[key]
        if key in self._chain:
            return self._chain[key]
        if key in self._global:
            return self._global[key]
        return default

    def merge(self, data: dict[str, Any], scope: str = "chain") -> None:
        """批量设置变量"""
        for key, value in data.items():
            self.set(key, value, scope)

    def snapshot(self) -> dict[str, Any]:
        """返回当前上下文快照（合并所有作用域）"""
        result = {}
        result.update(self._global)
        result.update(self._chain)
        result.update(self._step)
        return copy.deepcopy(result)

    def resolve_template(self, template: Any) -> Any:
        """委托给 parser 解析模板（避免循环依赖，在 executor 中注入 parser）"""
        # 此方法由 executor 在运行时替换
        return template

    def clear_step_scope(self) -> None:
        """清除步骤级变量"""
        self._step.clear()

    def set_step_result(self, step_id: str, data: dict[str, Any]) -> None:
        """保存步骤结果到上下文（用于 step_id.field 引用）"""
        self._step_results[step_id] = data
        # 同时写入 chain 作用域方便直接引用
        for key, value in data.items():
            self._chain[key] = value

    def get_step_result(self, step_id: str) -> dict[str, Any]:
        """获取某步骤的提取结果"""
        return self._step_results.get(step_id, {})

    def to_dict(self) -> dict[str, Any]:
        """返回完整上下文字典"""
        return {
            "global": copy.deepcopy(self._global),
            "chain": copy.deepcopy(self._chain),
            "step": copy.deepcopy(self._step),
        }

    def __repr__(self) -> str:
        return f"ExecutionContext(global={len(self._global)}, chain={len(self._chain)}, step={len(self._step)})"
