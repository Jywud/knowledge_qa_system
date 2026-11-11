import asyncio
import sys

if __name__ == "__main__":
    import uvicorn
    from uvicorn import Config, Server
    from app.config import settings

    loop_factory = None
    if sys.platform == "win32":
        # psycopg 异步驱动在 Windows 上只支持 SelectorEventLoop
        loop_factory = asyncio.SelectorEventLoop

    config = Config(
        "app.main:app", host="0.0.0.0", port=8000,
        proxy_headers=True, forwarded_allow_ips=settings.trusted_proxy_ips,
    )
    server = Server(config)
    asyncio.run(server.serve(), loop_factory=loop_factory)
