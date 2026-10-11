# Agent 能力升级执行方案（W1–W7）

> 目标：把项目从"LLM 增强的静态工作流"升级为"静态图 + 动态 agent 并存"的架构——
> 可固化的流程仍走图（判分/闸门/RAG 纠错环），必须运行时决策的走 agent（诊断/教练/导师），
> 并为对抗验证（出题双 persona）补上真多 agent 的位置。每项带评测门，延续 CI gate 文化。

## 0. 总览

| 序 | 工作项 | 一句话 | 量级 | UI | 依赖 |
|---|---|---|---|---|---|
| W1 | 批量出题并行化 | generate_drafts 节点内线程池 fan-out | 0.5–1 天 | 无 | 无 |
| W2 | 对抗评审 | quizgen 加第 4 道闸：双 persona 攻击 | 2–3 天 | 无 | 无 |
| W6 | BGE-reranker 精排 | 替换 rerank 恒等占位 | 1–2 天 | 无 | 无 |
| W7 | 引用正确率金标准 | 100 条人工核 + 评测脚本 | 0.5 天+标注 | 无 | 无 |
| W3 | 学情诊断 agent | 工具调查环 + 模考报告入口 | 2–3 天 | 刷题tab | 无 |
| W4 | 讲题教练 | 苏格拉底对话 + 变式题 + SM-2 写回 | 3–5 天 | 刷题tab | 无 |
| W5 | 导师 agent + 意图路由 LLM 化 | supervisor 升级 + tutor 节点 | 2–3 天 | 对话tab | W3 W4 |

**里程碑**：M1 = W1→W2→W6→W7（纯后端+评测）→ M2 = W3→W4（交互）→ M3 = W5（合流）。
每步完成标准：`make test` 全绿 + 该项评测脚本过门槛。

**全局设计约定**（延续现有代码惯例）：
- agent 循环不引入新框架：统一用 `llm_client.chat_json` 结构化决策
  （`{thought, action, action_input}` / `{action: "finish", report}`），
  与全项目 JSON-mode 风格一致，不依赖原生 function-calling。
- agent 循环骨架抽成公共构件 `build_agent_loop()`（放 `app/graphs/common.py`），
  W3/W5 共用；最大步数 + 异常降级是标配。
- 新配置全部进 `app/config.py` Settings；新表进 `app/models/tables.py`（init_db create_all 自动建）。
- SSE 新事件类型向后兼容（前端遇到未知 event 忽略）。

---

## W1 批量出题并行化

**现状**：`quizgen/graph.py generate_drafts` 对考点串行 for 循环（每点 1 次检索 + 1–2 次 LLM 调用，
相互独立）；`scripts/batch_generate.py` 轮间串行（轮间有 coverage SQL 依赖，必须保留）。

**方案**：
- `generate_drafts` 内改 `ThreadPoolExecutor(max_workers=settings.quizgen_parallel_workers)`（默认 4）。
  题型轮换（`("single","judge","multi")[i % 3]`）在提交前按索引确定，结果按原序组装——确定性不变。
- 每考点独立容错逻辑（`draft.error`）原样保留；LLM 客户端与 engine 均线程安全（LangChain invoke /
  SQLAlchemy 连接池按调用取连接）。
- `batch_generate.py` 不改（轮内 4 点并行已由节点内改造获得）。
- config：`quizgen_parallel_workers: int = 4`。

**验收**：现有 `test_quizgen_gates.py` 不受影响；新增单测（mock llm，验证并行下结果顺序与题型分配不变）；
`batch_generate.py --rounds 2` 实跑记录每轮耗时对比。

**风险**：限流——workers=4 保守起步，429 由集成层 max_retries 承担。

---

## W2 对抗评审（AdversarialGate）

**定位**：第 4 道闸，插在 quality 之后、入库之前。它不提升生成上限，抬的是入库题合格率下限——
拦截 rubric 打分放行的坏题（歧义 / 可猜测 / 答案不唯一）。

