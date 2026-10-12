import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** jsonl 用例导入/导出：粘贴文本或选择本地 .jsonl 文件，逐行导入（非法行报行号） */
export function CaseImport({ kind, onDone }: { kind: string; onDone: () => void }) {
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function importJsonl(jsonl: string) {
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ imported: number; errors: string[] }>(`/eval/${kind}/import`, {
        method: "POST", body: JSON.stringify({ jsonl }) });
      setMsg({ ok: !r.errors.length,
        text: `导入 ${r.imported} 条` + (r.errors.length ? `；${r.errors.length} 条失败：${r.errors.join("；")}` : "") });
      onDone();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message || "导入失败" });
    }
    setBusy(false);
  }

  async function onFile() {
    const f = fileRef.current?.files?.[0];
    if (f) setText(await f.text());
  }

  return (
    <div className="mt-2 rounded-lg border border-border bg-white p-2.5">
      <div className="flex items-center gap-2">
        <div className="text-xs font-semibold">导入用例（jsonl）</div>
        <input ref={fileRef} type="file" accept=".jsonl,.txt" className="text-[11px]"
               onChange={onFile} />
        <Button variant="outline" className="ml-auto h-7 px-2.5 text-[11px]" disabled={busy || !text.trim()}
                onClick={() => importJsonl(text)}>导入</Button>
        <Button variant="outline" className="h-7 px-2.5 text-[11px]" onClick={async () => {
          const r = await api<{ jsonl: string }>(`/eval/${kind}/export`);
          const blob = new Blob([r.jsonl], { type: "application/x-ndjson" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `${kind}_cases.jsonl`;
          a.click();
        }}>导出</Button>
      </div>
      <textarea
        className="mt-1.5 h-24 w-full rounded border border-input p-2 font-mono text-[11px] outline-none focus:border-primary"
        placeholder={'粘贴 jsonl 文本，一行一个用例，如：\n{"text": "卧推练哪里？", "expect": "qa"}\n{"query": "…", "relevant_chunk_ids": ["doc-xxx-1"]}'}
        value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      {msg && <div className={`text-[11px] ${msg.ok ? "text-[var(--success)]" : "text-destructive"}`}>{msg.text}</div>}
    </div>
  );
}
