import type { EvalRes } from "@/lib/types";
import { cn } from "@/lib/utils";

/** 单文档召回评测结果：loading / Recall@5 / MRR@5 / 未命中明细 */
export function EvalPanel({ panel }: { panel: EvalRes | "loading" | null }) {
  return (
    <div className="flex-1 rounded-xl border border-input bg-accent p-3.5">
      <div className="text-sm font-bold">📊 单文档召回评测 <span className="text-[11px] font-normal text-muted-foreground">（点击表格「📊 评测」后显示）</span></div>
      {panel === "loading" ? (
        <div className="py-10 text-center text-xs text-muted-foreground">⏳ 采样 → 生成问题 → 检索评测（约 1-2 分钟）…</div>
      ) : panel?.ok ? (
        <>
          <div className="flex gap-2.5">
            <div className="flex-1 rounded-lg border p-2 text-center">
              <div className={cn("text-lg font-bold", (panel.recall5 ?? 0) >= 0.75 ? "text-[var(--success)]" : "text-amber-600")}>{panel.recall5}</div>
              <div className="text-[11px] text-muted-foreground">Recall@5</div>
            </div>
            <div className="flex-1 rounded-lg border p-2 text-center"><div className="text-lg font-bold text-amber-600">{panel.mrr5}</div><div className="text-[11px] text-muted-foreground">MRR@5</div></div>
            <div className="flex-1 rounded-lg border p-2 text-center"><div className="text-lg font-bold">{panel.samples}</div><div className="text-[11px] text-muted-foreground">样本题</div></div>
            <div className="flex-1 rounded-lg border p-2 text-center"><div className="text-lg font-bold">{panel.misses!.length}</div><div className="text-[11px] text-muted-foreground">未命中</div></div>
          </div>
          {panel.misses!.map((m, i) => (
            <div key={i} className="mt-1.5 rounded-lg border-l-4 border-l-destructive bg-red-50 px-3 py-2 text-xs">
              <b>❌ {m.query.slice(0, 44)}</b>
              <div className="text-muted-foreground">期望 …{m.expected.slice(-12)} ｜ 实际 top3：{m.got_top3.join("、")}</div>
            </div>
          ))}
          {panel.misses!.length === 0 && (
            <div className="mt-1.5 rounded-lg border border-border border-l-4 border-l-[var(--success)] bg-green-50 px-3 py-2 text-xs"><b>✅ 全部命中</b></div>
          )}
        </>
      ) : (
        <div className="py-10 text-center text-xs text-slate-300">尚未评测</div>
      )}
    </div>
  );
}
