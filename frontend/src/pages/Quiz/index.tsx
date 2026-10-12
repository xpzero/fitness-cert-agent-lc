import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { USER_ID } from "@/lib/constants";
import type { Question, QuizResult } from "@/lib/types";
import { MODES } from "./constants";
import { ModeTabs } from "./components/ModeTabs";
import { QuestionCard } from "./components/QuestionCard";
import { QuizToolbar } from "./components/QuizToolbar";
import { ResultDash } from "./components/ResultDash";
import { SheetNav } from "./components/SheetNav";
import { CoachPanel } from "./components/CoachPanel";
import { QuestionBrowser } from "./components/QuestionBrowser";

const FLAGGED = new Set<string>();  // 标疑（本地会话级，demo 对齐）

export default function Quiz() {
  const [mode, setMode] = useState("practice");
  const [count, setCount] = useState("5");
  const [badges, setBadges] = useState({ wrong: 0, favorites: 0 });
  const [qs, setQs] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [emptyMsg, setEmptyMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [favSet, setFavSet] = useState<Set<string>>(new Set());
  const [browsing, setBrowsing] = useState(false);  // 题库浏览视图开关

  const loadBadges = () => api("/quiz/badges?user_id=" + USER_ID).then(setBadges).catch(() => {});
  useEffect(() => { loadBadges(); start(); }, []);  // 进页即选题（默认 practice 模式）

  async function start(modeOverride?: string) {
    const d = await api<{ questions: Question[] }>("/quiz/start", {
      method: "POST", body: JSON.stringify({ user_id: USER_ID, mode: modeOverride || mode, count: +count }) });
    if (!d.questions?.length) { setEmptyMsg(`「${MODES.find((m) => m.value === (modeOverride || mode))?.label || mode}」暂无题目——先做一轮章节练习`); setQs([]); return; }
    setQs(d.questions); setAnswers({}); setIdx(0); setResult(null);
  }
  async function toggleFav(id: string) {
    const on = !(favSet.has(id));
    await api("/quiz/favorite", { method: "POST", body: JSON.stringify({ user_id: USER_ID, question_id: id, on }) });
    if (on) setFavSet(new Set(favSet).add(id)); else { const s = new Set(favSet); s.delete(id); setFavSet(s); }
    loadBadges();
  }
  function toggleFlag(id: string) {
    FLAGGED.has(id) ? FLAGGED.delete(id) : FLAGGED.add(id);
    setBadges({ ...badges });
  }

  const pick = (k: string) => {
    if (result) return;
    const q = qs[idx];
    setAnswers((a) => {
      if (q.type === "multi") {
        const cur = new Set((a[q.id] || "").split("").filter(Boolean));
        cur.has(k) ? cur.delete(k) : cur.add(k);
        return { ...a, [q.id]: [...cur].sort().join("") };
      }
      return { ...a, [q.id]: k };
    });
  };
  async function submit() {
    setBusy(true);
    const payload = qs.map((q) => ({ question_id: q.id, answer: answers[q.id] || "" }));
    setResult(await api("/quiz/submit", { method: "POST", body: JSON.stringify({ user_id: USER_ID, mode, answers: payload }) }));
    setBusy(false);
    loadBadges();
  }

  const q = qs[idx];
  const rr = result?.results.find((r) => r.question_id === q?.id);
  const sel = new Set((answers[q?.id] || "").split("").filter(Boolean));
  const corr = rr ? new Set(rr.correct_answer) : null;
  const answered = Object.keys(answers).length;
  const explain =
    (rr && result?.explanations.find((e) => e.question_id === q?.id)?.explain) || rr?.explanation || "（暂无讲解）";

  return (
    <div>
      <ModeTabs mode={mode} badges={badges} onSelect={(v) => { setMode(v); start(v); }} />

      {emptyMsg && (
        <div className="mt-2 rounded-lg border border-border bg-muted px-3 py-2.5 text-center text-xs text-muted-foreground">
          {emptyMsg}（切「章节练习」开始）
        </div>
      )}
      {browsing ? (
        <QuestionBrowser onPractice={() => setBrowsing(false)} />
      ) : (
        <>
          <QuizToolbar q={q} total={qs.length} idx={idx} answered={answered} count={count} setCount={setCount} onStart={() => start()} />
          <div className="mt-1 text-right">
            <button className="cursor-pointer text-[11px] text-primary underline-offset-2 hover:underline" onClick={() => setBrowsing(true)}>
              浏览全部题目 →
            </button>
          </div>
        </>
      )}

      {result && <ResultDash r={result} onWrong={() => { setMode("wrong_review"); start(); }} />}

      {q && (
        <QuestionCard
          q={q} sel={sel} corr={corr} rr={rr} explain={explain}
          idx={idx} total={qs.length}
          onPick={pick} onPrev={() => setIdx(idx - 1)} onNext={() => setIdx(idx + 1)}
        />
      )}

      {q && result && rr && !rr.correct && (
        <CoachPanel userId={USER_ID} questionId={q.id} />
      )}

      {qs.length > 0 && q && (
        <SheetNav
          qs={qs} answers={answers} idx={idx} result={result} busy={busy}
          favOn={favSet.has(q.id)} flagged={FLAGGED.has(q.id)}
          onJump={setIdx} onSubmit={submit}
          onToggleFav={() => toggleFav(q.id)} onToggleFlag={() => toggleFlag(q.id)}
        />
      )}
    </div>
  );
}