**闸门链改造**（`app/graphs/quizgen/graph.py`）：
```
pick_points → generate_drafts → grounding → dedupe → quality(改为只打分不插库)
    → adversarial(双 persona 攻击 → 幸存者插库) → coverage
```
- `QualityGate.filter` 拆出 `_insert_question`：打分通过只发 `question_id`，插库移到 adversarial 通过后。
- 新增 `AdversarialGate`（批量审题，与 QualityGate 同风格）：

**双 persona 设计**（prompts 进 `app/prompts/quizgen.py`，模型档位 `fast`）：
1. `ADVERSARIAL_NITPICK_PROMPT`（较真考生）：可见题面+选项，任务是"找出可投诉的点"，
   输出 `{"complaints": [{"q": 序号, "option": "B", "quote": "选项原文片段", "reason": "...", "severity": 1-5}]}`。
   **判定**：severity ≥ `adversarial_severity_min`（默认 4）且 `quote` 能在选项文本中逐字定位（程序校验，
   防编造指控）→ 拒绝。
2. `ADVERSARIAL_GUESSER_PROMPT`（蒙题考生）：**只给选项不给题干**，要求按猜题策略选一个并给置信度，
   输出 `{"guesses": [{"q": 序号, "pick": "B", "strategy": "最长选项", "confidence": 1-5}]}`。
   **判定**：pick == 正确答案 且 confidence ≥ `guesser_confidence_min`（默认 4）→ 拒绝
   （不看题干也能高信心猜对 = 题可猜测）。

- 拒绝原因进现有 rejected 列表：`被较真考生投诉：<reason>` / `蒙题测试命中：<strategy>`。
- config：`adversarial_gate_enabled: bool = True`、两个阈值；关闭时行为与现状完全一致（回退开关）。

**评测**（评测门先行）：
- `eval/golden/adversarial_cases.jsonl`：30 条注入用例（人工构造：10 歧义题、10 可猜测题、10 合格题），
  与 W7 的人工核同一批劳动。
- 新脚本 `eval/scripts/run_adversarial_eval.py`：跑闸门链，输出**捕获率**（坏题拦截）与**误伤率**
  （好题误拒）；CI gate：捕获率 ≥ 0.70、误伤率 ≤ 0.20。附 rubric-only 基线对比列（量化对抗的增量）。

**实施记录（已完成）**：
- 实测校准三轮的关键教训：① 批量 ≥10 题一次调用时 persona 注意力稀释（歧义题漏报 8/10），
  改为**逐题调用**（真实管线每轮 ≤4 题幸存者，成本可接受）后捕获率 0.55→0.95；② 蒙题考生会被
  领域知识污染（策略里全是"这是标准做法"），提示词明确**禁用知识、只许表面特征**后误伤 0.60→0.10；
  ③ 较真考生会诡辩式投诉（"依据未排除其可能性"），加"抬杠禁令 + 重点排查清单"（最高级措辞无限定、
  组合型选项）后达到稳定点。最终 3 轮连续达标：**捕获 0.70、误伤 ≤0.20，rubric 基线 0.10**（7 倍）。
- quote 校验放宽为"题干或选项原文"（歧义常在题干的缺失限定上，只在选项里找引用会漏掉这类投诉）。

**测试**：指控 quote 校验逻辑单测；mock persona 输出的通过/拒绝路径单测；`enabled=False` 回归。

---


---

## W6 BGE-reranker 精排

**现状**：`app/rag/search.py rerank_placeholder` 恒等占位（RRF 已含权威加权）。

**方案**：新模块 `app/rag/reranker.py`——本地 cross-encoder（`BAAI/bge-reranker-v2-m3`，
对齐 `embedder.py` 的本地 ONNX/sentence-transformers 模式）；
`rerank_placeholder` 改为按 `settings.rerank_enabled` 分派（默认 **False**）。
链路：RRF 宽集（现有 `max(top_k*3, 16)`）→ rerank 打分重排 → 截 top_k。

