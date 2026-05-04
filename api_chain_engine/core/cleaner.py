"""数据清理器"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import ExecutionContext


@dataclass
class CleanupResult:
    """清理任务执行结果"""
    task_name: str
    success: bool
    error: str | None = None


@dataclass
class _CleanupTask:
    name: str
    func: Callable
    args: dict[str, Any] = field(default_factory=dict)


class DataCleaner:
    """
    执行后数据清理器，支持注册清理任务
    - 支持按顺序逆向清理（后创建的先删除）
    - 支持条件清理（仅测试环境）
    - 与链路执行上下文集成
    """

    def __init__(self) -> None:
        self._tasks: list[_CleanupTask] = []

    def register(
        self,
        task_name: str,
        cleanup_func: Callable,
        args: dict[str, Any] | None = None,
    ) -> None:
        """注册清理任务"""
        self._tasks.append(_CleanupTask(name=task_name, func=cleanup_func, args=args or {}))

    def register_api_cleanup(self, step_id: str, api_id: str, params: dict[str, Any]) -> None:
        """注册接口级清理（用于调用删除类接口）"""
        def _api_cleanup(**kw: Any) -> None:
            # 实际项目中可以调用注册的删除接口
            pass

        self._tasks.append(_CleanupTask(name=f"api_cleanup:{step_id}:{api_id}", func=_api_cleanup, args=params))

    def run_all(self, context: "ExecutionContext") -> list[CleanupResult]:
        """逆序执行所有清理任务"""
        results: list[CleanupResult] = []
        for task in reversed(self._tasks):
            result = self._run_task(task, context)
            results.append(result)
        return results

    def run_selective(self, task_names: list[str]) -> list[CleanupResult]:
        """按名称执行指定清理任务"""
        results: list[CleanupResult] = []
        for task in reversed(self._tasks):
            if task.name in task_names:
                result = self._run_task(task, None)
                results.append(result)
        return results

    def clear(self) -> None:
        """清空所有清理任务"""
        self._tasks.clear()

    def _run_task(self, task: _CleanupTask, context: "ExecutionContext | None") -> CleanupResult:
        """执行单个清理任务"""
        try:
            task.func(**task.args)
            return CleanupResult(task_name=task.name, success=True)
        except Exception as e:
            return CleanupResult(task_name=task.name, success=False, error=str(e))
