"""Worker entrypoint: python -m app.queue.worker"""

import asyncio
import logging
from app.queue.worker import run_worker

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(run_worker())