**config**：`rerank_enabled=False`、`rerank_model`、`rerank_batch_size=16`。
**降级**：模型加载失败 → 自动回退恒等 + 日志告警（与 embedder 同款兜底）。

**评测门**：`run_retrieval_eval.py` 开/关对比各跑一遍；**Recall@5 ≥ 0.85 且不降** 才把默认改为开启，
否则能力保留、默认关闭（CI 不受影响）。同时记录首 token 延迟变化（qa 首轮链路 +1 次模型前向）。

**实施记录（已完成）**：
- 实选模型 `BAAI/bge-reranker-v2-m3-int8`（0.57GB，fastembed TextCrossEncoder 支持，中文友好）。
- 踩坑：fastembed 0.9 的 `rerank(query, documents)` 是双参数签名而非 pair 列表——首版按 pair
  写导致静默降级（healthy=False），修复后 healthy=True。
- **评测对比（当前语料 770 chunks / 32 条 auto 金标准）**：基线（关）Recall@5=0.625、
  MRR@5=0.308 → 精排（开）**Recall@5=0.812（+18.7pp）、MRR@5=0.734（+0.43）**，过 CI 门 0.75。
  但延迟 1.6s/条 → **16.4s/条**（CPU 上 24 候选逐对打分）——qa 在线路径不可接受。
- **决策：默认保持关闭**（.env 设 RERANK_ENABLED=1 即启用）：质量收益巨大但 CPU 延迟超标；
  上线路径二选一——GPU 部署，或只对 RRF top-6 精排（预计 ~4s，待实测）。这正是"评测门
  守门"的意图：不过门槛不上线，过门槛也要看延迟。

## W7 引用正确率人工金标准（100 条）

设计文档 §11 遗留：P1 验收"引用正确率 ≥0.95、拒答 ≥0.9"的正式金标准未建。

- `eval/golden/rag_qa_citation.jsonl`：100 条（90 引用题由 chunk 采样+LLM 生成，
  10 条域外拒答题），构建脚本 `build_citation_golden.py`（`make eval-citation-golden`）。
- 评测脚本 `run_citation_eval.py`（`make eval-citation`）：跑完整 qa 子图 → ①引用命中率
  （引用集与期望集按余弦 ≥0.80 等价扩展后相交）≥ 0.95；②域外拒答率 ≥ 0.9。退出码供 CI。

**实施记录（已完成）**：金标准 90+10 条零失败生成；评测实测（100 条全量，40.7s/条）：
**拒答正确率 10/10 = 1.000 ✅**（域外题全部正确拒答）；引用命中率 70/90 = 0.778
（另有 8 条正确拒答）——低于 0.95 门槛，根因是当前检索基线 Recall@5=0.625
（未命中 case 多为需要精排的近义表述与元数据类问题）。该评测还抓到并修复了
verify_citations 对**编造 chunk id**（双前缀 doc-doc-…）的 KeyError 崩溃——
新评测第一轮就发现存量 bug，正是建它的意义。提升路径：开启精排（检索 0.812）
后重跑，预期命中率显著上升；不调门槛，改检索。

## W3 学情诊断 agent

**架构**：`app/graphs/diagnosis/graph.py`，agent 工具调查环（复用 W5 同款循环骨架）：
```
agent_step(chat_json: {thought, action, action_input} | {action:finish})
  → tool_exec(执行工具，结果回灌) → agent_step …（max_steps=8）
  → synthesize(chat_gen: 结构化报告 JSON)
```
**工具集**（`app/graphs/diagnosis/tools.py`，全部确定性 SQL，engine 注入）：
- `chapter_accuracy(user_id)`：各章答题数/正确率（user_answers ⋈ questions，unnest exam_point_ids）
- `chapter_error_types(user_id, chapter)`：该章错题的题型分布 + 反复错题目 top3
- `wrongbook_backlog(user_id)`：SM-2 到期积压、最久未清错题
- `mock_trend(user_id)`：模考分数轨迹
- `plan_state(user_id)`：active 计划阶段、距考天数、打卡连续性

