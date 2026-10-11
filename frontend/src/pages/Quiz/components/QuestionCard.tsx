import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Question, QuizResult } from "@/lib/types";
import { cn } from "@/lib/utils";

type ResultRow = QuizResult["results"][number];
type SourceRef = { chunk_id: string; title: string; page_no: number; content: string };

/** 教材依据折叠区：题干引用的表格/原文都在源 chunk 里，按需展开 */
function SourceBlock({ qid }: { qid: string }) {
  const [open, setOpen] = useState(false);
  const [sources, setSources] = useState<SourceRef[] | null>(null);

  useEffect(() => {
    if (!open || sources) return;
    api<{ sources: SourceRef[] }>(`/quiz/questions/${qid}/sources`)
      .then((d) => setSources(d.sources))
      .catch(() => setSources([]));
  }, [open, qid, sources]);

  return (
    <div className="mt-2.5">
      <button onClick={() => setOpen(!open)}
        className="cursor-pointer text-[12px] font-semibold text-primary hover:underline">
        {open ? "▾" : "▸"} 📖 查看教材依据（含表格原文）
      </button>
      {open && (sources === null
        ? <div className="mt-1.5 text-xs text-muted-foreground">加载中…</div>
        : sources.length === 0
          ? <div className="mt-1.5 text-xs text-muted-foreground">（未找到依据材料）</div>
          : sources.map((s) => (
            <div key={s.chunk_id} className="mt-1.5 rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-xs">
              <b className="font-semibold text-secondary-foreground">{s.title} · P{s.page_no}</b>
              <div className="mt-1 leading-6 text-foreground/90">{s.content}</div>
            </div>
          )))}
    </div>
  );
}

/** 当前题目卡片：题干、选项着色反馈、溯源讲题、上下题切换 */
export function QuestionCard({ q, sel, corr, rr, explain, idx, total, onPick, onPrev, onNext }: {
  q: Question;
  sel: Set<string>;
  corr: Set<string> | null;
  rr?: ResultRow;
  explain: string;
  idx: number;
  total: number;
  onPick: (k: string) => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="mt-3 rounded-xl border border-input bg-white p-5">
      <div className="mb-3.5 text-[15px] font-semibold leading-7">{q.stem}</div>
      {Object.keys(q.options || {}).sort().map((k) => {
        let cls = "border-input bg-white";
        if (rr) {
          if (corr!.has(k)) cls = "border-[var(--success)] bg-green-50";
          else if (sel.has(k)) cls = "border-destructive bg-red-50";
        } else if (sel.has(k)) cls = "border-primary bg-secondary";
        return (
          <div key={k} onClick={() => onPick(k)}
            className={cn("mb-2 flex cursor-pointer items-start gap-2.5 rounded-lg border-[1.5px] p-2.5 text-[13.5px]", cls)}>
            <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-[1.5px] text-xs",
              rr && corr!.has(k) ? "border-[var(--success)] bg-[var(--success)] text-white"
              : rr && sel.has(k) ? "border-destructive bg-destructive text-white"
              : sel.has(k) ? "border-primary bg-primary text-white" : "border-slate-300 text-muted-foreground")}>{k}</span>
            {q.options[k]}
            {rr && corr!.has(k) && <span className="ml-auto text-xs text-[var(--success)]">{sel.has(k) ? "✅ 正确且选中" : "✅ 正确答案（漏选）"}</span>}
            {rr && !corr!.has(k) && sel.has(k) && <span className="ml-auto text-xs text-destructive">❌ 你的错选</span>}
          </div>
        );
      })}
      <SourceBlock qid={q.id} />
      {rr && (
        <div className="mt-3 rounded-lg border border-l-4 border-l-[var(--success)] border-green-200 bg-green-50 p-3.5 text-[13px]">
          <div className="mb-1.5">
            <Badge variant={rr.correct ? "ok" : "bad"}>{rr.correct ? "✅ 答对" : `❌ 答错 · ${rr.detail}`}</Badge>
            <span className="ml-1.5 rounded-md bg-orange-100 px-2 py-0.5 text-[11px] text-orange-700">历史 {rr.history?.[1] ?? 0}/{rr.history?.[0] ?? 0} 次答对</span>
          </div>
          <b>溯源讲题：</b>{explain}
          <div className="mt-1 text-[11px] text-muted-foreground">
            📖 依据 {rr.source_chunk_ids?.map((c) => c.slice(-14)).join("、")} ｜ 错题已入 SM-2（明天 → 3 天后 → 8 天后）
          </div>
        </div>
      )}
      <div className="mt-3 flex justify-between">
        <Button variant="outline" disabled={idx === 0} onClick={onPrev}>← 上一题</Button>
        <Button disabled={idx === total - 1} onClick={onNext}>下一题 →</Button>
      </div>
    </div>
  );
}
