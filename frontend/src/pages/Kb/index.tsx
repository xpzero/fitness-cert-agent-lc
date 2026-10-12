import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ChunkRow, Doc, EvalRes } from "@/lib/types";
import { DocTable } from "./components/DocTable";
import { EvalPanel } from "./components/EvalPanel";
import { MetricCards } from "./components/MetricCards";
import { SearchPanel } from "./components/SearchPanel";
import { UploadPanel } from "./components/UploadPanel";

const PAGE_SIZE = 10;

type Overview = {
  documents: Doc[];
  lib_recall?: string;
  total: number;
  library_total?: number;
  indexed: number;
  total_chunks: number;
  active: number;
};

export default function Kb() {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [auth, setAuth] = useState("0");
  const [status, setStatus] = useState("");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [meta, setMeta] = useState({ total: 0, library_total: 0, indexed: 0, total_chunks: 0, active: 0 });
  const [libRecall, setLibRecall] = useState("—");
  const [verified, setVerified] = useState("—");
  const [openChunks, setOpenChunks] = useState<Record<string, ChunkRow[]>>({});
  const [evalPanel, setEvalPanel] = useState<EvalRes | "loading" | null>(null);

  const load = (p = page, q = query, a = auth, st = status) =>
    api<Overview>(`/kb/documents?page=${p}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(q)}&authority=${a}&status=${st}`).then((d) => {
      setDocs(d.documents);
      setMeta({ total: d.total, library_total: d.library_total ?? d.total, indexed: d.indexed, total_chunks: d.total_chunks, active: d.active });
      setLibRecall(d.lib_recall || "—");
      // 删除末页唯一文档后自动回退一页，避免停在空页
      if (d.documents.length === 0 && d.total > 0 && p > 1) setPage(p - 1);
    });

  useEffect(() => {
    load(page, query);
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  // 搜索防抖 400ms
  useEffect(() => {
    const t = setTimeout(() => { if (page !== 1) setPage(1); else load(1, query); }, 400);
    return () => clearTimeout(t);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps
  // 筛选变化即刷新（回第一页）
  useEffect(() => {
    if (page !== 1) setPage(1); else load(1, query, auth, status);
  }, [auth, status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api<{ covered_total: number; uncovered: string[] }>("/coverage/nsca_cpt")
      .then((c) => setVerified(`${c.covered_total}/${c.covered_total + c.uncovered.length}`))
      .catch(() => {});
  }, []);

  useEffect(() => {
    // 轮询开关看全库 active：正在解析的文档可能不在当前页
    const t = meta.active > 0 ? setInterval(() => load(), 3000) : undefined;
    return () => clearInterval(t);
  }, [docs, page]);

  async function toggleChunks(id: string) {
    if (openChunks[id]) {
      const n = { ...openChunks };
      delete n[id];
      setOpenChunks(n);
      return;
    }
    const d = await api<{ chunks: ChunkRow[] }>(`/kb/documents/${id}/chunks?limit=20`);
    setOpenChunks((o) => ({ ...o, [id]: d.chunks }));
  }

  async function del(id: string) {
    const res = await api(`/kb/documents/${id}`, { method: "DELETE" }).catch((e) => e);
    if (res?.ok === false) {
      if (confirm(res.reason + "\n\n确定强制删除？相关题目将下架。"))
        await api(`/kb/documents/${id}?force=true`, { method: "DELETE" });
      else return;
    }
    load();
  }

  async function runEval(id: string) {
    setEvalPanel("loading");
    try {
      setEvalPanel(await api(`/kb/documents/${id}/eval`, { method: "POST", body: "{}" }));
    } catch (err: any) {
      setEvalPanel({ ok: false, reason: err.message });
    }
  }

  async function reingest(id: string) {
    await api(`/kb/reingest/${id}`, { method: "POST", body: "{}" });
    load();
  }

  return (
    <div>
      <MetricCards
        total={meta.total}
        indexed={meta.indexed}
        totalChunks={meta.total_chunks}
        verified={verified}
        libRecall={libRecall}
      />

      <UploadPanel onUploaded={() => load()} />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="text-sm font-bold">文档列表</div>
        <span className="text-[11px] text-muted-foreground">{meta.total} / {meta.library_total} 个文档</span>
        {meta.active > 0 && (
          <span className="animate-pulse rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-semibold text-primary">
            ⟳ {meta.active} 个处理中
          </span>
        )}
        <input
          className="ml-auto w-52 rounded-lg border border-input bg-white px-3 py-1.5 text-[13px] outline-none focus:border-primary"
          placeholder="搜索标题 / 文件名…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] text-muted-foreground">权威级</span>
        {[["0", "全部"], ["1", "官方"], ["2", "半官方"], ["3", "补充"]].map(([v, label]) => (
          <button key={v} onClick={() => setAuth(v)}
            className={cn("cursor-pointer rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors",
              auth === v ? "border-primary bg-primary text-white" : "border-border bg-card text-muted-foreground hover:border-primary hover:text-primary")}>
            {label}
          </button>
        ))}
        <span className="mx-2 h-3.5 w-px bg-border" />
        <span className="mr-1 text-[11px] text-muted-foreground">状态</span>
        {[["", "全部"], ["indexed", "已索引"], ["queued", "排队中"], ["parsing", "解析中"], ["embedding", "向量化中"], ["failed", "失败"]].map(([v, label]) => (
          <button key={v} onClick={() => setStatus(v)}
            className={cn("cursor-pointer rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors",
              status === v ? "border-primary bg-primary text-white" : "border-border bg-card text-muted-foreground hover:border-primary hover:text-primary")}>
            {label}
          </button>
        ))}
        {(auth !== "0" || status || query) && (
          <button onClick={() => { setAuth("0"); setStatus(""); setQuery(""); }}
            className="ml-1 cursor-pointer text-[11px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline">
            清除筛选
          </button>
        )}
      </div>

      <DocTable
        docs={docs}
        page={page}
        pageSize={PAGE_SIZE}
        total={meta.total}
        onPage={setPage}
        openChunks={openChunks}
        onToggleChunks={toggleChunks}
        onEval={runEval}
        onReingest={reingest}
        onDelete={del}
      />

      <div className="mt-4 flex gap-3.5">
        <SearchPanel />
        <EvalPanel panel={evalPanel} />
      </div>
    </div>
  );
}