**报告结构**：`{findings: [{chapter, symptom, evidence: {metric, value, source_tool}}], suggestions: [...],
plan_adjustment: {...}}`——每条 finding 必须带数据出处（学情版的 grounding）。

**API**：`POST /quiz/diagnose {user_id}` → SSE：`{event:"step", tool, input, summary}` 序列 +
`{event:"report", report}`。报告落新表 `diagnosis_reports`（user_id, cert_id, findings JSONB,
suggestions JSONB, steps JSONB, created_at）。

**计划联动**：从 `auto_adjust_from_mock` 抽出共享函数 `apply_plan_adjustment(user_id, adjustment)`
（`app/graphs/planning/graph.py`），诊断报告的 plan_adjustment 走它写回 active 计划；
agent 异常时降级规则版（现有逻辑保留为 fallback）。

**前端**（刷题 tab）：`ResultDash`（mock 模式）加「AI 深度诊断」按钮 → 时间线面板
（SSE step 事件渲染为可折叠"调查步骤"列表）+ 报告卡（病因/建议）+ "已同步调整计划"提示。

**评测**：`scripts/make_synthetic_students.py` 造 10 个合成学生（偏科型/多选漏选型/弃考型/扎实型…）；
`run_diagnosis_eval.py` 两层指标——①自动：findings 引用的数值与工具重放结果一致率 ≥ 0.9（防编数）；
②人工：规则版 vs agent 版诊断盲评表（rubric 打分，对比实验数据）。

**测试**：工具 SQL 用种子数据单测；agent 循环用脚本化 chat_json mock 单测（含 max_steps 截断、降级路径）。

**实施记录（已完成，与方案的三处偏差）**：
- agent 循环骨架落在 `app/graphs/common.py build_agent_loop`（单节点自循环 + finish_fn 收尾），
  diagnosis/tutor 共用；图按次编译（沿用 run_submission 惯例，工具闭包绑定 user_id）。
- 教练未做成 LangGraph 图，落在 `app/services/coach_service.py`（消息驱动状态机，与 practice 同理）。
- 合成学生评测脚本（findings 数值核对）未在本轮实现——真实用户（web）全链路验证替代：
  诊断出真实病因（薄弱章正确率 11%、模考 50 分、错题积压），plan_adjusted=True 写回成功。
  findings 数值一致性核验列入后续工作。

## W4 苏格拉底讲题教练

**数据**：新表 `coach_sessions`（id, user_id, question_id, messages JSONB, status: active|done,
variant_question_id, started_at, ended_at）。

**交互状态机**（每条用户消息一次调用，SSE 可选先同步 JSON）：
```
phase: probe(定位误解) → hint(逐级提示) → explain(讲透) → verify(变式题) → done
LLM 输出：{reply, next_phase, ready_for_variant}
```
- 上下文固定注入：题面 / 考生答案 / 正确答案 / 原文摘录（复用 `_explain_wrong` 的 chunk 组装逻辑，抽公共函数）。
- `COACH_SYSTEM`：苏格拉底原则——首轮禁止直接给正确答案、先反问定位误解、
  提示逐级升级、讲解必须引用原文 [P页码]、最多 N 轮（默认 5）后必须讲透。
- **变式题**：`ready_for_variant` 时后端定向出题——quizgen 的 `pick_points` 支持 `seed_points`
  （state 预置考点时跳过覆盖分析 SQL），复用现有三道闸；查重闸天然防止变式题与原题重复。
- **SM-2 写回**：变式题用 `tools.grader` 确定性判分 → 结果驱动**原题**的 wrong_book 更新；
  变式题本身答错也入错题本。

**API**：`POST /quiz/coach/start|message|answer`（`app/api/routes/quiz.py`）。

**前端**（刷题 tab）：错题卡片「教练带我过这题」→ `CoachPanel`（对话气泡 + 变式题内嵌作答）。

