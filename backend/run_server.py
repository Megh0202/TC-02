from __future__ import annotations

import asyncio
import sys

import uvicorn


def main() -> None:
    # On Windows, Playwright needs a Proactor loop for subprocess support.
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
