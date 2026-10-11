import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { MODES } from "../constants";

/** 练习模式切换 + 错题本/收藏夹徽标 */
export function ModeTabs({ mode, badges, onSelect }: {
  mode: string;
  badges: { wrong: number; favorites: number };
  onSelect: (mode: string) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-border bg-accent px-3 py-2">
      <div className="flex overflow-hidden rounded-lg border border-primary">
        {MODES.map((m) => (
          <button key={m.value} onClick={() => onSelect(m.value)}
            className={cn("cursor-pointer px-3.5 py-1.5 text-[12.5px]",
              mode === m.value ? "bg-primary font-semibold text-white" : "text-primary hover:bg-secondary")}>
            {m.label}{m.value === "wrong_review" && badges.wrong > 0 ? `（今日到期 ${badges.wrong}）` : ""}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <Badge variant="warn">📖 错题本（{badges.wrong}）</Badge>
        <Badge variant="warn">⭐ 收藏夹（{badges.favorites}）</Badge>
      </div>
    </div>
  );
}
