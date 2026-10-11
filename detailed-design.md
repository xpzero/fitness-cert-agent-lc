# 健身私教考证 Agent — 细化设计方案

> 前置文档：[research-report.md](./research-report.md)（调研与功能设计）。
> 本文档回答"具体怎么做"：技术栈、目录结构、数据模型、图结构、RAG 管线、评测基建、里程碑。

---

## 1. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| Agent 框架 | **LangGraph (Python) ≥ 0.4** | 子图/supervisor/checkpoint/HITL 全覆盖 |
| LLM | 生成：**DeepSeek-V3**；轻量任务（判分自检、路由、评分）：**GLM-4-Flash / Qwen-turbo**（可配置） | 中文性价比；出题/讲解质量优先用强模型 |
| Embedding | **BGE-M3**（dense + sparse 双输出） | 中文效果好，天然支持混合检索 |
| Rerank | **BGE-reranker-v2-m3** | 中文 cross-encoder，本地可跑 |
| 向量库 | **pgvector**（与业务库同库） | 减少组件；Milvus 留作后期扩展 |
| 业务数据库 | **PostgreSQL 16** | 业务表 + pgvector + checkpoint 同库 |
| Checkpoint | `PostgresSaver`（LangGraph 官方） | 会话可恢复、HITL 中断落库 |
| 后端 | **FastAPI** + SSE 流式 | 流式输出问答/陪练事件 |
| 前端 MVP | **Streamlit**（开发期）→ **微信小程序**（参照 yu-ai-learn 的 Taro 方案） | 先验证闭环再做分发 |
| 观测 | **Langfuse**（self-host，免费） | 全链路 trace + 数据集评测 |
| 评测 | RAGAS + DeepEval + promptfoo + pytest | 见 §7 |
| 部署 | docker-compose（postgres / api / worker / web / langfuse） | 单机可跑 |
| OCR/文档 | PaddleOCR + pymupdf；字幕用 B站 CC 字幕接口 | 教材扫描件处理 |

## 2. 目录结构

```
fitness-cert-agent/
├── app/
│   ├── graphs/
│   │   ├── supervisor.py          # 主图：意图路由
│   │   ├── planning/              # 子图A 备考规划
│   │   ├── qa/                    # 子图B RAG 问答
│   │   ├── quizgen/               # 子图C 出题
│   │   ├── practice/              # 子图D 刷题/模考
│   │   └── coach/                 # 子图E 口播陪练
│   ├── rag/
│   │   ├── ingest.py              # 摄取管线（PDF/字幕/笔记 → chunks）
│   │   ├── retriever.py           # 混合检索 + rerank
│   │   ├── citation.py            # 引用校验器
│   │   └── glossary.yaml          # 术语对齐表（卧推→杠铃卧推…）
│   ├── tools/
│   │   ├── cert_lookup.py         # 官方查询入口工具（zscx/chinabba/tyrc）
│   │   ├── grader.py              # 客观题确定性判分（零 LLM）
│   │   └── sm2.py                 # SM-2 间隔重复
│   ├── models/                    # SQLAlchemy 表
│   ├── api/                       # FastAPI 路由
│   └── config.py                  # 模型/检索参数集中配置
├── knowledge/                     # 语料仓（不入库，git 管理）
│   ├── raw/                       # 原始 PDF/字幕/笔记（.gitignore 大文件）
│   ├── processed/                 # 清洗后的 markdown（带页码标记）
│   └── syllabus/                  # 各证书大纲考点树（YAML，手编）
├── eval/
│   ├── golden/                    # 金标准集（jsonl，见 §7）
│   ├── scripts/                   # recall@k / MRR / nDCG / 引用正确率
│   ├── promptfoo/                 # prompt 回归用例
│   └── report/                    # 评测报告输出
├── web/                           # Streamlit
├── tests/
├── docker-compose.yml
└── pyproject.toml
```

## 3. 数据模型（核心表）

