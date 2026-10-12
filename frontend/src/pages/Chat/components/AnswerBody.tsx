import { useState } from "react";
import type { ChatMsg, Src } from "@/lib/types";
import { CitationChip, CitationSheet } from "./CitationChip";
import { Markdown } from "@/components/Markdown";

/** 助手回答渲染：引用标记替换为可交互角标（hover 预览/点击抽屉），附来源列表 */
export function AnswerBody({ m }: { m: ChatMsg }) {
  const [openSrc, setOpenSrc] = useState<Src | null>(null);
  const srcList = m.sources || [];
  // 正文按引用标记切段渲染（不再走 innerHTML——角标要挂交互）
  const parts: Array<{ text: string; src?: { s: Src; i: number } }> = [];
  let rest = m.content;
  const markers = srcList.map((s) => `[${s.id.slice(0, 14)}…]`);
  for (let guard = 0; guard < 50 && rest; guard++) {
    let first = -1, hit = -1;
    markers.forEach((mk, j) => {
      const p = rest.indexOf(mk);
      if (p >= 0 && (first < 0 || p < first)) { first = p; hit = j; }
    });
    if (first < 0) { parts.push({ text: rest }); break; }
    if (first > 0) parts.push({ text: rest.slice(0, first) });
    parts.push({ text: "", src: { s: srcList[hit], i: hit } });
    rest = rest.slice(first + markers[hit].length);
  }
  return (
    <div className="text-[13.5px] leading-7">
      <div>
        {parts.map((p, k) => p.src
          ? <CitationChip key={k} index={p.src.i} src={p.src.s} onOpen={setOpenSrc} />
          : <Markdown key={k} text={p.text.replace(/\[(?:chunk:)?doc-[\w…·]+\]/g, "")} />)}
      </div>
      {!!srcList.length && (
        <>
          <div className="mt-2 text-xs font-bold">来源</div>
          {srcList.map((s, i) => (
            <button key={s.id}
              className="mt-1 block w-full rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-left text-xs hover:border-primary"
              onClick={() => setOpenSrc(s)}>
              <span className="cite">{i + 1}</span> <span className="font-semibold text-secondary-foreground">{s.label}</span>
              <div className="mt-0.5 text-muted-foreground">{s.excerpt}…</div>
            </button>
          ))}
        </>
      )}
      <CitationSheet src={openSrc} onClose={() => setOpenSrc(null)} />
    </div>
  );
}
