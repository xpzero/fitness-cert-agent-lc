import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { CoachMessage, Question } from "@/lib/types";
import { cn } from "@/lib/utils";

const PHASE_LABEL: Record<string, string> = {
  probe: "诊断误解", hint: "逐步提示", explain: "完整讲解", verify: "变式检验", done: "完成",
};

type VariantQ = Question & { answer?: string };

/** 苏格拉底讲题教练（W4）：错题卡片内的对话面板，变式题结果写回 SM-2 */
export function CoachPanel({ userId, questionId }: { userId: string; questionId: string }) {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [msgs, setMsgs] = useState<CoachMessage[]>([]);
  const [variant, setVariant] = useState<VariantQ | null>(null);
  const [pick, setPick] = useState("");
  const [verdict, setVerdict] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  // 刷新恢复：该题有进行中的教练会话则直接续上（消息/阶段/未作答变式题）
  useEffect(() => {
    (async () => {
      try {
        const d = await api<{ session_id?: string; messages?: CoachMessage[];
          phase?: string; variant?: VariantQ | null }>(
          `/quiz/coach/active?user_id=${userId}&question_id=${questionId}`);
        if (d.session_id) {
          setOpen(true);
          setSessionId(d.session_id);
          setMsgs(d.messages || []);
          if (d.variant) setVariant(d.variant);
        }
      } catch {
        /* 恢复失败就走正常开场 */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId]);

  async function start() {
    setBusy(true);
    try {
      const d = await api<{ session_id: string; greeting: string; phase: string }>(
        "/quiz/coach/start", { method: "POST", body: JSON.stringify({ user_id: userId, question_id: questionId }) });
      setOpen(true);
      setSessionId(d.session_id);
      setMsgs([{ role: "coach", content: d.greeting }]);
      setVariant(null); setPick(""); setVerdict(""); setText("");
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!text.trim() || busy) return;
    setBusy(true);
    const saying = text;
    setText("");
    setMsgs((m) => [...m, { role: "user", content: saying }]);
    try {
      const d = await api<{ reply: string; phase: string; variant: VariantQ | null }>(
        "/quiz/coach/message", { method: "POST", body: JSON.stringify({ session_id: sessionId, text: saying }) });
      setMsgs((m) => [...m, { role: "coach", content: d.reply }]);
      if (d.variant) setVariant(d.variant);
    } finally {
      setBusy(false);
    }
  }

  async function answer(k: string) {
    if (busy || verdict) return;
    setPick(k);
    setBusy(true);
    try {
      const d = await api<{ correct: boolean; sm2_updated: boolean; closing: string }>(
        "/quiz/coach/answer", { method: "POST", body: JSON.stringify({ session_id: sessionId, answer: k }) });
      setVerdict(d.closing);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="mt-3 rounded-xl border border-dashed border-amber-400 bg-amber-50 p-3 text-center">
        <Button size="sm" variant="outline" disabled={busy} onClick={start}>
          🎓 教练带我过这题（苏格拉底式，不直接给答案）
        </Button>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50/60 p-3">
      <div className="mb-2 flex items-center justify-between text-[12px] text-amber-700">
        <b>🎓 讲题教练</b>
        <span>阶段：{PHASE_LABEL[phaseOf(msgs, variant)] || "…"}</span>
      </div>
      <div className="max-h-64 space-y-2 overflow-auto rounded-lg bg-white p-2.5">
        {msgs.map((m, i) => (
          <div key={i} className={cn("text-[13px]", m.role === "user" ? "text-right" : "")}>
            <span className={cn(
              "inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5 text-left",
              m.role === "user" ? "bg-secondary" : "bg-amber-100")}>
              {m.content}
            </span>
          </div>
        ))}
        {busy && <div className="text-[11px] text-muted-foreground">▍教练思考中…</div>}
      </div>
      {variant && !verdict && (
        <div className="mt-2 rounded-lg border border-amber-300 bg-white p-2.5">
          <b className="text-[13px]">📝 变式题（作答后写回复习排程）</b>
          <div className="mt-1 text-[13px]">{variant.stem}</div>
          {Object.keys(variant.options || {}).sort().map((k) => (
            <div key={k} onClick={() => answer(k)}
              className={cn("mt-1.5 cursor-pointer rounded-lg border-[1.5px] p-2 text-[13px]",
                pick === k ? "border-primary bg-secondary" : "border-input bg-white")}>
              <b className="mr-1.5">{k}.</b>{variant.options[k]}
            </div>
          ))}
        </div>
      )}
      {verdict && (
        <div className="mt-2 rounded-lg border border-[var(--success)] bg-green-50 p-2.5 text-[13px]">{verdict}</div>
      )}
      {!variant && !verdict && (
        <div className="mt-2 flex gap-2">
          <Input value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="说说你的想法…" />
          <Button size="sm" disabled={busy} onClick={send}>发送</Button>
        </div>
      )}
    </div>
  );
}

function phaseOf(_msgs: CoachMessage[], variant: VariantQ | null): string {
  return variant ? "verify" : "probe";
}
