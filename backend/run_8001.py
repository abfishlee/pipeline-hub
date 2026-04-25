"""Temporary launcher on port 8001 — port 8000 has stale socket."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
        timeout_graceful_shutdown=10,
        log_level="info",
    )


if __name__ == "__main__":
    main()
