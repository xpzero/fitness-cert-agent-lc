import { Button } from "@/components/ui/button";

export function ChatInput({ input, setInput, busy, onSend }: {
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  onSend: () => void;
}) {
  return (
    <div className="mt-2.5 flex gap-2.5">
      <input
        className="flex-1 rounded-lg border border-input bg-white px-3 py-2.5 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
        placeholder="问点什么，例如：俯卧撑的合格标准是什么？"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onSend()}
      />
      <Button onClick={() => onSend()} disabled={busy}>发送</Button>
    </div>
  );
}