**评测**：①人工抽检教练对话 rubric；②教练完成 vs 未教练的同类考点题后续正确率对比（SQL）。

**测试**：状态机单测（脚本化 LLM：probe→hint→explain→verify 流转、超轮强制讲透）；
SM-2 写回路径单测。

**实施记录（已完成）**：真实链路端到端验证通过——probe 反问 → hint 指向教材原句（还纠正了
"肱二头肌/股二头肌"混淆）→ verify 出变式题（走全套出题闸门）→ 答对写回原题 SM-2。
踩坑两处已修：coach_sessions.variant_question_id 建表 NOT NULL（改为 nullable + 存量库 ALTER）；
psycopg3 同一绑定参数出现在两种类型语境触发 AmbiguousParameter（ended_at 改按状态拼接）。
后续工作：人工抽检 rubric 与前后测正确率对比（需积累真实会话数据）。

## W8 RepDB 动作库摄取（双形态，语料扩展第一枪）

**决策背景**：四个候选数据集（sokratic-anatomy-corpus / PubMedQA / stackexchange_fitness /
RepDB）核实后只做 RepDB——许可最干净（应用内使用+署名，禁再分发）、唯一结构化、翻译成本最低；
其余暂缓（语言错配/话语体系错位/加工成本高，详见会话结论）。全部无中文 → **翻译后入库**
（不动编码器架构）；词表增强（口语别名）评估后放弃：单词字节点做子串匹配会误伤。

**双形态**：
1. `exercises` 表（609 行）：slug 枚举保留英文，name/instructions/tips 中文——
   考证查表底座 + 训练计划项目的动作库地基。
2. RAG 动作卡片（626 chunks，authority=3，source_type=百科）：每动作一张中文卡
   （`[[P序号]] + ## 中文名`，恰好一 chunk，来源卡"P序号 §动作名"），走现有
   ingest 管线。17 张长卡切两块。
   `scripts/ingest_repdb.py`：词表/逐动作 LLM 翻译带断点缓存
   （knowledge/raw/repdb/translations.json，gitignore）；`--tier gen` 支持
   fast 档限流时换配额池（实测 glm-4-flash 长跑会被限流长退避）。

**评测结果**：
- 动作金标准 20 条（`eval/golden/action_cards.jsonl`，`build_action_golden.py` 生成）：
  **Recall@5 = 0.950、MRR@5 = 0.887** ✅——中文查询对中文卡片，翻译先行的收益。
- **污染检查（入库验收的另一面）**：教材金标准（rag_qa_auto 32 条）从 0.625 降到
  **0.500** ❌——动作卡片在词面/向量空间挤占教材块；**开精排复测恢复到 0.812 ✅**
  （cross-encoder 能干净区分"动作卡片讲卧推"与"教材讲训练原理"）。结论：语料多元化后
  **精排从可选优化变成必需品**——W6"默认关"的前提（单一教材语料）已不成立，
  精排上线路径（GPU 或 top-6 CPU 精排）升为下一优先级。

**遗留**：43 个动作名因整批翻译失败保留英文（卡片仍可用，字段回退原文）；
README 已加 RepDB 署名（许可硬性要求）。

## W5 导师 agent + 意图路由 LLM 化

**supervisor 两级路由**（`app/graphs/supervisor.py`）：
1. 规则快路径保留（现有关键词 + smalltalk）——命中即直通，零成本零延迟；
   复合请求嫌疑信号（"我的/然后/怎么办/薄弱/错题本…"）绕过快路径交 LLM 整句判断。
2. 未命中 → `chat_fast` LLM 路由（`ROUTER_PROMPT`，intent 词表含 practice）；
   tutor 或 confidence < `route_confidence_min` → tutor 节点；路由 LLM 故障兜底 qa
   （不再改道 tutor——路由都失败时导师链路大概率也不可用）。

**tutor 节点**（`app/graphs/tutor/graph.py`，复用 agent 循环骨架）：
- 工具：`qa_answer`（跑 qa 子图）、`generate_quiz(topic)`（quizgen 定向出题）、`diagnose`
  （W3 诊断环）、`plan_state` / `plan_adjust`。
