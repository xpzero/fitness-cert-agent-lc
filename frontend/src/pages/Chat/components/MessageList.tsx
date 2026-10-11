import type { RefObject } from "react";
import type { ChatMsg } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AnswerBody } from "./AnswerBody";

/** 消息气泡列表：含 LangGraph 执行链路 trail 与流式输出光标 */
export function MessageList({ msgs, busy, trail, boxRef }: {
  msgs: ChatMsg[];
  busy: boolean;
  trail: string[];
  boxRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div ref={boxRef} className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-input bg-white p-4">
      {msgs.length === 0 && (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          问点什么，例如：卧推的目标肌群是什么？
        </div>
      )}
      {msgs.map((m, i) => (
        <div key={i} className={cn("mb-4 flex gap-2.5", m.role === "user" && "flex-row-reverse")}>
          <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-lg",
            m.role === "user" ? "bg-blue-100" : "bg-secondary")}>
            {m.role === "user" ? "🧑" : "🏋️"}
          </div>
          <div className="max-w-[78%]">
            {i === msgs.length - 1 && busy && m.role === "assistant" && trail.length > 0 && (
              <div className="mb-1 text-[11px] text-muted-foreground">{trail.join(" → ")}</div>
            )}
            {m.role === "user"
              ? <div className="rounded-xl bg-blue-100 px-3 py-2 text-[13.5px] leading-7">{m.content}</div>
              : <AnswerBody m={m} />}
          </div>
        </div>
      ))}
      {busy && <span className="text-primary">▌</span>}
    </div>
  );
}
