from typing import Annotated, Any, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import START, StateGraph, add_messages

from app.config import settings
from app.services.document_service import get_vectorstore
from app.services.retrieval_service import hybrid_search

RAG_SYSTEM_PROMPT = """你是企业知识库问答助手。请根据下面提供的知识库内容回答用户问题。
- 如果知识库内容包含答案，请在回答中标注来源编号，例如 [来源1]。
- 如果知识库内容不足以回答，请明确说明，并基于常识谨慎回答。
- 用中文回答，保持简洁专业。

知识库内容：
{context}
"""


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    sources: list
    kb_id: str | None
    top_k: int | None


def build_llm() -> ChatOpenAI:
    if not settings.ark_api_key:
        raise RuntimeError("ARK_API_KEY 未配置，请在 backend/.env 中填写")
    return ChatOpenAI(
        model=settings.ark_model,
        api_key=settings.ark_api_key,
        base_url=settings.ark_base_url,
        streaming=True,
        temperature=0.3,
    )


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content or "")


def make_chat_node(llm: ChatOpenAI, vectorstore):
    async def chat_node(state: ChatState):
        query = extract_text(state["messages"][-1].content)
        kb_id = state.get("kb_id")
        top_k = state.get("top_k") or settings.top_k
        if kb_id:
            docs = await hybrid_search(query, int(kb_id), top_k, vectorstore)
        else:
            docs = await hybrid_search(query, None, top_k, vectorstore)
        sources = [
            {
                "index": i + 1,
                "source": d.metadata.get("source", ""),
                "page": d.metadata.get("page", 0),
            }
            for i, d in enumerate(docs)
        ]
        context = "\n\n".join(f"[来源{i + 1}] {d.page_content}" for i, d in enumerate(docs))
        if not docs:
            context = "（知识库中暂无相关内容）"
        system = SystemMessage(content=RAG_SYSTEM_PROMPT.format(context=context))
        response = await llm.ainvoke([system, *state["messages"]])
        return {"messages": [response], "sources": sources}

    return chat_node


def build_graph(checkpointer: AsyncPostgresSaver):
    graph = StateGraph(ChatState)
    graph.add_node("chat", make_chat_node(build_llm(), get_vectorstore()))
    graph.add_edge(START, "chat")
    return graph.compile(checkpointer=checkpointer)
