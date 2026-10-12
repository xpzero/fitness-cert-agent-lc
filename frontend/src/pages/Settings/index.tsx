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

/** key 前缀 -> 分区（模块域）。prompt.router → 路由模块。 */
const SECTIONS: [string, string, string][] = [
  ["router", "🧭 意图路由", "关键词快路径 / 复合信号 / LLM 路由提示词"],
  ["diagnosis", "🔍 学情诊断", "调查策略与报告合成"],
  ["tutor", "🎓 导师 agent", "会话级多工具编排"],
  ["qa", "💬 溯源问答", "查询改写（RAG 入口）"],
  ["quizgen", "✏️ 出题", "题目生成系统提示"],
];

function sectionOf(key: string) {
  const name = key.replace(/^(prompt|router)\./, "");
  for (const [prefix, label, desc] of SECTIONS) {
    if (name.startsWith(prefix)) return [prefix, label, desc] as [string, string, string];
  }
  return ["misc", "⚙️ 其他", ""];
}

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
  const [open, setOpen] = useState<string | null>(null);  // 展开的分区（默认全收起）

  const load = () => api<{ settings: Setting[] }>("/settings").then((d) => setSettings(d.settings)).catch(() => {});
  useEffect(() => { load(); }, []);

  const bySection = new Map<string, { label: string; desc: string; items: Setting[] }>();
  for (const s of settings) {
    const [prefix, label, desc] = sectionOf(s.key);
    if (!bySection.has(prefix)) bySection.set(prefix, { label, desc, items: [] });
    bySection.get(prefix)!.items.push(s);
  }

  return (
    <div>
      <div className="text-sm font-bold">设置 · 提示词与路由词表</div>
      <div className="text-xs text-muted-foreground">
        按模块分区，点击展开编辑。覆盖值存数据库（app_settings）；删除覆盖即回退代码默认值。
      </div>
      <div className="mt-3 space-y-2">
        {[...bySection.entries()].map(([prefix, sec]) => (
          <div key={prefix} className="rounded-xl border border-border bg-card">
            <button
              className="flex w-full cursor-pointer items-center gap-2 px-3.5 py-2.5 text-left"
              onClick={() => setOpen(open === prefix ? null : prefix)}
            >
              <span className="text-[13px] font-bold">{sec.label}</span>
              <span className="text-[11px] text-muted-foreground">{sec.desc}</span>
              {sec.items.some((s) => s.overridden) && (
                <Badge variant="ok">{sec.items.filter((s) => s.overridden).length} 项已覆盖</Badge>
              )}
              <span className="ml-auto text-xs text-muted-foreground">{open === prefix ? "▾" : "▸"}</span>
            </button>
            {open === prefix && (
              <div className="space-y-3 px-3.5 pb-3">
                {sec.items.map((s) => <Editor key={s.key} s={s} onSaved={load} />)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
