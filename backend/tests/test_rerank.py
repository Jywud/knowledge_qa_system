"""Rerank 精排链路：融合保留条数、重排顺序与失败降级。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from app.services import rerank_service, retrieval_service


def _doc(index: int) -> Document:
    return Document(
        page_content=f"内容{index}",
        metadata={"chunk_id": str(index), "file_id": "1", "chunk_index": str(index), "file_version": 1},
    )


def _stub_legs(monkeypatch, vector, keyword):
    monkeypatch.setattr(retrieval_service, "get_embeddings", lambda: SimpleNamespace(
        aembed_query=AsyncMock(return_value=[0.1])))
    monkeypatch.setattr(retrieval_service, "_vector_search", AsyncMock(return_value=vector))
    monkeypatch.setattr(retrieval_service, "_fts_search", AsyncMock(return_value=keyword))


async def test_rerank_disabled_keeps_rrf_top_n(test_db, monkeypatch):
    # 向量路 [0,1,2,3]、关键词路 [0,4]：doc0 双路计入排第一，doc1 与 doc4 同分按 key 稳定排序
    _stub_legs(monkeypatch, [_doc(i) for i in range(4)], [_doc(0), _doc(4)])
    rerank = AsyncMock()
    monkeypatch.setattr(retrieval_service, "rerank_documents", rerank)

    docs = await retrieval_service.hybrid_search(
        "问题", 1, 4, rrf_top_n=3, rerank_enabled=False, top_n=1, user_id=1)

    assert [d.metadata["chunk_id"] for d in docs] == ["0", "1", "4"]
    rerank.assert_not_awaited()


async def test_rerank_reorders_fused_candidates(test_db, monkeypatch):
    _stub_legs(monkeypatch, [_doc(i) for i in range(4)], [_doc(4), _doc(5)])
    # 重排服务收到的下标对应送入的候选池顺序，返回按相关性降序的 (下标, 分数)
    rerank = AsyncMock(return_value=[(2, 0.95), (0, 0.8)])
    monkeypatch.setattr(retrieval_service, "rerank_documents", rerank)

    docs = await retrieval_service.hybrid_search(
        "问题", 1, 4, rrf_top_n=3, rerank_enabled=True, top_n=2, user_id=1)

    # 融合保留 3 条候选（顺序 0,4,1），重排返回的下标对应候选池位置：2→doc1、0→doc0，取前 2 条
    assert len(rerank.await_args.args[1]) == 3
    assert [d.metadata["chunk_id"] for d in docs] == ["1", "0"]


async def test_rerank_failure_degrades_to_fused_order(test_db, monkeypatch):
    _stub_legs(monkeypatch, [_doc(i) for i in range(4)], [_doc(0), _doc(4)])
    monkeypatch.setattr(retrieval_service, "rerank_documents",
                        AsyncMock(side_effect=RuntimeError("重排服务不可用")))

    docs = await retrieval_service.hybrid_search(
        "问题", 1, 4, rrf_top_n=3, rerank_enabled=True, top_n=2, user_id=1)

    assert [d.metadata["chunk_id"] for d in docs] == ["0", "1"]


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"output": {"results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.4},
        ]}}


class _FakeClient:
    captured = {}

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, json=None, headers=None):
        _FakeClient.captured = {"url": url, "json": json, "headers": headers}
        return _FakeResponse()


async def test_rerank_client_calls_dashscope(test_db, monkeypatch):
    monkeypatch.setattr(rerank_service.settings, "rerank_provider", "dashscope")
    monkeypatch.setattr(rerank_service.settings, "rerank_api_key", "test-key")
    monkeypatch.setattr(rerank_service.settings, "rerank_model", "gte-rerank-v2")
    monkeypatch.setattr(rerank_service.settings, "rerank_base_url", "https://dashscope.example/")
    monkeypatch.setattr(rerank_service.httpx, "AsyncClient", _FakeClient)

    result = await rerank_service.rerank_documents("问题", ["甲", "乙"], 1)

    assert result == [(1, 0.9)]
    captured = _FakeClient.captured
    assert captured["url"] == "https://dashscope.example/api/v1/services/rerank/text-rerank/text-rerank"
    assert captured["json"]["model"] == "gte-rerank-v2"
    assert captured["json"]["input"] == {"query": "问题", "documents": ["甲", "乙"]}
    assert captured["json"]["parameters"] == {"return_documents": False, "top_n": 1}
    assert captured["headers"]["Authorization"] == "Bearer test-key"


async def test_rerank_client_requires_provider(test_db, monkeypatch):
    monkeypatch.setattr(rerank_service.settings, "rerank_provider", "none")
    with pytest.raises(RuntimeError):
        await rerank_service.rerank_documents("问题", ["甲"], 1)
