import asyncio
import functools
import logging
import random
from typing import Callable, Tuple, Type

logger = logging.getLogger("pipeline.retry")


def retry(
    max_attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e} — retry in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)

        return wrapper

    return decorator
