"""
agent/utils/retry.py
带指数退避的重试装饰器 - 处理 GitHub API 限流与网络错误。
"""

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

from agent.utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# GitHub API 限流异常（避免硬依赖 PyGitHub，使用字符串匹配作为后备）
try:
    from github.GithubException import RateLimitExceededException, GithubException

    _GITHUB_EXCEPTIONS: tuple[type[Exception], ...] = (
        RateLimitExceededException,
        GithubException,
    )
except ImportError:
    _GITHUB_EXCEPTIONS = (Exception,)


def github_retry(
    max_attempts: int = 5,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
) -> Callable[[F], F]:
    """GitHub API 重试装饰器（指数退避 + 随机抖动）。

    Args:
        max_attempts: 最大重试次数（含首次调用）。
        min_wait: 最小等待秒数。
        max_wait: 最大等待秒数。

    Returns:
        装饰后的函数。

    Example::

        @github_retry(max_attempts=3)
        def upload_file():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            last_exc: Exception | None = None
            wait = min_wait

            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except _GITHUB_EXCEPTIONS as exc:
                    attempt += 1
                    last_exc = exc
                    exc_type = type(exc).__name__

                    # RateLimitExceededException 使用更长等待
                    is_rate_limit = "RateLimit" in exc_type
                    actual_wait = max_wait if is_rate_limit else wait

                    logger.warning(
                        "github_api_retry",
                        func=func.__name__,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        exc_type=exc_type,
                        wait_seconds=actual_wait,
                    )

                    if attempt >= max_attempts:
                        break

                    time.sleep(actual_wait)
                    # 指数退避
                    wait = min(wait * 2, max_wait)

            logger.error(
                "github_api_max_retries_exceeded",
                func=func.__name__,
                attempts=attempt,
            )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 0.5,
    max_wait: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """通用重试装饰器（基于 tenacity）。

    Args:
        max_attempts: 最大重试次数。
        min_wait: 最小等待秒数（随机指数退避）。
        max_wait: 最大等待秒数。
        exceptions: 需要重试的异常类型元组。

    Returns:
        装饰后的函数。
    """
    return retry(  # type: ignore[return-value]
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(min=min_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        before_sleep=lambda retry_state: logger.warning(
            "retry_attempt",
            func=retry_state.fn.__name__ if retry_state.fn else "unknown",
            attempt=retry_state.attempt_number,
            wait=retry_state.next_action.sleep if retry_state.next_action else 0,
        ),
    )
