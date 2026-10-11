import type { ChatMsg } from "@/lib/types";

/** 助手回答渲染：引用标记替换为角标，附来源列表 */
export function AnswerBody({ m }: { m: ChatMsg }) {
  let html = m.content
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
  (m.sources || []).forEach((s, i) => {
    html = html.split(`[${s.id.slice(0, 14)}…]`).join(`<span class="cite">${i + 1}</span>`);
  });
  html = html.replace(/\[(?:chunk:)?doc-[\w…·]+\]/g, "");
  return (
    <div className="text-[13.5px] leading-7">
      <div dangerouslySetInnerHTML={{ __html: html }} />
      {!!m.sources?.length && (
        <>
          <div className="mt-2 text-xs font-bold">来源</div>
          {m.sources.map((s, i) => (
            <div key={s.id} className="mt-1 rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-xs">
              <span className="cite">{i + 1}</span> <span className="font-semibold text-secondary-foreground">{s.label}</span>
              <div className="mt-0.5 text-muted-foreground">{s.excerpt}…</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