```
certificates      证书（code, name, issuer, fee_range, official_urls jsonb）
exam_points       大纲考点树（id, cert_id, parent_id, chapter, title, weight）
                  —— knowledge/syllabus/*.yaml 导入，覆盖分析的基准
documents         语料文档（id, title, source_type[教材|大纲|字幕|笔记|百科],
                  cert_ids[], authority_level[1官方|2半官方|3补充], version_date）
chunks            切片（id, document_id, chunk_index, page_no, section_path,
                  content, embedding vector(1024), exam_point_ids[],
                  tsv tsvector）—— page_no 是引用溯源的根基
questions         题目（id, cert_id, type[single|multi|judge|case|oral],
                  stem, options jsonb, answer, explanation,
                  source_chunk_ids[], evidence_text,      # 逐字依据
                  exam_point_ids[], difficulty, origin[真题|AI生成|人工],
                  verified bool, quality_score)
user_answers      答题记录（user_id, question_id, is_correct, answer, ts）
wrong_book        错题本（user_id, question_id, sm2: ease float default 2.5,
                  interval_days int default 0, reps int, due_date date）
study_plans       学习计划（user_id, cert_id, exam_date, plan jsonb,
                  status[draft|confirmed|active], daily_tasks jsonb）
mock_exams        模考（id, user_id, question_ids[], answers jsonb, score,
                  started_at, submitted_at, report jsonb）
rubric_results    口播陪练评分（session_id, item[目标肌群|起始姿势|动作过程|
                  呼吸|保护|注意事项], score, evidence, feedback）
```

**要点**：
- `chunks.page_no` + `questions.evidence_text`（从原文逐字摘出的依据句）是"防幻觉 + 溯源"的两根柱子；
- `exam_point_ids` 连通"题目 ↔ 大纲"，支撑考点覆盖分析和薄弱点诊断；
- 所有 AI 生成内容带 `verified` 标记，未过校验不进入用户侧。

## 4. 图结构细化

### 4.0 主图 supervisor

```
State: {messages, user_profile, intent, active_subgraph_state}
nodes: load_context → classify_intent → route
edges: route -(conditional)→ [planning | qa | practice | quizgen | coach]
```
- `classify_intent` 用 GLM-4-Flash 小模型（快、便宜），返回枚举 + 置信度；低置信度走澄清追问节点。
- 每个子图是 `add_node` 进主图的独立 `StateGraph`，内部状态经 checkpoint 持久化。

### 4.1 子图A：备考规划

```
State: {profile{身份,城市,预算,每周时长,目标场馆,现证书}, cert_compare, recommended_path,
        plan, human_feedback}
nodes:
  collect_profile      # 缺字段主动追问（结构化表单优先）
  compare_certs        # 从 certificates 表 + 官方信息生成对比卡
  recommend_path       # 按画像规则+LLM 生成 1 主 1 备路径
  generate_plan        # 倒排期：exam_date → 里程碑 → 每日任务（引用 exam_points 权重）
  hitl_confirm         # interrupt()：用户确认/修改后才 status=active
  adjust_plan          # 依据模考成绩/错题热力图调计划（被模考子图触发）
```
体现能力点：**HITL interrupt**（计划确认）、**跨子图通信**（模考/刷题结果回写计划）。

### 4.2 子图B：RAG 问答（Corrective RAG 模式）

```
State: {query, rewritten, candidates, reranked, grade, draft, citations, final}
nodes:
  rewrite        # 指代消解 + 术语对齐（查 glossary.yaml）+ 拆解多问
  retrieve       # 混合检索：pgvector dense(top40) ∥ BM25 tsv(top40) → RRF 融合 → rerank top8
  grade          # 自评检索质量：{correct|ambiguous|wrong}（小模型）
  generate       # 强模型生成，强制引用 [chunk_id]
  verify         # 引用校验器：每个关键断言须被所引 chunk 蕴含（NLI 判定）
  ├─ pass  → format_answer（渲染"来源：《健身教练》P123 §3.2"）
  ├─ fix   → rewrite 改写重检（≤2 次）
  └─ fail  → 拒答节点（改推官方入口工具/提示补语料），附"本问题暂无法溯源"声明
```
- 政策/报名类 query 直接路由到 `tools/cert_lookup`（官方 URL 白名单），不走生成。
- 时效策略：authority_level=1 且 version_date 超过 12 个月的段落，回答自动附加"以官方最新公告为准 + 官方链接"。

