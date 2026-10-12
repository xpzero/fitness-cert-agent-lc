import { useState } from "react";
import type { ChatMsg, Src } from "@/lib/types";
import { CitationChip, CitationSheet } from "./CitationChip";
import ReactMarkdown from "react-markdown";

/** 引用标记 → markdown 链接占位（[doc-xxx…] → [​](#cite-N)），
 * 整篇一次渲染（markdown 结构不被角标切断），链接渲染器把 #cite-N 还原成角标组件 */
export function AnswerBody({ m }: { m: ChatMsg }) {
  const [openSrc, setOpenSrc] = useState<Src | null>(null);
  const srcList = m.sources || [];
  const markers = srcList.map((s) => `[${s.id.slice(0, 14)}…]`);

  // 预处理：正文中的引用标记换成 #cite-N 链接；残留未知标记（无 source 对应）清除
  let text = m.content;
  srcList.forEach((_s, i) => {
    text = text.split(markers[i]).join(`[^\u200b](#cite-${i})`);
  });
  text = text.replace(/\[(?:chunk:)?doc-[\w…·]+\]/g, "");

  return (
    <div className="text-[13.5px] leading-7">
      <div className="[&_b]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px]
        [&_li]:my-0.5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5
        [&_h1]:mt-3 [&_h1]:text-[15px] [&_h1]:font-bold [&_h2]:mt-3 [&_h2]:text-[14px] [&_h2]:font-bold
        [&_table]:my-2 [&_table]:w-full [&_table]:text-[12px] [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1">
        <ReactMarkdown
          components={{
            a: ({ href, children }) => {
              const m2 = /^#cite-(\d+)$/.exec(href || "");
              if (m2) {
                const i = Number(m2[1]);
                return <CitationChip index={i} src={srcList[i]} onOpen={setOpenSrc} />;
              }
              return <a href={href}>{children}</a>;
            },
          }}>
          {text}
        </ReactMarkdown>
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
