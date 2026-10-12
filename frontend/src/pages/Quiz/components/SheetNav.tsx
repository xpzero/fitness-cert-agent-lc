import { Button } from "@/components/ui/button";
import type { Question, QuizResult } from "@/lib/types";
import { cn } from "@/lib/utils";

/** 答题卡：题号跳转 + 交卷 + 收藏/标疑当前题 */
export function SheetNav({ qs, answers, idx, result, busy, favOn, flagged, onJump, onSubmit, onToggleFav, onToggleFlag }: {
  qs: Question[];
  answers: Record<string, string>;
  idx: number;
  result: QuizResult | null;
  busy: boolean;
  favOn: boolean;
  flagged: boolean;
  onJump: (i: number) => void;
  onSubmit: () => void;
  onToggleFav: () => void;
  onToggleFlag: () => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-accent px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-[11px] text-muted-foreground">
        答题卡
        <span className="ml-auto">{Object.keys(answers).length}/{qs.length}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {qs.map((x, i) => (
          <button key={x.id} onClick={() => onJump(i)}
            className={cn("flex h-[30px] w-[30px] cursor-pointer items-center justify-center rounded-lg border text-xs",
              answers[x.id] ? "border-primary bg-secondary text-primary" : "border-input text-muted-foreground",
              i === idx && "outline-2 outline-primary")}>
            {i + 1}
          </button>
        ))}
      </div>
      <div className="mt-2.5 flex gap-1.5">
        <Button size="sm" variant="outline" className="flex-1" onClick={onToggleFav}>{favOn ? "⭐ 已收藏" : "☆ 收藏"}</Button>
        <Button size="sm" variant="outline" className="flex-1" onClick={onToggleFlag}>{flagged ? "🚩 已标疑" : "🚩 标疑"}</Button>
      </div>
      <Button className="mt-1.5 w-full" disabled={!!result || busy} onClick={onSubmit}>
        {busy ? "⏳ 判分中…" : "📝 交卷并判分"}
      </Button>
    </div>
  );
}
