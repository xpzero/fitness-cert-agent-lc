import { useEffect, useRef, useState } from "react";
import { api, sseChat } from "@/lib/api";
import { USER_ID } from "@/lib/constants";
import type { ChatMsg, ChatSession, Src } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChatInput } from "./components/ChatInput";
import { FollowUps } from "./components/FollowUps";
import { MessageList } from "./components/MessageList";

const NODE_CN: Record<string, string> = {
  rewrite_query: "改写问题", retrieve_chunks: "检索教材", guard: "检查材料",
  generate_draft: "生成回答", verify_citations: "校验引用", format_answer: "整理出处",
  refuse_answer: "转官方渠道", classify: "理解意图", qa: "问答", tutor: "导师",
};

const TUTOR_TOOL_CN: Record<string, string> = {
  qa_answer: "查教材", generate_quiz: "出题", diagnose: "学情诊断",
  plan_state: "看计划", plan_adjust: "调计划",
  chapter_accuracy: "查章节正确率", chapter_wrong_detail: "下钻错题",
  wrongbook_backlog: "查错题本", mock_trend: "查模考趋势",
};

const LS_KEY = "fca-active-chat-session";

function newSessionId(): string {
  return "chat-" + Math.random().toString(16).slice(2, 12);
}

type HistoryRow = { role: string; content: string; sources?: Src[] };

function toMsgs(rows: HistoryRow[]): ChatMsg[] {
  return rows.map((m) => ({
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    sources: m.sources || [],
  }));
}

export default function Chat() {
  const [sessionId, setSessionId] = useState(newSessionId());
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [trail, setTrail] = useState<string[]>([]);
  const boxRef = useRef<HTMLDivElement>(null);
  const scroll = () => setTimeout(() => boxRef.current?.scrollTo(0, 1e9), 50);

  async function refreshSessions() {
    try {
      const d = await api<{ sessions: ChatSession[] }>(`/chat/sessions?user_id=${USER_ID}`);
      setSessions(d.sessions || []);
    } catch {
      /* 列表拉取失败不阻塞对话 */
    }
  }

  async function openSession(id: string) {
    if (busy) return;
    setSessionId(id);
    localStorage.setItem(LS_KEY, id);
    try {
      const d = await api<{ messages: HistoryRow[] }>(
        `/chat/messages?user_id=${USER_ID}&session_id=${id}`);
      setMsgs(toMsgs(d.messages || []));
    } catch {
      setMsgs([]);
    }
    setTrail([]);
    scroll();
  }

  function newChat() {
    if (busy) return;
    const id = newSessionId();
    setSessionId(id);
    localStorage.setItem(LS_KEY, id);
    setMsgs([]);
    setTrail([]);
  }

  async function deleteSession(id: string) {
    await api(`/chat/sessions?user_id=${USER_ID}&session_id=${encodeURIComponent(id)}`,
             { method: "DELETE" }).catch(() => {});
    if (id === sessionId) {  // 删的是当前会话 → 开新的
      const nid = newSessionId();
      setSessionId(nid);
      localStorage.setItem(LS_KEY, nid);
      setMsgs([]);
    }
    refreshSessions();
  }

  // 挂载：拉会话列表；恢复上次活跃会话（刷新/重启不丢）
  useEffect(() => {
    (async () => {
      await refreshSessions();
      const last = localStorage.getItem(LS_KEY);
      if (!last) return;
      try {
        const d = await api<{ messages: HistoryRow[] }>(
          `/chat/messages?user_id=${USER_ID}&session_id=${last}`);
        if (d.messages?.length) {
          setSessionId(last);
          setMsgs(toMsgs(d.messages));
          scroll();
        }
      } catch {
        /* 上次会话取不回就当新会话 */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function send(text?: string) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "" }]);
    setBusy(true);
    setTrail([]);
    scroll();  // 用户消息即滚底，不等首个 token
    const path: string[] = [];
    let final = "", sources: Src[] = [];
    await sseChat(q, (evt) => {
      if (evt.event === "node_end") { path.push(NODE_CN[evt.node] || evt.node); setTrail([...path]); }
      if (evt.event === "tutor_step") {
        path.push(TUTOR_TOOL_CN[evt.tool] || evt.tool);
        setTrail([...path]);
      }
      if (evt.event === "token") {
        final += evt.text;
        setMsgs((m) => { const c = [...m]; c[c.length - 1] = { role: "assistant", content: final, sources: [] }; return c; });
        scroll();
      }
      if (evt.event === "final_replace") final = evt.text;
      if (evt.event === "done") { final = evt.final; sources = evt.sources || []; }
    }, USER_ID, sessionId).catch((e) => { final = `（请求失败：${e.message}）`; });
    setMsgs((m) => { const c = [...m]; c[c.length - 1] = { role: "assistant", content: final, sources }; return c; });
    setBusy(false);
    scroll();
    localStorage.setItem(LS_KEY, sessionId);
    refreshSessions();
  }

  const last = msgs[msgs.length - 1];
  // 注意转 boolean：sources.length 为 0 时 && 链短路成数字 0，会被 React 渲染出来
  const showFollow = !busy && last?.role === "assistant" && !!last.sources?.length
    && !last.content.includes("无法溯源");

  return (
    <div className="flex h-full min-h-0 gap-5">
      {/* 会话列表：服务端持久化，刷新可恢复 */}
      <div className="flex w-60 shrink-0 flex-col min-h-0">
        <button onClick={newChat} disabled={busy}
          className="w-full rounded-xl bg-primary px-4 py-2.5 text-[13.5px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50">
          ＋ 新对话
        </button>
        <div className="mt-3 min-h-0 flex-1 space-y-1 overflow-y-auto rounded-xl border border-border bg-card p-2">
          {sessions.length === 0 && (
            <div className="px-2 py-3 text-[11.5px] leading-relaxed text-muted-foreground">
              还没有历史对话
              <br />
              答案带教材出处 · 不可溯源即拒答
              <br />（右键会话可删除）
            </div>
          )}
          {sessions.map((s) => (
            <div key={s.session_id} className="group relative"
                 onContextMenu={(e) => {
                   e.preventDefault();
                   const ok = confirm(`删除会话「${s.title || "未命名"}」？(${s.n} 条消息)`);
                   if (ok) deleteSession(s.session_id);
                 }}>
            <button onClick={() => openSession(s.session_id)} disabled={busy}
              className={cn(
                "block w-full rounded-lg px-2.5 py-2 text-left text-[12.5px] transition-colors",
                s.session_id === sessionId
                  ? "bg-secondary font-semibold text-secondary-foreground"
                  : "text-foreground/80 hover:bg-muted",
              )}>
              <div className="truncate">{s.title || "（未命名会话）"}</div>
              <div className="mt-0.5 text-[10.5px] text-muted-foreground">
                {s.n} 条 · {new Date(s.last_at).toLocaleString("zh-CN", {
                  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
                })}
              </div>
            </button>
            </div>
          ))}
        </div>
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <MessageList msgs={msgs} busy={busy} trail={trail} boxRef={boxRef} />
        <ChatInput input={input} setInput={setInput} busy={busy} onSend={() => send()} />
        {showFollow && <FollowUps onSend={send} />}
      </div>
    </div>
  );
}
