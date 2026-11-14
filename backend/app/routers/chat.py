import asyncio
import json
import re
from contextlib import suppress
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_db
from app.auth import get_current_user
from app.models import Chunk, Conversation, FileRecord, Message, User
from app.schemas import ChatRequest, ConversationCreate, ConversationOut, MessageOut
from app.services.rag_service import extract_text, generate_title
from app.services.settings_service import get_system_settings
from app.services.permission_service import authorization_lock, readable_kb_predicate
from app.services.conversation_scope_service import (
    conversation_kb_ids, create_scope, readable_kb_ids, require_conversation_scope,
)

router = APIRouter(prefix="/api/conversations", tags=["chat"])

_background_tasks: set[asyncio.Task] = set()


async def _verify_generation(db: AsyncSession, user_id: int, conversation_id: int, epoch: int) -> Conversation:
    await authorization_lock(db)
    conv = await db.scalar(select(Conversation).where(Conversation.id == conversation_id)
                           .execution_options(populate_existing=True))
    if not conv or conv.user_id != user_id or not conv.rbac_ready or conv.memory_epoch != epoch:
        raise HTTPException(403, "知识库权限已变更，回答已停止，请刷新后重试")
    await require_conversation_scope(db, user_id, conv)
    return conv


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await authorization_lock(db)
    scope = await create_scope(db, user.id, body.kb_id)
    conv = Conversation(
        user_id=user.id, title=body.title or "", kb_id=body.kb_id,
        kb_scope=json.dumps(scope),
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
        .where(Conversation.rbac_ready.is_(True))
        .order_by(Conversation.id.desc())
    )
    allowed = await readable_kb_ids(db, user.id)
    return [conv for conv in result.scalars().all()
            if (scope := conversation_kb_ids(conv)) and set(scope).issubset(allowed)]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id or not conv.rbac_ready:
        raise HTTPException(404, "会话不存在")
    await require_conversation_scope(db, user.id, conv)
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
    if not conv or conv.user_id != user.id or not conv.rbac_ready:
        raise HTTPException(404, "会话不存在")
    last_thread = conv.memory_thread_id

    await db.delete(conv)
    await db.commit()

    checkpointer = request.app.state.checkpointer
    threads = {last_thread} if last_thread else set()
    if hasattr(checkpointer, "alist"):
        async for checkpoint in checkpointer.alist(None, filter={"user_id": user.id, "conversation_id": conversation_id}):
            threads.add(checkpoint.config["configurable"]["thread_id"])
    for thread in threads:
        await checkpointer.adelete_thread(thread)
    return {"ok": True}


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: int,
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await authorization_lock(db)
    conv = await db.get(Conversation, conversation_id, with_for_update=True)
    if not conv or conv.user_id != user.id or not conv.rbac_ready:
        raise HTTPException(404, "会话不存在")
    if not body.content.strip():
        raise HTTPException(400, "问题不能为空")
    if "kb_id" in body.model_fields_set and body.kb_id != conv.kb_id:
        raise HTTPException(400, "会话检索范围已固定，切换范围请新建会话")
    kb_id = conv.kb_id
    scope = await require_conversation_scope(db, user.id, conv)
    chunk_count = await db.scalar(
        select(func.count(Chunk.id))
        .join(FileRecord, FileRecord.id == Chunk.file_id)
        .where(FileRecord.kb_id.in_(scope), readable_kb_predicate(FileRecord.kb_id, user.id))
    )
    if not chunk_count:
        raise HTTPException(400, "当前检索范围暂无可用文档，请联系管理员上传后再提问")
    is_first_message = not conv.title
    if is_first_message:
        conv.title = body.content[:20]
    db.add(Message(conversation_id=conversation_id, role="user", content=body.content))
    await db.commit()

    graph = request.app.state.graph
    user_id, epoch = user.id, conv.memory_epoch
    prefix = f"rbac-v1-user-{user_id}-conv-{conversation_id}-epoch-{epoch}-"
    previous_thread = conv.memory_thread_id
    thread_id = prefix + uuid4().hex
    config = {"configurable": {"thread_id": thread_id},
              "metadata": {"user_id": user_id, "conversation_id": conversation_id}}
    user_msg = HumanMessage(content=body.content)
    system_settings = await get_system_settings(db)
    top_k = system_settings.top_k
    rrf_top_n = system_settings.rrf_top_n
    top_n = system_settings.top_n
    rerank_enabled = system_settings.rerank_enabled
    min_score = system_settings.retrieval_min_score
    # 设置可能首次创建；提交并释放连接后，流生成只使用基本值快照。
    await db.commit()
    revoked = asyncio.Event()
    finished = asyncio.Event()
    stream_closed = asyncio.Event()

    async def generate_and_save_title():
        try:
            title = await generate_title(body.content)
            async with SessionLocal() as title_db:
                title_conv = await _verify_generation(title_db, user_id, conversation_id, epoch)
                title_conv.title = title
                await title_db.commit()
        except Exception:
            pass

    async def run_generation(queue: asyncio.Queue):
        full_text = ""
        title_task = (
            asyncio.create_task(generate_and_save_title()) if is_first_message else None
        )
        try:
            await queue.put({"type": "start"})
            payload = {"messages": [user_msg], "kb_id": str(kb_id) if kb_id is not None else None,
                       "kb_ids": scope, "top_k": top_k, "rrf_top_n": rrf_top_n,
                       "rerank_enabled": rerank_enabled, "top_n": top_n,
                       "retrieval_min_score": min_score, "user_id": user_id}
            # 只有原子落库后保存的指针可延续上下文；失败/撤权任务使用独立线程，不会被复用。
            if previous_thread and previous_thread.startswith(prefix):
                previous = await graph.aget_state({"configurable": {"thread_id": previous_thread}})
                values = previous.values
                payload["messages"] = list(values.get("messages", [])) + [user_msg]
                payload["summary"] = values.get("summary", "")
                payload["summarized_count"] = values.get("summarized_count", 0)
            async for chunk, _metadata in graph.astream(
                payload,
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
            grouped: dict[tuple, dict] = {}
            for source in sources:
                key = (source.get("file_id"), source.get("file_version"), source["source"])
                entry = grouped.setdefault(
                    key,
                    {
                        "source": source["source"],
                        "file_id": source.get("file_id"),
                        "file_version": source.get("file_version"),
                        "file_type": source.get("file_type", ""),
                        "kb_name": source.get("kb_name", ""),
                        "kb_id": source.get("kb_id"),
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
                            "chunk_id": source.get("chunk_id"),
                            "file_version": source.get("file_version"),
                            "chunk_index": source.get("chunk_index"),
                            "text": excerpt,
                        }
                    )
            sources = list(grouped.values())
            async with SessionLocal() as save_db:
                saved_conv = await _verify_generation(save_db, user_id, conversation_id, epoch)
                save_db.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_text,
                        sources=json.dumps(sources, ensure_ascii=False),
                    )
                )
                saved_conv.memory_thread_id = thread_id
                await save_db.commit()
            async with SessionLocal() as check_db:
                await _verify_generation(check_db, user_id, conversation_id, epoch)
            await queue.put({"type": "sources", "sources": sources})
        except Exception as exc:
            await queue.put({"type": "error", "message": exc.detail if isinstance(exc, HTTPException) else str(exc),
                             "status": exc.status_code if isinstance(exc, HTTPException) else 500})
        finally:
            if title_task:
                if revoked.is_set():
                    title_task.cancel()
                try:
                    await asyncio.wait_for(title_task, timeout=8)
                except (Exception, asyncio.CancelledError):
                    pass
            finished.set()
            if not revoked.is_set():
                await queue.put({"type": "done"})

    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(run_generation(queue))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    async def monitor_permissions():
        # 模型结束后仍可能有待发送内容，直到客户端消费结束才停止监控。
        while not (finished.is_set() and stream_closed.is_set()):
            try:
                async with SessionLocal() as check_db:
                    await _verify_generation(check_db, user_id, conversation_id, epoch)
            except Exception:
                revoked.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                # 队列中的片段不能在撤权后继续发出，未完成线程也没有可复用指针。
                while not queue.empty():
                    queue.get_nowait()
                await queue.put({"type": "error", "status": 403, "code": "permission_revoked",
                                 "message": "知识库权限已变更，回答已停止，请刷新后重试"})
                await queue.put({"type": "done"})
                break
            try:
                await asyncio.wait_for(stream_closed.wait(), timeout=1)
                if not finished.is_set():
                    await asyncio.wait_for(finished.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    monitor = asyncio.create_task(monitor_permissions())
    _background_tasks.add(monitor)
    monitor.add_done_callback(_background_tasks.discard)

    async def event_stream():
        try:
            while True:
                event = await queue.get()
                if revoked.is_set() and event["type"] not in {"error", "done"}:
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "done":
                    break
        except asyncio.CancelledError:
            pass
        finally:
            stream_closed.set()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
