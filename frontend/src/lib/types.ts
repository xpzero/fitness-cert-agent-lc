/** 前端共享类型——与 app/api 响应结构对应（后端契约见各路由模块 docstring）。 */

// ---- 对话 ----
export type Src = { id: string; label: string; excerpt: string };
export type ChatMsg = { role: "user" | "assistant"; content: string; sources?: Src[] };
export type ChatSession = { session_id: string; title: string; n: number; last_at: string };

// ---- 刷题 ----
export type Question = { id: string; type: string; stem: string; options: Record<string, string> };
export type QuizResult = {
  results: { question_id: string; correct: boolean; user_answer: string; correct_answer: string; detail: string;
    explanation: string; source_chunk_ids: string[]; history: [number, number] }[];
  explanations: { question_id: string; explain: string }[];
  weak_points: { chapter: string; correct: number; total: number }[];
  scheduled: number;
  report: { mode: string; score: number; total: number; wrong: number; pass_line?: number;
    pass_probability?: number; plan_adjusted?: boolean; plan_adjustment?: { action: string } };
};

// ---- 知识库 ----
export type Doc = {
  file_size?: number;
  id: string; title: string; authority_level: number; status: string; filename: string;
  error: string; chunks: number; min_page: number; max_page: number;
  created_at?: string; updated_at?: string;
  job?: { phase: string; progress: number; detail: string };
};
export type ChunkRow = { id: string; page_no: number; section_path: string; content: string };
export type EvalRes = {
  ok: boolean; reason?: string; samples?: number; recall5?: number; mrr5?: number;
  misses?: { query: string; expected: string; got_top3: string[] }[];
};
export type SearchHit = {
  chunk_id: string; label: string; authority: number; score: number;
  dense_rank: number | null; sparse_rank: number | null; content: string;
};

// ---- 规划 ----
export type Overview = {
  active: boolean; exam_date?: string; days_left?: number; weekend_days?: number; week_no?: number;
  coverage?: { covered: number; total: number; pct?: number }; answered?: number; streak?: number;
  mock_trend?: number[]; trend_delta?: number;
  phases?: { name: string; weeks: string; chapters: string[] }[];
  weekly_hours?: number;
  current_phase?: { name: string; _progress: number; _cur_week: number; _span: number };
  week_tasks?: string[]; checkins?: Record<string, boolean>; adjustments?: { date: string; mock_score: number; action: string }[];
};
export type PlanPhase = { name: string; weeks: string; chapters?: string[]; daily_tasks?: string; milestone?: string };
export type PlanDraft = {
  thread_id: string; pending_confirm: boolean;
  path?: { primary: string; primary_reason: string; backup: string };
  plan?: { phases?: PlanPhase[] };
};

// ---- 学情诊断（W3）----
export type DiagStep = { tool: string; input: any; thought: string; output: string };
export type DiagFinding = {
  chapter: string; symptom: string;
  evidence: { metric: string; value: string; source_tool: string };
};
export type DiagReport = {
  findings: DiagFinding[]; suggestions: string[];
  plan_adjusted?: boolean; degraded?: boolean;
};

// ---- 讲题教练（W4）----
export type CoachMessage = { role: "user" | "coach"; content: string };
