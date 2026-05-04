# -*- coding: utf-8 -*-
"""
执行上下文管理器
管理链路执行过程中的变量作用域（global / chain / step），
支持模板变量解析委托、快照导出，是参数依赖传递的核心。
"""
import copy
from typing import Any, Optional
from loguru import logger


SCOPE_GLOBAL = "global"
SCOPE_CHAIN = "chain"
SCOPE_STEP = "step"


class ExecutionContext:
    """
    三层变量作用域：
      global  - 全局变量（base_url、env 等），整个进程生命周期
      chain   - 链路级变量（token、user_id 等），链路执行期间有效
      step    - 步骤级变量，每步执行后清空
    查询优先级: step > chain > global
    """

    def __init__(self, global_variables: Optional[dict] = None):
        self._global: dict[str, Any] = dict(global_variables or {})
        self._chain: dict[str, Any] = {}
        self._step: dict[str, Any] = {}
        self._step_responses: dict[str, Any] = {}   # 存储每步的原始响应体，供 step_id.field 引用
        logger.debug(f"[Context] 初始化上下文，全局变量: {list(self._global.keys())}")

    # ------------------------------------------------------------------ #
    #  写入
    # ------------------------------------------------------------------ #

    def set(self, key: str, value: Any, scope: str = SCOPE_CHAIN) -> None:
        """设置变量到指定作用域"""
        if scope == SCOPE_GLOBAL:
            self._global[key] = value
        elif scope == SCOPE_CHAIN:
            self._chain[key] = value
        elif scope == SCOPE_STEP:
            self._step[key] = value
        else:
            raise ValueError(f"未知作用域: {scope}，可选: global | chain | step")
        logger.debug(f"[Context] set [{scope}] {key} = {repr(value)[:80]}")

    def merge(self, data: dict, scope: str = SCOPE_CHAIN) -> None:
        """批量合并变量到指定作用域"""
        for k, v in data.items():
            self.set(k, v, scope)

    def set_step_response(self, step_id: str, response_body: Any) -> None:
        """保存步骤响应体，供后续步骤通过 step_id.field 引用"""
        self._step_responses[step_id] = response_body

    # ------------------------------------------------------------------ #
    #  读取
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        """按 step > chain > global 优先级查找变量"""
        for store in (self._step, self._chain, self._global):
            if key in store:
                return store[key]
        return default

    def get_step_response(self, step_id: str) -> Any:
        return self._step_responses.get(step_id)

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def all_vars(self) -> dict:
        """返回合并后的所有变量（step 覆盖 chain 覆盖 global）"""
        merged = {}
        merged.update(self._global)
        merged.update(self._chain)
        merged.update(self._step)
        return merged

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def clear_step_scope(self) -> None:
        """清空步骤级变量（每步执行结束后调用）"""
        self._step.clear()

    def snapshot(self) -> dict:
        """返回当前上下文快照（深拷贝，避免引用污染）"""
        return {
            "global": copy.deepcopy(self._global),
            "chain": copy.deepcopy(self._chain),
            "step": copy.deepcopy(self._step),
        }

    def to_dict(self) -> dict:
        """返回扁平化的所有变量（用于日志展示）"""
        return self.all_vars()

    def __repr__(self) -> str:
        return (
            f"<ExecutionContext "
            f"global={len(self._global)} "
            f"chain={len(self._chain)} "
            f"step={len(self._step)}>"
        )
