import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Setting = {
  key: string;
  category: "prompt" | "json";
  desc: string;
  value: unknown;
  default: unknown;
  overridden: boolean;
};

/** 编辑器：prompt 用 textarea，词表用 JSON textarea（保存时后端校验） */
function Editor({ s, onSaved }: { s: Setting; onSaved: () => void }) {
  const isJson = s.category === "json";
  const [text, setText] = useState(
    isJson ? JSON.stringify(s.value, null, 2) : String(s.value),
  );
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true); setMsg(null);
    let value: unknown = text;
    if (isJson) {
      try { value = JSON.parse(text); }
      catch { setMsg({ ok: false, text: "JSON 格式错误" }); setBusy(false); return; }
    }
    try {
      await api(`/settings/${s.key}`, { method: "PUT", body: JSON.stringify({ value }) });
      setMsg({ ok: true, text: "已保存" }); onSaved();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message || "保存失败" });
    }
    setBusy(false);
  }

  return (
    <div className="rounded-xl border border-border bg-accent p-3">
      <div className="flex items-center gap-2">
        <code className="text-[12px] font-semibold">{s.key}</code>
        <Badge variant="warn">{s.desc}</Badge>
        {s.overridden && <Badge variant="ok">已覆盖默认</Badge>}
        <div className="ml-auto flex items-center gap-2">
          {msg && <span className={`text-[11px] ${msg.ok ? "text-[var(--success)]" : "text-destructive"}`}>{msg.text}</span>}
          {s.overridden && (
            <Button variant="outline" onClick={async () => {
              await api(`/settings/${s.key}`, { method: "DELETE" }); onSaved();
            }}>恢复默认</Button>
          )}
          <Button disabled={busy} onClick={save}>保存</Button>
        </div>
      </div>
      <textarea
        className="mt-2 h-40 w-full rounded-lg border border-input bg-white p-2.5 font-mono text-[12px] leading-5 outline-none focus:border-primary"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
      />
      <div className="mt-1 text-[10.5px] text-muted-foreground">
        {s.category === "prompt"
          ? "提示词正文可改；{变量} 占位符不可增删（保存时校验）。改动立即影响 agent 行为，建议改后到评测页跑一次意图路由评测。"
          : "JSON 词表；格式错误无法保存。"}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([]);

  const load = () => api<{ settings: Setting[] }>("/settings").then((d) => setSettings(d.settings)).catch(() => {});
  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="text-sm font-bold">设置 · 提示词与路由词表</div>
      <div className="text-xs text-muted-foreground">
        覆盖值存数据库（app_settings）；删除覆盖即回退代码默认值。改坏有校验拦截，改完建议跑评测验证。
      </div>
      <div className="mt-3 space-y-3">
        {settings.map((s) => <Editor key={s.key} s={s} onSaved={load} />)}
      </div>
    </div>
  );
}
