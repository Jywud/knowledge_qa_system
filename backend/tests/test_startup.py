import runpy
from pathlib import Path
from unittest.mock import AsyncMock


async def test_startup_reindex_failure_is_logged_and_contained(test_db, monkeypatch, caplog):
    from app import main
    monkeypatch.setattr(main, "SessionLocal", test_db)
    monkeypatch.setattr(main, "reindex_missing_embeddings", AsyncMock(side_effect=RuntimeError("isolated unavailable")))
    await main._reindex_on_startup()
    assert "继续启动" in caplog.text


def test_run_entry_uses_only_explicit_trusted_proxies(monkeypatch):
    import uvicorn
    configs = []
    class Server:
        def __init__(self, config):
            configs.append(config)
        async def serve(self):
            pass
    monkeypatch.setattr(uvicorn, "Server", Server)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "run.py"), run_name="__main__")
    assert configs[0].proxy_headers is True
    assert configs[0].forwarded_allow_ips == "127.0.0.1,::1"
