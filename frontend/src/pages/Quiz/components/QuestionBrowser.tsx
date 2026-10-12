import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Question } from "@/lib/types";
import { TYPE_LABEL } from "../constants";

type BrowseQ = Question & { chapter: string; point_title: string };

/** 题库浏览（章节练习全量列出）：章节筛选 + 分页 + 题型中文标签 */
export function QuestionBrowser({ onPractice }: { onPractice: () => void }) {
  const [qs, setQs] = useState<BrowseQ[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [chapter, setChapter] = useState("");
  const PAGE = 20;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  useEffect(() => {
    api<{ questions: BrowseQ[]; total: number }>(
      `/quiz/browse?chapter=${encodeURIComponent(chapter)}&page=${page}&page_size=${PAGE}`,
    ).then((d) => { setQs(d.questions); setTotal(d.total); }).catch(() => {});
  }, [page, chapter]);

  return (
    <div className="mt-3 rounded-xl border border-border bg-accent p-3">
      <div className="flex items-center gap-2">
        <div className="text-sm font-bold">题库浏览</div>
        <span className="text-[11px] text-muted-foreground">{total} 题</span>
        <input
          className="ml-auto w-44 rounded-lg border border-input bg-white px-2.5 py-1 text-[12.5px] outline-none focus:border-primary"
          placeholder="按章节筛选…"
          value={chapter}
          onChange={(e) => { setChapter(e.target.value); setPage(1); }}
        />
        <Button variant="outline" onClick={onPractice}>返回练习</Button>
      </div>
      <div className="mt-2 divide-y divide-border">
        {qs.map((q, i) => (
          <div key={q.id} className="flex items-start gap-2 py-2 text-[13px]">
            <span className="w-6 shrink-0 text-right text-muted-foreground">{(page - 1) * PAGE + i + 1}</span>
            <Badge variant="warn" className="shrink-0">{TYPE_LABEL[q.type] || q.type}</Badge>
            <div className="min-w-0 flex-1">
              <div className="truncate">{q.stem}</div>
              <div className="text-[11px] text-muted-foreground">{q.chapter} · {q.point_title}</div>
            </div>
          </div>
        ))}
        {!qs.length && <div className="py-6 text-center text-xs text-muted-foreground">无匹配题目</div>}
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center justify-center gap-2 text-xs">
          <Button variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</Button>
          <span className="text-muted-foreground">{page} / {pages}</span>
          <Button variant="outline" disabled={page === pages} onClick={() => setPage(page + 1)}>下一页</Button>
        </div>
      )}
    </div>
  );
}
