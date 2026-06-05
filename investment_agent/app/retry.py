"""简单的异步重试工具 — 用于瞬态 DB 错误恢复。"""

import asyncio
import functools
import logging

_log = logging.getLogger(__name__)


def with_retry(max_retries: int = 3, base_delay: float = 0.1):
    """异步函数重试装饰器，指数退避。

    仅捕获 aiosqlite 操作错误（OperationalError / DatabaseError），
    其他异常直接传播。
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    error_type = type(e).__name__
                    # 仅重试瞬态 DB 错误
                    if error_type in ("OperationalError", "DatabaseError", "TimeoutError"):
                        last_error = e
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt)
                            _log.debug(
                                "DB retry %d/%d after %.2fs: %s",
                                attempt + 1, max_retries, delay, e,
                            )
                            await asyncio.sleep(delay)
                        else:
                            _log.warning(
                                "DB retry exhausted after %d attempts: %s",
                                max_retries, e,
                            )
                    else:
                        raise
            if last_error:
                raise last_error

        return wrapper

    return decorator
