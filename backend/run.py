"""Local development launcher.

용도: Windows 로컬에서 `python run.py` 로 uvicorn 기동 시 psycopg async 가
요구하는 `SelectorEventLoop` 정책을 미리 설정한다. (psycopg 는 Windows 의
기본 `ProactorEventLoop` 에서 동작하지 않음 — psycopg 공식 제약.)

운영(Linux/Docker)에서는 이 launcher 를 쓰지 않는다 — 기본 asyncio loop 가
selector 기반이라 문제 없음. `Dockerfile` 의 CMD 는 직접 uvicorn 호출.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # psycopg async 호환을 위한 사전 설정 — uvicorn 의 asyncio.run 보다 먼저 적용되어야 함.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        timeout_graceful_shutdown=10,
        log_level="info",
    )


if __name__ == "__main__":
    main()
