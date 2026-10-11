import { Fragment } from "react";
import { Badge, Dot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ChunkRow, Doc } from "@/lib/types";
import { cn } from "@/lib/utils";

function StatusCell({ d }: { d: Doc }) {
  if (d.status === "indexed") return <Badge variant="ok"><Dot tone="ok" />已索引</Badge>;
  if (d.status === "failed")
    return (
      <div>
        <Badge variant="bad"><Dot tone="fail" />解析失败</Badge>
        <div className="mt-1 max-w-[220px] truncate text-[11px] text-muted-foreground">{d.error || d.job?.detail}</div>
      </div>
    );
  return (
    <div>
      <Badge variant="warn"><Dot tone="parsing" />{{ queued: "排队中", parsing: "解析中", embedding: "向量化中" }[d.status] || d.status}</Badge>
      <div className="mt-1.5 h-1.5 w-[110px] overflow-hidden rounded-full bg-secondary">
        <div className="h-full bg-primary" style={{ width: `${d.job?.progress || 0}%` }} />
      </div>
      <div className="text-[11px] text-muted-foreground">{d.job?.detail}</div>
    </div>
  );
}

/** 文档列表：状态/进度、chunk 展开、评测/重解析/删除操作（分页，pageSize 个/页） */
export function DocTable({ docs, page, pageSize, total, onPage, openChunks, onToggleChunks, onEval, onReingest, onDelete }: {
  docs: Doc[];
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
  openChunks: Record<string, ChunkRow[]>;
  onToggleChunks: (id: string) => void;
  onEval: (id: string) => void;
  onReingest: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div>
      <div className="mt-4 text-sm font-bold">文档列表</div>
      <div className="text-xs text-muted-foreground">状态自动刷新（3s 轮询）· 删除前检查题目引用 · 点击文件名展开 chunk</div>
      <div className="mt-1 rounded-xl border border-border bg-accent p-2.5">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="bg-muted text-left text-xs text-muted-foreground">
              <th className="px-2.5 py-2.5 font-medium">文件</th>
              <th className="w-[150px] px-2 py-2.5 font-medium">状态 / 进度</th>
              <th className="w-[64px] px-2 py-2.5 font-medium">Chunks</th>
              <th className="w-[64px] px-2 py-2.5 font-medium">权威级</th>
              <th className="w-[84px] px-2 py-2.5 font-medium">页码</th>
              <th className="w-[92px] px-2 py-2.5 font-medium">创建时间</th>
              <th className="w-[92px] px-2 py-2.5 font-medium">更新时间</th>
              <th className="w-[218px] px-2 py-2.5 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <Fragment key={d.id}>
                <tr className="align-middle">
                  <td className="px-2.5 py-3">
                    <div className="max-w-[280px] cursor-pointer truncate font-semibold hover:text-primary"
                      title={d.title} onClick={() => onToggleChunks(d.id)}>{d.title}</div>
                    <div className="max-w-[280px] truncate text-[11px] text-muted-foreground" title={d.filename}>{d.filename || "种子语料"}</div>
                  </td>
                  <td className="px-2 py-3"><StatusCell d={d} /></td>
                  <td className="whitespace-nowrap px-2 py-3">{d.chunks || "—"}</td>
                  <td className="px-2 py-3">
                    <span className={cn("whitespace-nowrap rounded-md px-2 py-0.5 text-[11.5px]",
                      { 1: "bg-orange-100 text-orange-700", 2: "bg-yellow-100 text-yellow-700", 3: "bg-sky-100 text-sky-700" }[d.authority_level])}>
                      {["", "官方", "半官方", "补充"][d.authority_level]}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-3">{d.max_page ? `P${d.min_page}–P${d.max_page}` : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-3 text-[11.5px] text-muted-foreground">
                    {d.created_at ? new Date(d.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-3 text-[11.5px] text-muted-foreground">
                    {d.updated_at ? new Date(d.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex gap-1">
                      <Button size="sm" onClick={() => onEval(d.id)}>📊 评测</Button>
                      <Button size="sm" variant="outline" onClick={() => onReingest(d.id)}>重解析</Button>
                      <Button size="sm" variant="destructive" onClick={() => onDelete(d.id)}>删除</Button>
                    </div>
                  </td>
                </tr>
                {openChunks[d.id] && (
                  <tr>
                    <td colSpan={8} className="bg-muted/60 px-3 py-2.5">
                      {openChunks[d.id].map((c) => (
                        <div key={c.id} className="mb-1.5 rounded-lg border border-border border-l-4 border-l-primary bg-white px-3 py-2 text-xs">
                          <b className="font-mono text-[11px] text-secondary-foreground">…{c.id.slice(-12)}</b> ｜ P{c.page_no}
                          {c.section_path ? ` §${c.section_path}` : ""}
                          <div className="mt-0.5">{c.content.slice(0, 110)}…</div>
                        </div>
                      ))}
                      <div className="text-[11px] text-muted-foreground">共显示前 20 块</div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
          <div>共 {total} 个文档</div>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(1)}>«</Button>
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</Button>
            <span className="px-1.5">第 {page} / {pages} 页</span>
            <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</Button>
            <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(pages)}>»</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
