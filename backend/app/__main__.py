"""
Run the SchemeSetu API:  python -m app [--host 0.0.0.0] [--port 8000] [--reload]

Equivalent to `uvicorn app.main:app`, but sets the selector event loop on
Windows before uvicorn creates its loop (async psycopg cannot use Windows'
default ProactorEventLoop). On Linux/macOS/Docker either command works.
"""

import argparse

from app.database.connection import use_selector_event_loop_on_windows


def main() -> None:
    from app.core.config import settings

    parser = argparse.ArgumentParser(prog="python -m app")
    parser.add_argument("--host", default=settings.BACKEND_HOST)
    parser.add_argument("--port", type=int, default=settings.BACKEND_PORT)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    use_selector_event_loop_on_windows()
    import uvicorn
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, loop="asyncio")


if __name__ == "__main__":
    main()
