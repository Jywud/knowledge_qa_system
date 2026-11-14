"""向量召回相似度阈值（retrieval_min_score）的参数传递与默认回退。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.services import retrieval_service


def _fake_db_capture():
    fake_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))

    class Session:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *args):
            pass

    return fake_db, Session


async def test_vector_search_applies_min_score(monkeypatch):
    fake_db, Session = _fake_db_capture()
    monkeypatch.setattr("app.database.SessionLocal", Session)

    await retrieval_service._vector_search([0.1], 1, 5, user_id=1, min_score=0.7)

    _statement, params = fake_db.execute.await_args.args
    assert params["max_distance"] == pytest.approx(0.3)


async def test_vector_search_defaults_to_env_min_score(monkeypatch):
    fake_db, Session = _fake_db_capture()
    monkeypatch.setattr("app.database.SessionLocal", Session)

    await retrieval_service._vector_search([0.1], 1, 5, user_id=1)

    _statement, params = fake_db.execute.await_args.args
    assert params["max_distance"] == pytest.approx(1 - settings.retrieval_min_score)


async def test_hybrid_search_forwards_min_score(monkeypatch):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(return_value=[0.1])))
    vector = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval_service, "_vector_search", vector)
    monkeypatch.setattr(retrieval_service, "_fts_search", AsyncMock(return_value=[]))

    docs = await retrieval_service.hybrid_search("问题", 1, 5, min_score=0.8, user_id=1)

    assert docs == []  # 向量零命中保守返回空
    assert vector.await_args.kwargs["min_score"] == 0.8
