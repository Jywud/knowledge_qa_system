import pytest

from app.services.rag_service import generate_title


@pytest.mark.asyncio
async def test_generate_title_strips_wrapping_quotes(monkeypatch):
    class FakeResult:
        content = "  “如何配置知识库”  "

    class FakeLLM:
        async def ainvoke(self, messages):
            return FakeResult()

    monkeypatch.setattr("app.services.rag_service.build_summary_llm", lambda: FakeLLM())
    title = await generate_title("请介绍一下知识库怎么配置")
    assert title == "如何配置知识库"
