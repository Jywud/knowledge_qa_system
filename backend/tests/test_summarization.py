import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from app.config import settings
from app.services.rag_service import make_summarize_node, ChatState


def _messages(n: int) -> list:
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(HumanMessage(content=f"用户消息 {i + 1}"))
        else:
            msgs.append(AIMessage(content=f"助手回复 {i + 1}"))
    return msgs


@pytest.mark.asyncio
async def test_no_summary_under_threshold():
    summary_llm = MagicMock()
    node = make_summarize_node(summary_llm)
    state: ChatState = {
        "messages": _messages(15),
        "sources": [],
        "kb_id": None,
        "top_k": None,
        "summary": "",
        "summarized_count": 0,
    }
    result = await node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_summary_triggered_at_threshold():
    mock_result = MagicMock()
    mock_result.content = "用户在讨论测试话题"
    summary_llm = AsyncMock()
    summary_llm.ainvoke.return_value = mock_result
    node = make_summarize_node(summary_llm)
    state: ChatState = {
        "messages": _messages(30),
        "sources": [],
        "kb_id": None,
        "top_k": None,
        "summary": "",
        "summarized_count": 0,
    }
    result = await node(state)
    assert result["summary"] == "用户在讨论测试话题"
    assert result["summarized_count"] == 10
    summary_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_summary_incremental_merge():
    mock_result = MagicMock()
    mock_result.content = "合并后的新摘要"
    summary_llm = AsyncMock()
    summary_llm.ainvoke.return_value = mock_result
    node = make_summarize_node(summary_llm)
    state: ChatState = {
        "messages": _messages(50),
        "sources": [],
        "kb_id": None,
        "top_k": None,
        "summary": "旧摘要",
        "summarized_count": 10,
    }
    result = await node(state)
    assert result["summary"] == "合并后的新摘要"
    assert result["summarized_count"] == 30
    call_args = summary_llm.ainvoke.call_args
    prompt_text = call_args[0][0][0].content
    assert "旧摘要" in prompt_text


@pytest.mark.asyncio
async def test_summary_failure_fallback():
    summary_llm = AsyncMock()
    summary_llm.ainvoke.side_effect = Exception("LLM timeout")
    node = make_summarize_node(summary_llm)
    state: ChatState = {
        "messages": _messages(30),
        "sources": [],
        "kb_id": None,
        "top_k": None,
        "summary": "",
        "summarized_count": 0,
    }
    result = await node(state)
    assert result == {}
