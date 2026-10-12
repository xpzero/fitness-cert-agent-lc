import { useState } from "react";
import OfficialLinks from "@/components/OfficialLinks";
import Chat from "@/pages/Chat";
import Kb from "@/pages/Kb";
import Quiz from "@/pages/Quiz";
import Plan from "@/pages/Plan";
import Settings from "@/pages/Settings";
import Eval from "@/pages/Eval";
import { cn } from "@/lib/utils";

const NAV = [
  { key: "chat", icon: "💬", label: "对话", desc: "溯源问答 · AI 导师" },
  { key: "quiz", icon: "✏️", label: "刷题", desc: "练习 · 模考 · 学情诊断" },
  { key: "plan", icon: "🗓", label: "备考规划", desc: "计划 · 打卡 · 驾驶舱" },
  { key: "kb", icon: "📚", label: "知识库", desc: "语料 · 检索试驾" },
  { key: "eval", icon: "📊", label: "评测", desc: "四套金标准 · 门槛" },
  { key: "settings", icon: "⚙️", label: "设置", desc: "提示词 · 路由词表" },
] as const;

type PageKey = (typeof NAV)[number]["key"];

const TITLES: Record<PageKey, { title: string; sub: string }> = {
  chat: { title: "对话", sub: "答案带教材出处 · 不可溯源即拒答" },
  quiz: { title: "刷题", sub: "确定性判分 · SM-2 错题排程 · 苏格拉底讲题" },
  plan: { title: "备考规划", sub: "证书对比 · 周计划 · 模考后自动调整" },
  kb: { title: "知识库", sub: "上传语料 · 混合检索 · 单文档评测" },
  eval: { title: "评测", sub: "检索 · 意图路由 · 引用 · 对抗评审" },
  settings: { title: "设置", sub: "提示词与路由词表 · DB 覆盖层" },
};

export default function App() {
  const [page, setPage] = useState<PageKey>("chat");
  const current = TITLES[page];

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 一级导航：深色侧边栏 */}
      <aside className="flex w-60 shrink-0 flex-col bg-[#0f172a] text-slate-300">
        <div className="px-5 pb-4 pt-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-lg shadow-[0_0_18px_rgba(37,99,235,0.35)]">🏋️</div>
            <div>
              <div className="text-[15px] font-bold leading-tight tracking-wide text-white">FIT·CERT</div>
              <div className="text-[10.5px] text-slate-400">健身私教考证 Agent</div>
            </div>
          </div>
        </div>
        <nav className="mt-1 flex-1 space-y-1 overflow-y-auto px-3">
          {NAV.map((n) => (
            <button
              key={n.key}
              onClick={() => setPage(n.key)}
              className={cn(
                "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                page === n.key
                  ? "bg-primary/15 text-white ring-1 ring-inset ring-primary/40"
                  : "hover:bg-white/5 hover:text-white",
              )}
            >
              <span className="text-base">{n.icon}</span>
              <span className="min-w-0">
                <span className="block text-[13.5px] font-semibold">{n.label}</span>
                <span className="block truncate text-[10.5px] text-slate-400">{n.desc}</span>
              </span>
            </button>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-3.5 text-[10.5px] leading-relaxed text-slate-500">
          四大认证 · 全语料检索
          <br />
          溯源 RAG · LangGraph · pgvector
        </div>
      </aside>

      {/* 内容区 */}
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="sticky top-0 z-10 flex items-baseline gap-3 border-b border-border bg-background/90 px-8 pb-3 pt-5 backdrop-blur">
          <h1 className="text-[20px] font-bold">{current.title}</h1>
          <span className="truncate text-[12.5px] text-muted-foreground">{current.sub}</span>
        </header>
        {/* 对话页撑满视口高度（消息区内部滚动）；其余页正常纵向滚动 */}
        <div className={cn("flex-1 px-8 py-6", page === "chat" && "flex min-h-0 flex-col overflow-hidden")}>
          {page === "chat" && <Chat />}
          {page === "quiz" && <Quiz />}
          {page === "plan" && <Plan />}
          {page === "kb" && <Kb />}
          {page === "eval" && <Eval />}
          {page === "settings" && <Settings />}
        </div>
        <OfficialLinks />
      </main>
    </div>
  );
}
