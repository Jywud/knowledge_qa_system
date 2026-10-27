"""检索质量回归用例。

依赖本地 PostgreSQL + Ollama，默认跳过；设置 RUN_RETRIEVAL_TESTS=1 启用。
kb_id 需按实际环境调整。
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RETRIEVAL_TESTS") != "1",
    reason="需要本地 PostgreSQL + Ollama，设置 RUN_RETRIEVAL_TESTS=1 运行",
)

RETRIEVAL_CASES = [
    {"kb_id": 1, "query": "陪诊师考试有哪些注意事项", "expect_source": "陪诊师考试.md"},
    {"kb_id": 1, "query": "量子物理中的薛定谔方程是什么", "expect_source": None},
]


@pytest.mark.parametrize("case", RETRIEVAL_CASES)
async def test_retrieval_case(case):
    from app.services.retrieval_service import hybrid_search

    docs = await hybrid_search(case["query"], case["kb_id"], 5)
    if case["expect_source"] is None:
        assert docs == []
    else:
        assert any(doc.metadata["source"] == case["expect_source"] for doc in docs)