### 4.3 子图C：AI 出题（防幻觉核心）

```
State: {target_points, draft_questions[], validated[], rejected[]}
nodes:
  pick_points    # 覆盖分析：exam_points 中被题目覆盖少的点优先（可按章节筛选）
  generate       # 每题强制产出：stem/options/answer/explanation/
                 # source_chunk_ids + evidence_text（从 chunk 逐字摘依据句）
  grounding_check# evidence_text 与 source chunk 的相似度 ≥ 0.9（模糊匹配），
                 # 且答案能由 evidence 推出（NLI）→ 不过进 reject
  dedupe         # 与 questions 表已有题做语义查重（embedding 相似 > 0.85 拒绝）
  quality_gate   # 小模型按 rubric 打分（表述清晰/答案唯一/干扰项合理），
                 # ≥4/5 入库 verified=true，否则人工审核队列
  report         # 输出本轮覆盖增量：哪些考点被新题覆盖
```
体现能力点：**校验-重试-拒绝的条件边循环**、**与库内数据闭环**。主观题（case/oral）走同一 grounding，但额外生成 `must_mention` 采分点列表（供批改重算分）。

### 4.4 子图D：刷题/模考

```
State: {mode[练习|模考|错题复习], queue[], cursor, answers, score, report}
nodes:
  select         # 练习=按 exam_point 权重+未覆盖考点；模考=按真题结构抽 100 题/120min
                 # 错题复习=sm2.due_date <= today
  serve          # 出题（客观题本地判分：选项比对，零 LLM）
  diagnose       # 按章节聚合正确率 → 薄弱点 top3
  explain        # 仅答错时调 LLM 讲题（引 source_chunk_ids 溯源）
  schedule       # 错题入 wrong_book，SM-2 更新：
                 # 答对: reps+1, interval=1→6→round(interval*ease);
                 # 答错: reps=0, interval=1, ease=max(1.3, ease-0.2)
  mock_report    # 模考报告：总分/各章得分率/通过概率(逻辑回归)/→触发规划子图 adjust_plan
```

### 4.5 子图E：口播陪练（MVP 文字输入，二期接 ASR）

> **决策（2026-10-06）：真人考官评分校准延后。** MVP 只开**建议模式**（advice，不出数值分）；
> 打分模式（score）由 feature flag 控制，待收集 30 段真人讲解 + 考官评分、一致性 r≥0.7 后再解锁。

```
State: {mode[advice|score], movement, turn_count, transcript[], rubric_checks, feedback}
nodes:
  examiner       # 考官人设：从实操题签库抽动作 → 追问链（先完整讲解→针对追问≤3轮）
  transcribe     # （二期）Paraformer ASR；MVP 直接收文本
  rubric_check   # 按官方评分表 rubric 逐项核查（目标肌群/起始姿势/动作过程/呼吸/
                 # 保护/注意事项），每项输出 {covered: bool,
                 # evidence(引用评分标准 chunk), suggestion}
  score（可选）  # 仅 score 模式注册此节点：46 分制映射打分；解锁前不存在
  debrief        # 总结报告：六项覆盖雷达 + 缺项改进建议 + 下一动作推荐
                 # advice 模式不出现"得分/预测分"字样，只谈覆盖与建议
```

### 4.6 横切

- **Checkpoint**：`PostgresSaver`，thread_id = 会话；模考中途、计划确认前均可恢复。
- **流式**：SSE 事件流（`node_start / token / citation / node_end`），前端渲染进度。
- **观测**：Langfuse trace 挂 thread_id；每次回答记录 retriever 参数与 grade 结果。

## 5. RAG 摄取管线参数

