import type { Overview } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

/** 本周任务按天打卡（每 2 个任务归入一天）+ 模考联动记录 */
export function WeekTasks({ ov, onCheckin }: {
  ov: Overview;
  onCheckin: (no: number, done: boolean) => void;
}) {
  const monday = new Date(); monday.setDate(monday.getDate() - monday.getDay() + 1);
  const buckets: Record<string, [number, string][]> = Object.fromEntries(DAYS.map((d) => [d, []]));
  (ov.week_tasks || []).forEach((t, i) => buckets[DAYS[Math.min(Math.floor(i / 2), 6)]].push([i, t]));

  return (
    <div className="mt-3 flex gap-3.5">
      <div className="flex-[1.4] rounded-xl border border-input bg-accent p-4">
        <div className="text-sm font-bold">本周任务（第 {ov.week_no} 周）</div>
        {DAYS.map((d, di) => buckets[d].length > 0 && (
          <div key={d} className="mt-2 flex gap-2.5">
            <div className="w-16 shrink-0 border-r-2 border-border pr-2.5 text-center text-[11px] text-muted-foreground">
              <b className="block text-[15px] text-primary">{d}</b>
              {(() => { const dt = new Date(monday); dt.setDate(monday.getDate() + di);
                return `${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`; })()}
            </div>
            <div className="flex-1">
              {buckets[d].map(([i, t]) => {
                const on = ov.checkins?.[String(i + 1)] || ov.checkins?.[i + 1];
                const hot = t.includes("【模考后加练】");
                return (
                  <div key={i} className="flex cursor-pointer items-center gap-2 py-1.5 text-[12.5px]" onClick={() => onCheckin(i + 1, !on)}>
                    <span className={cn("flex h-[17px] w-[17px] items-center justify-center rounded-[5px] border-[1.5px] text-[11px] text-white",
                      on ? "border-[var(--success)] bg-[var(--success)]" : "border-slate-300")}>{on ? "✓" : ""}</span>
                    <span className={cn(on && "text-muted-foreground line-through", hot && !on && "text-primary")}>
                      {hot ? "🗓 " + t.replace("【模考后加练】", "") : t}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 rounded-xl border border-input bg-accent p-4">
        <div className="text-sm font-bold">模考联动记录</div>
        {(ov.adjustments || []).length ? (
          (ov.adjustments || []).slice(-3).map((a, i) => (
            <div key={i} className="mt-1.5 rounded-lg border border-border border-l-4 border-l-[var(--success)] bg-green-50 px-3 py-2 text-xs">
              <b>{a.date} · 模考 {a.mock_score} 分</b>
              <div className="text-muted-foreground">{String(a.action).slice(0, 66)}</div>
            </div>
          ))
        ) : (
          <div className="mt-1.5 rounded-lg border border-border bg-muted px-3 py-2.5 text-xs text-muted-foreground">
            暂无记录——完成一次「全真模考」后，系统会按薄弱考点自动调整本计划
          </div>
        )}
      </div>
    </div>
  );
}
