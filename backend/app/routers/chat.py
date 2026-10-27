import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_db
from app.auth import get_current_user
from app.models import Chunk, Conversation, FileRecord, Message, User
from app.schemas import ChatRequest, ConversationCreate, ConversationOut, MessageOut
from app.services.rag_service import extract_text
from app.services.settings_service import get_system_settings

router = APIRouter(prefix="/api/conversations", tags=["chat"])

_background_tasks: set[asyncio.Task] = set()


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(
        user_id=user.id, title=body.title or "", kb_id=body.kb_id
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.id.desc())
    )
    return result.scalars().all()


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    if conv.kb_id is None:
        raise HTTPException(400, "会话未绑定知识库，无法问答")
    chunk_count = await db.scalar(
        select(func.count(Chunk.id))
        .join(FileRecord, FileRecord.id == Chunk.file_id)
        .where(FileRecord.kb_id == conv.kb_id)
    )
    if not chunk_count:
        raise HTTPException(400, "知识库暂无可用文档，无法问答")
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    )
    return result.scalars().all()


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")

    await db.delete(conv)
    await db.commit()

    checkpointer = request.app.state.checkpointer
    await checkpointer.adelete_thread(f"user-{user.id}-conv-{conversation_id}")
    return {"ok": True}


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: int,
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    if not conv.title:
        conv.title = body.content[:20]
    if conv.kb_id is None and body.kb_id:
        conv.kb_id = body.kb_id
    db.add(Message(conversation_id=conversation_id, role="user", content=body.content))
    await db.commit()

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": f"user-{conv.user_id}-conv-{conv.id}"}}
    user_msg = HumanMessage(content=body.content)
    system_settings = await get_system_settings(db)

    async def run_generation(queue: asyncio.Queue):
        full_text = ""
        try:
            await queue.put({"type": "start"})
            async for chunk, _metadata in graph.astream(
                {
                    "messages": [user_msg],
                    "kb_id": str(conv.kb_id) if conv.kb_id else None,
                    "top_k": system_settings.top_k,
                },
                config=config,
                stream_mode="messages",
            ):
                if not isinstance(chunk, AIMessageChunk):
                    continue
                text = extract_text(chunk.content)
                if text:
                    full_text += text
                    await queue.put({"type": "token", "content": text})
            state = await graph.aget_state(config)
            sources = state.values.get("sources", [])
            cited = {int(num) for num in re.findall(r"\[来源(\d+)\]", full_text)}
            if cited:
                sources = [source for source in sources if source["index"] in cited]
            else:
                sources = []
            grouped: dict[str, dict] = {}
            for source in sources:
                entry = grouped.setdefault(
                    source["source"],
                    {
                        "source": source["source"],
                        "file_type": source.get("file_type", ""),
                        "kb_name": source.get("kb_name", ""),
                        "count": 0,
                        "excerpts": [],
                    },
                )
                entry["count"] += 1
                excerpt = source.get("excerpt", "")
                if excerpt and all(item["index"] != source["index"] for item in entry["excerpts"]):
                    entry["excerpts"].append(
                        {
                            "index": source["index"],
                            "file_id": source.get("file_id"),
                            "chunk_index": source.get("chunk_index"),
                            "text": excerpt,
                        }
                    )
            sources = list(grouped.values())
            async with SessionLocal() as save_db:
                save_db.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_text,
                        sources=json.dumps(sources, ensure_ascii=False),
                    )
                )
                await save_db.commit()
            await queue.put({"type": "sources", "sources": sources})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put({"type": "done"})

    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(run_generation(queue))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    async def event_stream():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
