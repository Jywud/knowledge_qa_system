from typing import Annotated, Any, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import START, StateGraph, add_messages

from app.config import settings
from app.services.retrieval_service import hybrid_search

RAG_SYSTEM_PROMPT = """你是企业知识库问答助手。请严格依据下面提供的知识库内容回答用户问题。
- 只使用知识库内容作答，不要基于常识补充知识库中不存在的信息。
- 如果知识库内容与问题无关或不足以回答，直接说明知识库中没有相关内容，不要编造答案。
- 只有在回答中实际引用了知识库内容时才标注来源编号，例如 [来源1]；没有引用时不要输出来源标注。
- 用中文回答，保持简洁专业。

知识库内容：
{context}
"""

SUMMARY_PROMPT = """请将以下对话压缩为一段简洁摘要（不超过200字），保留：
- 用户的核心目标和意图
- 已确认的关键事实
- 已完成的操作或决定
- 待解决的问题
- 用户明确表达的偏好

已有摘要（如果有，请在此基础上合并新对话的要点）：
{old_summary}

新对话内容：
{new_messages}

请直接输出摘要内容，不要加任何前缀或解释。"""


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]
    sources: list
    kb_id: str | None
    top_k: int | None
    summary: str
    summarized_count: int


def build_llm() -> ChatOpenAI:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置，请在 backend/.env 中填写")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        streaming=True,
        temperature=0.3,
    )


def build_summary_llm() -> ChatOpenAI:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置，请在 backend/.env 中填写")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        streaming=False,
        temperature=0.1,
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


def make_summarize_node(summary_llm: ChatOpenAI):
    async def summarize_node(state: ChatState):
        messages = state["messages"]
        summarized_count = state.get("summarized_count", 0)
        recent_n = settings.max_history_messages

        old_messages = messages[summarized_count:-recent_n] if recent_n > 0 else []
        if len(old_messages) < settings.summary_batch_size:
            return {}

        old_summary = state.get("summary", "")
        new_messages_text = "\n".join(
            f"{'用户' if m.type == 'human' else '助手'}：{extract_text(m.content)}"
            for m in old_messages
        )
        prompt = SUMMARY_PROMPT.format(old_summary=old_summary, new_messages=new_messages_text)

        try:
            result = await summary_llm.ainvoke([SystemMessage(content=prompt)])
            new_summary = extract_text(result.content)
            return {
                "summary": new_summary,
                "summarized_count": summarized_count + len(old_messages),
            }
        except Exception:
            return {}

    return summarize_node


def make_chat_node(llm: ChatOpenAI):
    async def chat_node(state: ChatState):
        query = extract_text(state["messages"][-1].content)
        kb_id = state.get("kb_id")
        top_k = state.get("top_k") or settings.top_k
        if kb_id:
            docs = await hybrid_search(query, int(kb_id), top_k)
        else:
            docs = await hybrid_search(query, None, top_k)
        sources = [
            {
                "index": i + 1,
                "source": d.metadata.get("source", ""),
                "page": d.metadata.get("page", 0),
                "file_id": d.metadata.get("file_id"),
                "chunk_index": d.metadata.get("chunk_index"),
                "excerpt": d.page_content[:150].replace("\n", " ") + ("…" if len(d.page_content) > 150 else ""),
            }
            for i, d in enumerate(docs)
        ]
        context = "\n\n".join(f"[来源{i + 1}] {d.page_content}" for i, d in enumerate(docs))
        if not docs:
            context = "（知识库中暂无相关内容）"
        system = SystemMessage(content=RAG_SYSTEM_PROMPT.format(context=context))
        summary = state.get("summary", "")
        max_history = settings.max_history_messages
        history = state["messages"][-max_history:] if max_history > 0 else state["messages"]
        if summary:
            summary_msg = SystemMessage(content=f"以下是本次对话前期的摘要：\n{summary}")
            response = await llm.ainvoke([system, summary_msg, *history])
        else:
            response = await llm.ainvoke([system, *history])
        return {"messages": [response], "sources": sources}

    return chat_node


def build_graph(checkpointer: AsyncPostgresSaver):
    graph = StateGraph(ChatState)
    graph.add_node("summarize", make_summarize_node(build_summary_llm()))
    graph.add_node("chat", make_chat_node(build_llm()))
    graph.add_edge(START, "summarize")
    graph.add_edge("summarize", "chat")
    return graph.compile(checkpointer=checkpointer)
