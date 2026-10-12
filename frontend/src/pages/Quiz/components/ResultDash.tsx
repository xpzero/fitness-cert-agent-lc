import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { USER_ID } from "@/lib/constants";
import type { QuizResult } from "@/lib/types";
import { DiagnosisPanel } from "./DiagnosisPanel";

/** 交卷后成绩面板：得分环图、薄弱考点、SM-2 安排与计划联动提示 */
export function ResultDash({ r, onWrong }: { r: QuizResult; onWrong: () => void }) {
  const ok = r.report.score >= 60;
  return (
    <div className="mt-3 flex gap-4 rounded-xl border border-input bg-white p-4">
      <div className="flex h-[120px] w-[120px] items-center justify-center rounded-full"
        style={{ background: `conic-gradient(${ok ? "#2563eb" : "#DC2626"} 0 ${r.report.score}%, #dbeafe ${r.report.score}% 100%)` }}>
        <div className="flex h-[88px] w-[88px] flex-col items-center justify-center rounded-full bg-white">
          <b className="text-[22px]" style={{ color: ok ? "#2563eb" : "#DC2626" }}>{r.report.score}</b>
          <span className="text-[11px] text-muted-foreground">得分 / 100</span>
        </div>
      </div>
      <div className="flex-1">
        {r.report.mode === "mock" && (
          <div className="mb-2">
            <Badge variant={ok ? "ok" : "bad"}>{ok ? "已及格" : "未及格"}（60 分线）</Badge>
            <Badge variant="info" className="ml-1.5">模考通过概率参考 {Math.round((r.report.pass_probability || 0) * 100)}%</Badge>
          </div>
        )}
        {r.weak_points.map((w, i) => (
          <div key={i} className="mb-1 flex items-center gap-2 text-[12.5px]">
            <span className="w-28 truncate">{w.chapter}</span>
            <div className="h-2 w-40 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${(w.correct / Math.max(1, w.total)) * 100}%` }} />
            </div>
            <span>{w.correct}/{w.total}</span>
          </div>
        ))}
      </div>
      <div className="w-64">
        {r.report.mode === "mock" && <DiagnosisPanel userId={USER_ID} />}
        <div className="mb-2 rounded-lg border border-border border-l-4 border-l-primary bg-accent p-2.5 text-[12.5px]">
          🔁 <b>错题入 SM-2</b><br />{r.scheduled} 题：明天 → 3 天后 → 8 天后
        </div>
        {r.report.plan_adjusted && (
          <div className="mb-2 rounded-lg border border-border border-l-4 border-l-[var(--success)] bg-green-50 p-2.5 text-[12.5px]">
            🗓 <b>计划已自动加练</b><br />{String(r.report.plan_adjustment?.action || "").slice(0, 44)}
          </div>
        )}
        <div className="mb-2 rounded-lg border border-border border-l-4 border-l-sky-600 bg-sky-50 p-2.5 text-[12.5px]">
          🎓 <b>相似题推荐</b><br /><span className="text-muted-foreground">同考点换问法专项练习（P5 排期）</span>
        </div>
        <Button size="sm" variant="outline" onClick={onWrong}>▶️ 开始错题复习</Button>
      </div>
    </div>
  );
}
