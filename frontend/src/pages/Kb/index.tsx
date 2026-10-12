import { useEffect, useState } from "react";
import { api } from "@/lib/api";
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
  const [docs, setDocs] = useState<Doc[]>([]);
  const [meta, setMeta] = useState({ total: 0, library_total: 0, indexed: 0, total_chunks: 0, active: 0 });
  const [libRecall, setLibRecall] = useState("—");
  const [verified, setVerified] = useState("—");
  const [openChunks, setOpenChunks] = useState<Record<string, ChunkRow[]>>({});
  const [evalPanel, setEvalPanel] = useState<EvalRes | "loading" | null>(null);

  const load = (p = page, q = query) =>
    api<Overview>(`/kb/documents?page=${p}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(q)}`).then((d) => {
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

      <div className="mt-4 flex items-center gap-2">
        <div className="text-sm font-bold">文档列表</div>
        {meta.active > 0 && (
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-semibold text-primary">
            {meta.active} 个文档处理中…
          </span>
        )}
        {query && <span className="text-[11px] text-muted-foreground">筛选 “{query}”：{meta.total} / {meta.library_total}</span>}
        <input
          className="ml-auto w-56 rounded-lg border border-input bg-white px-3 py-1.5 text-[13px] outline-none focus:border-primary"
          placeholder="搜索标题 / 文件名…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
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