| 环节 | 参数 |
|---|---|
| 教材 PDF | PaddleOCR 扫描 → markdown（保留页码标记 `[[P123]]`）→ 按 `章节+页码` 切片 |
| 切片 | 512 token / 64 overlap；标题层级进 section_path；表格整块不切 |
| 字幕 | 按"一讲一个知识点"切，关联对应教材 chunk（视频 → 教材章节映射表） |
| 权重 | authority_level 1/2/3 在 RRF 融合时加权 ×1.3/×1.1/×0.8 |
| 元数据 | 每个人工标注 chunk 时顺手打 exam_point_ids（MVP 手工，约 300–500 条核心 chunk） |

## 6. API 概览

```
POST /chat                SSE 流式对话（入口统一走 supervisor）
POST /plan/confirm        HITL 确认（resume checkpoint）
POST /practice/answer     提交答案（同步返回判分+讲解）
POST /mock/start|submit   模考开始/交卷
POST /coach/session       陪练会话（文本）/upload_audio（二期）
GET  /coverage/{cert_id}  考点覆盖报告
GET  /wrongbook/due       今日待复习
```

## 7. 评测基建细化

### 7.1 数据集文件（全部进 git）

```
eval/golden/rag_qa.jsonl        # {query, relevant_chunk_ids[], expected_answer}
eval/golden/citation.jsonl      # {query, answer, cited_chunk_ids[], is_supported(bool)}  人工核 100 条
eval/golden/trap.jsonl          # 教材无答案/时效题 50 条 {query, should_refuse: true, fallback}
eval/golden/routing.jsonl       # {query, expected_intent} 200 条
eval/golden/oral_advice.jsonl   # 讲解文本 10–15 段 + 用户自检预期（advice 模式冒烟用）
# oral_samples.jsonl（30 段真人讲解 + 考官评分）→ 延后收集，是打分模式解锁的前置条件
eval/golden/gen_questions.jsonl # 出题校验：{exam_point_id, accepted: bool} 人工抽检
```

### 7.2 指标与门槛（每阶段验收线）

| 指标 | 计算方式 | 门槛 |
|---|---|---|
| Recall@5 / MRR | 对 rag_qa.jsonl 金标准 chunk | ≥0.85 / ≥0.7 |
| Faithfulness / Answer Relevancy | RAGAS | ≥0.9 / ≥0.85 |
| **引用正确率** | citation.jsonl 上 NLI 校验 + 人工抽检 20% | ≥0.95 |
| 拒答准确率 | trap.jsonl | ≥0.9 |
| 路由准确率 | routing.jsonl | ≥0.92 |
| 出题防幻觉率 | grounding_check 通过率 × 人工抽检准确率 | 入库题抽检 ≥0.97 |
| 口播建议质量 | 六项 rubric 覆盖率 + 评分标准引用正确率；用户自检 10 段 | 覆盖 100%；引用正确 ≥0.9 |
| 口播评分一致性 | （延后）rubric 评分 vs 考官评分 Pearson r | ≥0.7 才解锁打分模式 |
| 回归 | promptfoo + pytest（判分/SM-2 单元测试 100% 通过） | CI 必须绿 |

### 7.3 CI 流程（GitHub Actions）

```
PR → pytest(单元) → 构建索引(小样本) → eval/scripts/run_all.py
  → 生成 eval/report/{date}.md（指标表 + 与上次 diff）
  → 任一指标低于门槛 → fail
prompt 变更额外跑 promptfoo 用例
```

## 8. 里程碑（建议 8–10 周）

