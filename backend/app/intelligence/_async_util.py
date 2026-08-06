"""Utility for running async functions from sync legacy interfaces."""
import asyncio
import concurrent.futures


def run_async(coro):
    """Run a coroutine from a synchronous context.

    Handles both cases: no event loop running (simple run_until_complete)
    and event loop running (submit to thread pool).
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return loop.run_until_complete(coro)
