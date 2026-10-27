import asyncio
import sys

if __name__ == "__main__":
    import uvicorn
    from uvicorn import Config, Server

    loop_factory = None
    if sys.platform == "win32":
        # psycopg 异步驱动在 Windows 上只支持 SelectorEventLoop
        loop_factory = asyncio.SelectorEventLoop

    config = Config("app.main:app", host="0.0.0.0", port=8000)
    server = Server(config)
    asyncio.run(server.serve(), loop_factory=loop_factory)