| 阶段 | 周 | 交付 | 验收门槛（gate） |
|---|---|---|---|
| **P0 语料与地基** | 1 | 语料仓建立、教材 OCR+切片 300+ 核心chunk、考点树 YAML、docker-compose 起 PostgreSQL+pgvector+Langfuse | 检索 Recall@5 ≥ 0.75（基线） |
| **P1 RAG 问答** | 2–3 | 子图B 完整链路（混合检索+rerank+Corrective RAG+引用校验）、Streamlit 问答页、cert_lookup 工具 | 引用正确率 ≥0.95；拒答 ≥0.9 |
| **P2 刷题闭环** | 4–5 | 题库表+判分+错题本+SM-2+薄弱点诊断；子图C 出题（grounding 检验）+ 考点覆盖报告 | 入库题抽检准确率 ≥0.97；判分/SM-2 单测 100% |
| **P3 规划+模考+陪练** | 6–7 | 子图A（含 HITL）、模考报告、子图E 口播陪练·**建议模式**（文本）、跨子图联动（模考→调计划） | 路由 ≥0.92；陪练建议覆盖 100% 且引用 ≥0.9；计划人工盲评 ≥3.5/5 |
| **P4 评测完备与打磨** | 8–9 | 金标准集、CI 全绿、Langfuse 线上观测面板、10 个种子用户内测 | 端到端任务全部达标；P95 响应 <8s |
| **P5（延后）打分模式解锁** | 内测后 | 收集 30 段真人讲解 + 考官评分、judge 校准、feature flag 解锁 score 模式 | 一致性 r≥0.7 |

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 教材版权 | 教材内容仅自建私库，不对外分发原文；产品卖点=溯源引用+生成内容；开源部分只放代码与大纲结构 |
| 真题版权 | 不做"真题库"卖点；题以 AI 生成+人工审核为主，标注 origin |
| 政策时效 | 每条政策类 chunk 带 version_date；回答强制附官方链接；cert_lookup 走白名单 |
| 评分合规 | 口播陪练上线初期只给"改进建议"不给分数，一致性达标后才开放打分 |
| 出题质量 | quality_gate + 人工审核队列双闸；verified=false 永不进用户侧 |
| 成本 | 判分/路由/自检用 Flash 级模型；embedding 本地 BGE-M3；DeepSeek 只用于生成 |

## 10. 明确不做的（MVP 边界）

- 语音输入/输出（二期）；视频动作 CV 评估（远期，参考 Fitness-AQA）
- 口播陪练"打分模式"（依赖真人考官校准，延后至 P5；MVP 只出建议不出分）

## 11. 实施偏差记录（截至 P1 完成，2026-10-06）

| 原设计 | 实际实施 | 原因 |
|---|---|---|
| BGE-M3 本地 embedding（1024d） | **bge-small-zh-v1.5 ONNX（512d）**，`EMBED_DIM` 可配 | coding-plan key 无 embedding 配额（429/1113）；fastembed 0.8 不支持 bge-m3；90MB 下载 vs 2.3GB |
| BM25（zhparser 分词） | **pg_trgm `word_similarity`** | pgvector 镜像无 zhparser；word_similarity 对"短查询 vs 长文档"区分度优于 similarity() |
| RRF 等权融合 + 权威 1.3/1.1/0.8 加权 | **dense 0.65 / sparse 0.35 加权 RRF**，权威降为 1.05/1.0/0.95 平局打破 | 实测权威强加权会把 dense 正确结果压下去（0.641→调后 0.821） |
| 单路 dense | **双路 dense（原始 + HyDE）取最优秩** | 口语化长问句 vs 教材式短文本语义错位，HyDE 桥接 |
| BGE-reranker cross-encoder | 恒等占位（接口保留） | 本地无该模型；权威+HyDE 已达标，延后 |
| glm-4.6 / glm-4-flash 同端点 | **生成 glm-4.5-air @ z.ai coding 端点；轻任务 glm-4.5-flash @ bigmodel** | coding-plan key 的模型配额矩阵（探测脚本验证）；glm-4.7 为思考模型 content 为空 |
| PostgresSaver checkpoint | P1 暂不接（单轮问答无状态） | P3 HITL/模考恢复时接入 |
| — | 服务端口 8765 / DB 5433（8000/5432 被宿主机占用）；Langfuse SDK 锁 <3（v2 服务端协议） | 本机环境约束 |

**P1 验收状态**：Recall@5 = **0.821** ✅（门槛 0.75，39 条 auto 金标准）；引用正确率正式金标准（100 条人工核）待建，当前由 verify 节点 lexical 抽查兜底。
- 真题倒卖、包过承诺（合规红线）
- 多证书全量语料：**MVP 只做新国职一个证书打透**，CBBA/NSCA 大纲结构预留（certificates/exam_points 表已多证书建模）