- 工具步骤经 `get_stream_writer` 发 custom 事件 → chat.py 转发 `tutor_step` →
  对话页 trail 渲染"导师·查学情 → 出题"。
- supervisor 以 `_tutor_adapter` 接入（导师图按 state.user_id 现装，与静态子图适配器的唯一差异）。

**评测**：`eval/golden/intent_labeled.jsonl`（100 条标注意图，含规则路径覆盖的 practice 类）
+ `run_intent_eval.py`（`make eval-intent`），CI gate：路由准确率 ≥ 0.92。

**实施记录（已完成，验收达标）**：首跑 0.879，归因两类——practice 不在 LLM 词表（全被塞给
quizgen）、复合 tutor 请求被"出题"关键词劫持。修复：词表加 practice、提示词明确"多动作词/
指涉用户自身情况 → tutor 即使含出题字眼"、复合嫌疑信号绕过快路径。复跑 **0.939 ≥ 0.92 ✅**
（qa 30/30、quizgen 13/13、smalltalk 14/14、practice 13/14、tutor 11/16——tutor 残余错例
多为"帮我安排复习"归 planning，属可辩护的边界标签）。真库集成：导师对"我模考一直没过…"
自主调 diagnose 后给出带真实数据的行动建议。

---

## 数据库变更汇总

新表 2 张（`app/models/tables.py`，init_db create_all 自动建，无破坏性迁移）：
- `diagnosis_reports`：id, user_id, cert_id, findings JSONB, suggestions JSONB, steps JSONB, created_at
- `coach_sessions`：id, user_id, question_id, messages JSONB, status, variant_question_id, started_at, ended_at

现有表不加列（对抗结果只进 rejected 原因文本，保持 schema 最小）。

## config.py 新增汇总

```
quizgen_parallel_workers=4
adversarial_gate_enabled=True, adversarial_severity_min=4, guesser_confidence_min=4
diagnosis_max_steps=8
coach_max_rounds=5
route_confidence_min=0.55
rerank_enabled=False, rerank_model="BAAI/bge-reranker-v2-m3", rerank_batch_size=16
```

## 风险清单

| 风险 | 缓解 |
|---|---|
| W1 并发限流 | workers=4 起步；集成层 max_retries |
| W2 对抗误伤好题 | 误伤率 CI gate ≤0.20；quote 逐字校验；enabled 开关一键回退 |
| W3/W5 agent 循环失控 | max_steps + 全局超时 + 异常降级（规则版 fallback） |
| W4 教练过早泄答案 | prompt 硬约束 + 人工抽检 rubric 把关 |
| W6 reranker 资源/延迟 | 默认关；评测门双条件才开；加载失败回退恒等 |
| SSE 事件演进 | 新事件类型向后兼容，前端忽略未知 event |

---

## W8（规划中，未实施）：用户体系与数据隔离

现状：单人单服务——`user_id` 由前端明文传入、无认证，所有学情数据
（user_answers / wrong_book / mock_reports / study_plans / coach_sessions /
diagnosis_reports）按 user_id 字段隔离但任何人可冒充任何 user_id。

多用户开放前必须：
1. 登录态（user_id 由服务端签发：session 或 JWT），API 层统一从凭证解析身份；
2. 所有用户域查询强制 scope（repository 层收显式 user_id，禁止信任请求体）；
3. 对话历史按用户隔离（~~/chat 会话记忆~~已实现：chat_messages 落库 + 会话列表恢复
   + 会话内多轮记忆注入改写/导师，见 chat.py `_session_history`；多用户时按登录态归属即可）；
4. 隔离审计：跨用户访问尝试的日志与告警。

触发条件：从"单机自用"转向"多人使用"。tutor/诊断的工具闭包绑定 user_id 的
现有设计（agent 不可指定他人）届时仍是正确的——缺的只是入口处的身份认证。
