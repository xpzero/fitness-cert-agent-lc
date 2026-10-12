"""会话端点：/chat（SSE 流式）+ 历史会话列表/取回 与健康检查。"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langgraph.graph import END
from sqlalchemy import text as sql_text

from app.api.deps import get_main_graph, sse, trace_chat
from app.api.schemas import ChatRequest
from app.db import database
from app.prompts.qa import REFUSAL_TEXT_PREFIX

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "phase": "P3-agent-upgrade",
        "ui": "http://localhost:5173/（前端独立部署，API 经 vite 代理）",
        "try": ["POST /chat", "GET /kb/documents"],
    }


def _session_history(user_id: str, session_id: str, limit: int = 12) -> list[dict]:
    """取会话内最近几条消息（多轮记忆的来源）：按时间升序返回 [{role, content}]。"""
    with database.engine.connect() as conn:
        rows = conn.execute(sql_text(
            "SELECT role, content FROM ("
            "  SELECT id, role, content FROM chat_messages "
            "  WHERE user_id = :u AND session_id = :s ORDER BY id DESC LIMIT :n"
            ") t ORDER BY id ASC"),
            {"u": user_id, "s": session_id, "n": limit}).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


@router.post("/chat")
async def chat(req: ChatRequest):
    """SSE：start(含 session_id) / node_end / token(qa 生成阶段) / tutor_step(导师工具步骤) / done(含 final)。"""
    thread_id = f"{req.user_id}-{uuid.uuid4().hex[:8]}"
    session_id = req.session_id or ("chat-" + uuid.uuid4().hex[:10])
    # 多轮记忆：会话内历史注入主图 messages（路由取最后一条，qa/tutor 取最近几轮）
    history = _session_history(req.user_id, session_id) if req.session_id else []
    initial_state = {
        "messages": history + [{"role": "user", "content": req.message}],
        "user_id": req.user_id,
    }

    async def sse_event_stream():
        yield sse({"event": "start", "thread_id": thread_id, "session_id": session_id})
        final_text = ""
        sources: list = []
        tokens_streamed = False
        # updates=节点完成事件；custom=qa 子图 token / tutor·diagnosis 的工具步骤（自动冒泡到父图）
        async for stream_mode, payload in get_main_graph().astream(
            initial_state, stream_mode=["updates", "custom"]
        ):
            if stream_mode == "custom":
                if isinstance(payload, dict) and payload.get("token"):
                    tokens_streamed = True
                    yield sse({"event": "token", "text": payload["token"]})
                elif isinstance(payload, dict) and payload.get("step"):
                    step = payload["step"]
                    yield sse({"event": "tutor_step", "tool": step.get("tool"),
                               "thought": str(step.get("thought", ""))[:80]})
                continue
            if not isinstance(payload, dict):
                continue
            for node, update in payload.items():
                if node in (END, "__end__"):
                    continue
                yield sse({"event": "node_end", "node": node})
                reply = (
                    update.get("reply") if isinstance(update, dict) else None
                )
                if reply and reply.get("text"):
                    final_text = reply["text"]
                    sources = reply.get("sources", [])
        if not tokens_streamed:  # 拒答/错误路径无 token 流，整段补发
            for i in range(0, len(final_text), 120):
                yield sse({"event": "token", "text": final_text[i : i + 120]})
        elif final_text and not final_text.startswith(REFUSAL_TEXT_PREFIX):
            # 流式后 format_answer 的引用重排：发增量修正事件（前端整体替换）
            yield sse({"event": "final_replace", "text": final_text})
        yield sse({"event": "done", "text": final_text, "sources": sources})
        trace_chat(req.user_id, req.message, thread_id, final_text)
        _persist(req.user_id, session_id, req.message, final_text, sources)

    return StreamingResponse(sse_event_stream(), media_type="text/event-stream")


def _persist(user_id: str, session_id: str, question: str,
             answer: str, sources: list) -> None:
    """对话历史落库（会话恢复用）。旁路能力：失败不影响回答主链路。"""
    try:
        with database.engine.begin() as conn:
            conn.execute(sql_text(
                "INSERT INTO chat_messages (user_id, session_id, role, content, sources) "
                "VALUES (:u, :s, 'user', :c, CAST('[]' AS jsonb))"),
                {"u": user_id, "s": session_id, "c": question})
            conn.execute(sql_text(
                "INSERT INTO chat_messages (user_id, session_id, role, content, sources) "
                "VALUES (:u, :s, 'assistant', :c, CAST(:src AS jsonb))"),
                {"u": user_id, "s": session_id, "c": answer,
                 "src": json.dumps(sources or [], ensure_ascii=False)})
    except Exception:  # noqa: BLE001
        pass


@router.get("/chat/sessions")
def chat_sessions(user_id: str = "dev") -> dict:
    """会话列表（最近活跃优先，≤50）。标题取每个会话的首条用户消息。"""
    with database.engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT s.session_id, s.last_at, s.n, t.content AS title
            FROM (SELECT session_id, max(created_at) AS last_at, count(*) AS n
                  FROM chat_messages WHERE user_id = :u
                  GROUP BY session_id
                  ORDER BY last_at DESC LIMIT 50) s
            JOIN LATERAL (SELECT content FROM chat_messages c
                          WHERE c.user_id = :u AND c.session_id = s.session_id
                            AND c.role = 'user'
                          ORDER BY c.id LIMIT 1) t ON true
            ORDER BY s.last_at DESC
        """), {"u": user_id}).mappings().all()
    return {"sessions": [dict(r) for r in rows]}


@router.delete("/chat/sessions")
def chat_delete_session(user_id: str, session_id: str) -> dict:
    """删除会话（连同消息）。当前活跃会话被删时前端应开新会话。"""
    with database.engine.begin() as conn:
        n = conn.execute(sql_text(
            "DELETE FROM chat_messages WHERE user_id = :u AND session_id = :s"),
            {"u": user_id, "s": session_id}).rowcount
    return {"deleted": n, "session_id": session_id}


@router.get("/chat/messages")
def chat_history(user_id: str, session_id: str) -> dict:
    """取回一个会话的全部消息（刷新恢复）。"""
    with database.engine.connect() as conn:
        rows = conn.execute(sql_text(
            "SELECT role, content, sources FROM chat_messages "
            "WHERE user_id = :u AND session_id = :s ORDER BY id"),
            {"u": user_id, "s": session_id}).mappings().all()
    return {"messages": [dict(r) for r in rows]}
