import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CaseImport } from "./components/CaseImport";

type Run = { kind: string; metrics: Record<string, unknown>; passed: boolean; created_at: string };
type KindInfo = { kind: string; cases: number; gate: { metric: string; min: number }; latest: Run | null };

const KIND_META: Record<string, { label: string; desc: string; needLLM: boolean }> = {
  retrieval: { label: "检索 Recall@5", desc: "金标准 query → 混合检索 top5 命中", needLLM: false },
  intent: { label: "意图路由", desc: "两级路由准确率（快路径+LLM）", needLLM: true },
  citation: { label: "引用正确率", desc: "qa 图引用 chunk 命中 + 拒答率", needLLM: true },
  adversarial: { label: "对抗评审", desc: "坏题捕获率 / 好题误伤率", needLLM: true },
};

/** 评测中心：四卡片（门槛+最近结果）+ 运行进度 + 用例浏览 */
export default function Eval() {
  const [kinds, setKinds] = useState<KindInfo[]>([]);
  const [running, setRunning] = useState<Record<string, { run_id: string; progress: number }>>({});
  const [casesOf, setCasesOf] = useState<{ kind: string; cases: unknown[] } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = () => api<{ kinds: KindInfo[] }>("/eval/overview").then((d) => setKinds(d.kinds)).catch(() => {});
  useEffect(() => { load(); }, []);

  useEffect(() => {
    pollRef.current = setInterval(() => {
      Object.entries(running).forEach(async ([kind, r]) => {
        const t = await api<{ phase: string; progress: number; error?: string }>(`/eval/runs/${r.run_id}`).catch(() => null);
        if (!t) return;
        if (t.phase === "done" || t.phase === "failed") {
          setRunning((o) => { const n = { ...o }; delete n[kind]; return n; });
          load();
        } else {
          setRunning((o) => ({ ...o, [kind]: { ...r, progress: t.progress } }));
        }
      });
    }, 1500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [running]);

  async function run(kind: string) {
    const { run_id } = await api<{ run_id: string }>(`/eval/${kind}/run`, { method: "POST", body: "{}" });
    setRunning((o) => ({ ...o, [kind]: { run_id, progress: 0 } }));
  }

  async function runAll() {
    for (const k of kinds) {
      if (KIND_META[k.kind]?.needLLM === false) await run(k.kind);  // 无 LLM 依赖的并行安全，直接全发
    }
    for (const k of kinds) {
      if (KIND_META[k.kind]?.needLLM) await run(k.kind);            // LLM 类串行发（后台本来就是单线程池）
    }
  }

  function openCases(kind: string) {
    api<{ cases: unknown[] }>(`/eval/${kind}/cases`).then((d) => setCasesOf({ kind, cases: d.cases }));
  }

  return (
    <div>
      <div className="flex items-center gap-2">
        <div className="text-sm font-bold">评测中心</div>
        <Button className="ml-auto" disabled={Object.keys(running).length > 0} onClick={runAll}>
          ▶ 一键运行全部
        </Button>
      </div>
      <div className="text-xs text-muted-foreground">
        门槛即 CI 门槛；用例存数据库（eval_cases），可增删改。检索/意图可即时跑，引用与对抗需 LLM（分钟级，自动串行）。
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3.5">
        {kinds.map((k) => {
          const meta = KIND_META[k.kind] || { label: k.kind, desc: "", needLLM: false };
          const latest = k.latest;
          const val = latest ? Number(latest.metrics[k.gate.metric] ?? 0) : null;
          const r = running[k.kind];
          return (
            <div key={k.kind} className="rounded-xl border border-border bg-accent p-3.5">
              <div className="flex items-center gap-2">
                <div className="text-[13.5px] font-bold">{meta.label}</div>
                {latest && (
                  <Badge variant={latest.passed ? "ok" : "bad"}>
                    {latest.passed ? "✅ 过门槛" : "❌ 未达标"}
                  </Badge>
                )}
                <div className="ml-auto flex gap-1.5">
                  <Button variant="outline" onClick={() => openCases(k.kind)}>用例 {k.cases}</Button>
                  <Button disabled={!!r} onClick={() => run(k.kind)}>{r ? `${r.progress}%` : "运行"}</Button>
                </div>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">{meta.desc}{meta.needLLM ? " · 需 LLM" : ""}</div>
              <div className="mt-2 flex items-end gap-3">
                <div>
                  <span className="text-2xl font-bold text-primary">{val === null ? "—" : val}</span>
                  {val !== null && <span className="text-xs text-muted-foreground"> / ≥{k.gate.min}</span>}
                </div>
                {latest && (
                  <div className="ml-auto text-right text-[10.5px] text-muted-foreground">
                    {new Date(latest.created_at).toLocaleString("zh-CN", { hour12: false })}
                    <div>{Object.entries(latest.metrics).map(([m, v]) => `${m}=${v}`).join(" · ")}</div>
                  </div>
                )}
              </div>
              {r && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
                  <div className="h-full bg-primary transition-all" style={{ width: `${r.progress}%` }} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {casesOf && (
        <div className="mt-4 rounded-xl border border-border bg-accent p-3">
          <div className="flex items-center gap-2">
            <div className="text-sm font-bold">{KIND_META[casesOf.kind]?.label || casesOf.kind} · 用例</div>
            <span className="text-[11px] text-muted-foreground">{casesOf.cases.length} 条</span>
            <Button variant="outline" className="ml-auto" onClick={() => setCasesOf(null)}>关闭</Button>
          </div>
          <CaseImport kind={casesOf.kind} onDone={() => openCases(casesOf.kind)} />
          <div className="mt-2 max-h-80 overflow-y-auto rounded-lg bg-white">
            <pre className="p-3 font-mono text-[11px] leading-5">
              {casesOf.cases.map((c) => JSON.stringify(c)).join("\n")}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
