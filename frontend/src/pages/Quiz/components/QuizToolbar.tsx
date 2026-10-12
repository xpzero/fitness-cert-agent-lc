import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Question } from "@/lib/types";
import { TYPE_LABEL } from "../constants";

/** 答题进度条 + 每轮题数选择 + 开始按钮 */
export function QuizToolbar({ q, total, idx, answered, count, setCount, onStart }: {
  q: Question | undefined;
  total: number;
  idx: number;
  answered: number;
  count: string;
  setCount: (v: string) => void;
  onStart: () => void;
}) {
  return (
    <div className="mt-3 flex items-center gap-3 rounded-xl border border-border bg-accent px-3.5 py-2.5">
      <Badge variant="warn">{total ? `第 ${idx + 1} / ${total} 题 · ${q ? (TYPE_LABEL[q.type] || q.type) : ""}` : "未开始"}</Badge>
      <div className="h-[7px] flex-1 overflow-hidden rounded-full bg-secondary">
        <div className="h-full bg-primary transition-all" style={{ width: `${total ? ((idx + 1) / total) * 100 : 0}%` }} />
      </div>
      <span className="whitespace-nowrap text-[11px] text-muted-foreground">已答 {answered}/{total}</span>
      <Select value={count} onValueChange={setCount}>
        <SelectTrigger className="w-[88px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {["5", "10", "15", "20"].map((n) => <SelectItem key={n} value={n}>{n} 题</SelectItem>)}
        </SelectContent>
      </Select>
      <Button onClick={onStart}>开始</Button>
    </div>
  );
}
