import type { Overview } from "@/lib/types";

/** 计划概览头部：考试倒计时渐变卡 + 覆盖率/累计刷题/模考趋势统计卡 */
export function OverviewHeader({ ov }: { ov: Overview }) {
  return (
    <div className="flex gap-4">
      <div className="flex-[1.2] rounded-xl bg-gradient-to-br from-primary to-amber-500 p-5 text-white">
        <div className="flex items-baseline gap-2.5">
          <span className="text-[38px] font-extrabold">{ov.days_left ?? 0}</span>
          <span className="text-[13px] opacity-90">天后考试</span>
          <span className="ml-auto text-[13px] opacity-90">{ov.exam_date} · NSCA-CPT（四大证）</span>
        </div>
        <div className="mt-1.5 text-xs opacity-90">
          剩余有效学习日 {(ov.days_left ?? 0) - (ov.weekend_days ?? 0)} 天（周末 x{ov.weekend_days ?? 0}）·
          每周 {ov.weekly_hours ?? 10} 小时 · 累计刷题 {ov.answered} 题
        </div>
        <div className="mt-2.5 flex gap-2">
          <button className="cursor-pointer rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-primary"
            onClick={() => document.getElementById("plan-form-anchor")?.scrollIntoView({ behavior: "smooth" })}>
            📋 重新生成计划
          </button>
          <button className="cursor-pointer rounded-md bg-white/20 px-3 py-1.5 text-xs font-semibold text-white"
            onClick={() => window.print()}>
            🖨 导出打印版
          </button>
        </div>
      </div>
      <div className="flex flex-1 gap-3">
        <div className="flex-1 rounded-xl border border-border bg-accent px-4 py-3">
          <div className="text-[22px] font-bold text-primary">{ov.coverage!.covered}/{ov.coverage!.total}</div>
          <div className="mt-0.5 text-xs text-secondary-foreground">考点已覆盖</div>
          <div className="text-[11px] text-muted-foreground">题目覆盖 {ov.coverage!.pct}%</div>
        </div>
        <div className="flex-1 rounded-xl border border-border bg-accent px-4 py-3">
          <div className="text-[22px] font-bold text-primary">{ov.answered}</div>
          <div className="mt-0.5 text-xs text-secondary-foreground">累计刷题</div>
          <div className="text-[11px] text-muted-foreground">连续 {ov.streak} 天 🔥</div>
        </div>
        <div className="flex-1 rounded-xl border border-border bg-accent px-4 py-3">
          <div className="text-[22px] font-bold text-primary">
            {ov.mock_trend && ov.mock_trend.length >= 2 ? `${ov.mock_trend[1]}→${ov.mock_trend[0]}` : (ov.mock_trend?.[0] ?? "—")}
          </div>
          <div className="mt-0.5 text-xs text-secondary-foreground">
            模考分趋势{ov.trend_delta != null && (ov.trend_delta >= 0 ? ` 近 2 次 ↑${ov.trend_delta}` : ` 近 2 次 ↓${Math.abs(ov.trend_delta)}`)}
          </div>
        </div>
      </div>
    </div>
  );
}
