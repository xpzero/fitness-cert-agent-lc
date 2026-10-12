import ReactMarkdown from "react-markdown";

/** LLM 返回的 markdown 渲染（加粗/列表/代码/表格），复用于 qa 回答与 coach 讲解 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="text-[13.5px] leading-7 [&_b]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px]
      [&_h1]:mt-3 [&_h1]:text-[15px] [&_h1]:font-bold [&_h2]:mt-3 [&_h2]:text-[14px] [&_h2]:font-bold
      [&_li]:my-0.5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-2.5 [&_pre]:font-mono [&_pre]:text-[12px]
      [&_strong]:text-secondary-foreground [&_table]:my-2 [&_table]:w-full [&_table]:text-[12px] [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}
