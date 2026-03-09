"""
agent/utils/logger.py
结构化日志模块 - 支持 JSON（生产环境）和 text（开发环境）两种格式。
使用 structlog 实现结构化日志输出。
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_log_level(
    logger: Any,  # noqa: ANN401
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """向日志事件字典中注入日志级别字段。"""
    if method == "warning":
        event_dict["level"] = "WARNING"
    else:
        event_dict["level"] = method.upper()
    return event_dict


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """配置全局 structlog 日志。

    Args:
        log_level: 日志级别（DEBUG / INFO / WARNING / ERROR / CRITICAL）。
        log_format: 输出格式，"json" 用于生产，"text" 用于开发调试。
    """
    # 共享处理器链 (pre-chain)
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        _add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # 同时配置标准库 logging（让第三方库的日志也能被 structlog 捕获）
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """获取命名 structlog 日志记录器。

    Args:
        name: 日志记录器名称，通常传入 ``__name__``。

    Returns:
        structlog.BoundLogger: 绑定了 logger 名称的日志记录器。
    """
    return structlog.get_logger(name)
