const FOLLOW_UPS = ["考试对这项内容的要求是什么？", "这个考点的常见错误是什么？"];

/** 基于上一条可溯源回答的追问快捷按钮 */
export function FollowUps({ onSend }: { onSend: (text: string) => void }) {
  return (
    <div className="mt-2 flex gap-2">
      {FOLLOW_UPS.map((f) => (
        <button key={f} onClick={() => onSend(f)}
          className="cursor-pointer rounded-full border border-border bg-accent px-3 py-1.5 text-xs text-secondary-foreground hover:bg-secondary">
          {f}
        </button>
      ))}
    </div>
  );
}
