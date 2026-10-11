import type { ReactNode } from "react";

function MetricCard({ value, label, sub }: { value: ReactNode; label: string; sub?: string }) {
  return (
    <div className="flex-1 rounded-xl border border-border bg-accent px-4 py-3">
      <div className="text-2xl font-bold text-primary">{value}</div>
      <div className="mt-0.5 text-xs text-secondary-foreground">{label}</div>
      {sub && <div className="text-[11px] text-orange-800">{sub}</div>}
    </div>
  );
}

/** 顶部指标卡：文档数 / Chunks / 已验证题目 / 库级 Recall（数字来自全库汇总，非当前页） */
export function MetricCards({ total, indexed, totalChunks, verified, libRecall }: {
  total: number;
  indexed: number;
  totalChunks: number;
  verified: string;
  libRecall: string;
}) {
  return (
    <div className="flex gap-3.5">
      <MetricCard value={total} label="文档" sub={`${indexed} 已索引`} />
      <MetricCard value={totalChunks} label="Chunks" />
      <MetricCard value={verified} label="已验证题目" />
      <MetricCard value={libRecall} label="库级 Recall@5" sub="最近评测" />
    </div>
  );
}
