import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SearchHit } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEARCH_MODES: [string, string][] = [["hybrid", "混合"], ["dense", "语义"], ["sparse", "词面"]];

/** 检索试驾：混合/语义/词面模式切换，展示分数构成（dense/sparse/RRF） */
export function SearchPanel() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("dense");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  async function search() {
    if (!q.trim()) return;
    setSearching(true);
    try {
      setHits((await api(`/kb/search?q=${encodeURIComponent(q)}&mode=${mode}`)).results);
    } finally { setSearching(false); }
  }

  return (
    <div className="flex-1 rounded-xl border border-input bg-accent p-3.5">
      <div className="text-sm font-bold">检索试驾 <span className="text-[11px] font-normal text-muted-foreground">（模式切换 · 分数构成）</span></div>
      <div className="mt-2 inline-flex overflow-hidden rounded-lg border border-primary">
        {SEARCH_MODES.map(([v, label]) => (
          <button key={v} onClick={() => setMode(v)}
            className={cn("cursor-pointer px-4 py-[7px] text-[12.5px]",
              mode === v ? "bg-primary font-semibold text-white" : "text-primary hover:bg-secondary")}>
            {label}
          </button>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2.5">
        <Input className="flex-1" placeholder="例如：坐姿体前屈的合格标准" value={q}
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        <Button className="h-9 shrink-0" onClick={search} disabled={searching}>{searching ? "检索中…" : "🔍 检索"}</Button>
      </div>
      <div className="mt-2">
        {searching && <div className="py-4 text-center text-xs text-muted-foreground">检索中…</div>}
        {!searching && hits !== null && hits.length === 0 && (
          <div className="rounded-lg border border-border bg-muted px-3 py-3 text-center text-xs text-muted-foreground">
            词面模式无命中——该说法与语料原文差异较大，建议切「混合」或「语义」模式
          </div>
        )}
        {hits?.map((c, i) => (
          <div key={c.chunk_id} className="mb-1.5 rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-xs">
            <b>#{i + 1}</b> <span className="font-semibold text-secondary-foreground">{c.label}</span> · 权威 {c.authority} · {c.score}
            <div className="mt-1">{c.content?.slice(0, 130)}…</div>
            <div className="text-[11px] text-muted-foreground">dense #{c.dense_rank ?? "—"} ｜ sparse #{c.sparse_rank ?? "—"} ｜ RRF 融合</div>
          </div>
        ))}
      </div>
    </div>
  );
}
