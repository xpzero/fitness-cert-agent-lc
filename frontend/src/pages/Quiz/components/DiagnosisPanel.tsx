import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ssePost } from "@/lib/api";
import type { DiagReport, DiagStep } from "@/lib/types";

const TOOL_LABELS: Record<string, string> = {
  chapter_accuracy: "各章正确率",
  chapter_wrong_detail: "章节错题下钻",
  wrongbook_backlog: "错题本积压",
  mock_trend: "模考趋势",
  plan_state: "计划对照",
};

/** AI 深度诊断（W3）：SSE 调查时间线 + 结构化报告卡（模考报告右侧入口） */
export function DiagnosisPanel({ userId }: { userId: string }) {
  const [steps, setSteps] = useState<DiagStep[]>([]);
  const [report, setReport] = useState<DiagReport | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setSteps([]);
    setReport(null);
    try {
      await ssePost("/quiz/diagnose", { user_id: userId }, (evt) => {
        if (evt.event === "step") setSteps((s) => [...s, evt]);
        if (evt.event === "report") setReport(evt.report);
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-2 rounded-lg border border-border border-l-4 border-l-violet-500 bg-violet-50 p-2.5 text-[12.5px]">
      <div className="flex items-center justify-between">
        <b>🧠 AI 深度诊断</b>
        <Button size="sm" variant="outline" disabled={busy} onClick={run}>
          {busy ? "调查中…" : report ? "重新诊断" : "开始诊断"}
        </Button>
      </div>
      {(steps.length > 0 || busy) && (
        <div className="mt-2 space-y-1">
          {steps.map((s, i) => (
            <details key={i} className="rounded border border-violet-200 bg-white px-2 py-1">
              <summary className="cursor-pointer text-[12px]">
                <span className="text-violet-700">[{TOOL_LABELS[s.tool] || s.tool}]</span>{" "}
                {s.thought?.slice(0, 40)}
              </summary>
              <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap text-[11px] text-muted-foreground">
                {s.output}
              </pre>
            </details>
          ))}
          {busy && <div className="text-[11px] text-muted-foreground">▍正在调查…</div>}
        </div>
      )}
      {report && (
        <div className="mt-2 rounded border border-violet-200 bg-white p-2">
          {report.degraded && (
            <div className="mb-1 text-[11px] text-orange-600">（降级模式：规则统计）</div>
          )}
          {report.findings?.map((f, i) => (
            <div key={i} className="mb-1">
              <b>{f.chapter}</b>：{f.symptom}
              <span className="ml-1 text-[10.5px] text-muted-foreground">
                （依据 {f.evidence?.source_tool}：{String(f.evidence?.value).slice(0, 30)}）
              </span>
            </div>
          ))}
          {report.suggestions?.length > 0 && (
            <div className="mt-1.5 border-t border-dashed border-violet-200 pt-1.5">
              {report.suggestions.map((s, i) => (
                <div key={i}>💡 {s}</div>
              ))}
            </div>
          )}
          {report.plan_adjusted && (
            <div className="mt-1.5 text-[11.5px] text-[var(--success)]">
              ✅ 建议已同步到「规划」标签页的 active 计划
            </div>
          )}
        </div>
      )}
    </div>
  );
}
