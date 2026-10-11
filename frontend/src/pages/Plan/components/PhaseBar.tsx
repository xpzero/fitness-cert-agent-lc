import type { Overview } from "@/lib/types";
import { cn } from "@/lib/utils";

/** 备考阶段进度条：已完成 / 进行中 / 待开始 */
export function PhaseBar({ ov, curIdx }: { ov: Overview; curIdx: number }) {
  return (
    <div className="mt-3 flex gap-2.5">
      {(ov.phases || []).map((ph, i) => (
        <div key={i} className={cn("flex-1 rounded-xl border p-3 text-[12.5px]",
          i === curIdx ? "border-primary bg-secondary shadow-[0_0_0_3px_#FFE0CC]" : i < curIdx ? "bg-accent opacity-65" : "bg-accent")}>
          <div className="text-[13px] font-bold">{i === curIdx ? "🟠" : i < curIdx ? "✅" : "⬜"} {ph.name}</div>
          <div className="my-1 text-[11px] text-muted-foreground">{ph.weeks}</div>
          <div className="text-[11px] text-muted-foreground">{(ph.chapters || []).slice(0, 2).join("、") || "—"}</div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className={cn("h-full rounded-full", i === curIdx ? "bg-primary" : "bg-[var(--success)]")}
              style={{ width: i === curIdx ? `${ov.current_phase?._progress || 0}%` : i < curIdx ? "100%" : "0%" }} />
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {i === curIdx ? `进行中 · 第 ${ov.current_phase?._cur_week || 1}/${ov.current_phase?._span || 1} 周`
              : i < curIdx ? "✅ 已完成" : "待开始"}
          </div>
        </div>
      ))}
    </div>
  );
}
