import { useState } from "react";
import { api } from "@/lib/api";
import type { Src } from "@/lib/types";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/** 引用角标/来源卡：hover 显示摘录预览，点击抽屉展示 chunk 全文 */
export function CitationChip({ index, src, onOpen }: { index: number; src: Src; onOpen: (s: Src) => void }) {
  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <button
          className="mx-0.5 inline-flex h-[18px] min-w-[18px] cursor-pointer items-center justify-center rounded bg-secondary px-1 align-[2px] text-[11px] font-bold text-primary hover:bg-primary hover:text-white"
          onClick={() => onOpen(src)}
          title={`查看出处 ${index + 1}`}
        >
          {index + 1}
        </button>
      </HoverCardTrigger>
      <HoverCardContent side="top" className="w-80 text-xs">
        <div className="font-semibold text-secondary-foreground">{src.label}</div>
        <div className="mt-1 max-h-24 overflow-hidden text-muted-foreground">{src.excerpt}…</div>
        <div className="mt-1.5 text-[10px] text-muted-foreground">点击查看原文</div>
      </HoverCardContent>
    </HoverCard>
  );
}

/** 引用原文抽屉（挂在消息列表层，一次只开一个） */
type ChunkDetail = { id: string; title: string; page_no: number; section_path: string; content: string };

export function CitationSheet({ src, onClose }: { src: Src | null; onClose: () => void }) {
  const [detail, setDetail] = useState<ChunkDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const chunkId = src?.id || "";
  const loadedFor = detail?.id === chunkId ? detail : null;

  if (src && !loadedFor && !loading && !error) {
    setLoading(true);
    api<{ chunk: ChunkDetail }>(`/kb/chunk/${encodeURIComponent(chunkId)}`)
      .then((d) => setDetail(d.chunk))
      .catch(() => setError("原文加载失败"))
      .finally(() => setLoading(false));
  }
  if (!src && (detail || error)) { setDetail(null); setError(""); }

  return (
    <Sheet open={!!src} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-[440px] overflow-y-auto sm:max-w-[440px]">
        <SheetHeader>
          <SheetTitle className="text-left text-sm">{src?.label || "出处原文"}</SheetTitle>
        </SheetHeader>
        <div className="px-1 pb-6 text-[13px] leading-7">
          {src && <div className="mb-3 rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-xs">{src.excerpt}…</div>}
          {loading && <div className="text-muted-foreground">加载原文…</div>}
          {error && <div className="text-destructive">{error}</div>}
          {loadedFor && (
            <>
              <div className="mb-2 text-xs text-muted-foreground">
                {loadedFor.title}
                {loadedFor.page_no ? ` · P${loadedFor.page_no}` : ""}
                {loadedFor.section_path ? ` · ${loadedFor.section_path}` : ""}
              </div>
              <div className="whitespace-pre-wrap">{loadedFor.content}</div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
