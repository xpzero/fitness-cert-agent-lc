# 教学交接文档（fitness-cert-agent 系统课程）

> 用途：跨 session 续课。新会话读本文件即可恢复教学方案、进度与学员画像，
> 无需重讲。配套背景：README.md（项目全貌）、docs/agent-upgrade-plan.md（W1–W8）。

## 一、教学法约定（已与学员确认）

1. 每个概念固定结构：**是什么 → 为什么需要 → 代码落点（文件:行号）→ 失败了会怎样**；
2. 证据文化：论断默认带代码/命令出处；**不搞数字演算**（学员明确表示数字只用来验证"不是编造"）；
3. 自测每课 3 题、理解型；作业尽量给可直接复制的命令（学员环境常驻运行中）；
4. 每概念可配"面试官追问链"（是什么→为什么→参数哪来→失败会怎样）；
5. 讲解用具体例子和真实事故（engineering-notes 里的实录是好素材）。

## 二、学员画像（用于校准深度）

- 架构/流程/工程决策类吸收很快（单例、目录拆分、生命周期、异步队列一次讲对）；
- RAG/评测术语曾是系统性盲区，已通过 1.5 课集中补齐（RRF 量纲、bi/cross-encoder 分工、NLI 兜底均已过关）；
- 高频追问模式："数字怎么来的/为什么要这个/代码在哪能看到"——喜欢要证据；
- 会主动做自测和作业，且会拿真实输出回来对答案。

## 三、课程表与进度

| 课 | 内容 | 状态 |
|---|---|---|
| 0 | LangGraph 最小认知（状态/节点/边/条件边/compile） | ✅ 含自测批改 |
| 1 | 运行时解剖（端口/端点/deps 单例/config 旋钮/15 张表四域地图） | ✅ 含"一道题的一生" |
| 1.5 | RAG 术语与原理集中补课（embedding/HNSW/切块/双通道/HyDE/RRF/rerank/grounding/NLI/Recall@5/MRR） | ✅ 作业（curl 分数构成）已验收 |
| 2 | 知识摄入管线（kb_service/kb_worker/pipeline/embedder；异步队列、逐页OCR、[[P页码]]、幂等落库、删除引用保护） | ✅ 自测已批改；作业（上传txt→检索 dense#1）已闭环 |
| 3 | 检索与融合·源码走读（search.py/fusion.py 逐行对号 + 检索试驾三模式 + eval 脚本） | ✅ 课上现场挖出并修复 RepDB 检索域污染（见下）+ HNSW 过滤后置空集；自测/作业已布置待学员回复 |
| 4 | qa 子图逐行走读（Corrective RAG 全链 + citation.py） | ✅ 自测 2.5/3（fail-open/closed 方向、MRR 语义已过关）；作业（SSE 出处/拒答观察）已闭环 |
| 5 | quizgen 出题闸门链（四闸深讲） | ✅ 重讲版（一道题的一生+记忆锚点）通过；题型 gap 上网核实（四大证全单选）；补货/出题页一度实现后按学员决策撤回（生成=内部能力，界面只暴露消费） |
| 6 | practice + SM-2（含手算示例可略算术） | ✅ 重讲版通过：自测 2.5/3（SM-2 手算满分、wrong_review 累积语义对；N+1 位置对、修法给了反范式，已补讲批量 ANY(:ids) 与取舍）+ 作业闭环（sm2-lab 三行 ease=2.3/interval=1/reps=0/due=次日 验收通过；学员报错已诊断=仓库根目录运行致 ModuleNotFoundError） |
| 7 | 双 agent 工具环（build_agent_loop + diagnosis/tutor 源码） | ✅ 自测 3/3 批完（四出口=三位置、环内/环外判别式、递归上限 25 实测、闭包权限两理由）；作业（/quiz/diagnose SSE 轨迹）学员自验收对上 |
| 8 | planning(HITL/checkpoint) + coach 状态机 | ✅ 自测批完（恢复≠重跑已精确化；反馈链补到 generate_plan prompt:126；裁决三处 194-195·197-198·201，学员误答软侧 68·74·83 已纠正：裁决=代码否决 LLM 输出之处）；psycopg=Postgres 裸驱动、coach 对话存 coach_sessions 表非内存三问已答；作业 hitl-lab + coach 开场学员自验收对上 |
| 9 | supervisor 路由 + API/SSE 端到端 | ⬅️ **进行中**：两级路由（关键词快路径/复合信号防劫持/低置信→tutor/失败兜底qa）/适配器注册表/messages 归约器/SSE 事件协议（updates+custom 冒泡/拒答补发/final_replace）/0.939 来龙去脉已讲完；**待收自测 3 题 + 作业（跑意图评测脚本 + curl 复合请求看 tutor_step 冒泡）**，见第 9 课交付消息 |
| 10 | 评测与质量体系（四套金标准 + CI 门槛 + 合成数据的边界） | ✅ 结课（学员拍板"结束"）：四套评测总览/CI 只挂单测+检索门槛/--no-hyde 双因（无key+确定性）与盲区/等价扩展的能与不能/权威加权 vs 金标准/合成数据边界已讲透；**悬案现场判决**：本地 64,405 块实测 Recall@5=0.312 vs CI 绿（语料仅1文档），miss 分类四种病（等价更好出处/真丢失/切块相邻/auto 配对脱节+金标准跑题）——一半 miss 非检索之过。**处置未拍板**（推荐 A 重建金标准），已记 README 改进待办不丢失；eval-intent 未交不追 |
| 11 | 选修：前端结构（LangChain 适配层已随简化手术移除，仅剩 llm.py 的 init_chat_model 工厂属核心保留） | 待开 |

## 四、近期仓库大改动（新 session 需知的现状）

以下是教学期间顺手做的工程改动：

- **目录拆分**：`backend/`（app/scripts/eval/tests/knowledge/uploads/.venv/pyproject）+ `frontend/`（原 web/）；后端静态托管已删，前端 5173 走 vite 代理（API_PATHS 含 /chat /kb /quiz /plan）；Makefile/CI/README 已同步；`python-multipart` 补进了依赖。
- **对话会话持久化 + 多轮记忆**：新表 `chat_messages`；GET /chat/sessions、/chat/messages；/chat 带 session_id；历史注入主图 messages（qa 改写带历史解析指代、tutor 带上下文）。
- **教练会话恢复**：GET /quiz/coach/active；CoachPanel 挂载时续接进行中的会话。
- **动作库（已整体移除）**：第 3 课期间因检索域污染（engineering-notes #30）+ 学员反馈拉高系统复杂度，RepDB 动作库全量删除（页面/路由/表/摄取脚本/raw 数据 27MB）；删除前快照 commit `8fb1323` 可恢复。

### 简化手术（学员拍板"保留简单的设计"，继 RepDB 移除后的第二刀）

- **删检索域隔离**：documents.searchable 列、两路 SQL 的 WHERE、pipeline 参数、kb 列表字段、DB 列，全部移除（RepDB 既已不存在，闸门失去保护对象）。
- **删 HNSW iterative_scan**：SET LOCAL 行移除（它只为过滤查询而生，无过滤即无用）。
- **删 reranker 整件**（休眠脚手架：默认关、从未启用、qa 图仅注释提及）：reranker.py、Candidate.rerank_score、config 3 个旋钮、search 尾部调用；检索链终点简化为 `return candidates`，rrf_merge 直接截 top_k（原 3 倍取宽是为喂精排，一并去掉）。0.57GB 模型永远不会下载。
- **删 langchain_adapter**（零生产消费者，仅自身测试引用）：文件 + test_langchain_adapter.py + fusion docstring 提及。
- **删 action 金标准**（RepDB 孤儿）：build_action_golden.py + action_cards.jsonl。
- **保留**（查证为活跃使用）：HyDE（qa 默认开）、glossary 查询改写、kb_worker 队列、四套评测、PostgresSaver、chat 会话持久化。测试 133→128 全绿。
- 检索链最终形态：**dense(+HyDE 双路) + sparse 阶梯 → 权威加权 RRF → top 8**，无过滤无精排。
- **出题修复**：quizgen 适配器 n_points 1→2（模拟卷 3）+ 空手带 exclude_points 重试 + 诚实文案（曾因确定性选题卡死在弱考点总报"未过质量闸"）。
- **其他**：zhipu embedding 后端已删（无配额，仅本地 ONNX）；extract_text 记录 OCR 失败页号写 documents.error；出处标签带文档名（Candidate.title）；测试同步更新（133 全绿）。

### 第 3 课期间的工程改动

- **RepDB 动作库整体移除**（学员拍板）：代码/页面/表/raw 数据全删，快照 commit `8fb1323` 留档；随后第二刀简化手术（见上节）。
- **遗留**：本地检索评测 ~0.53-0.56 vs CI 绿——金标准 32 条全指向四大证（CI 语料），本地多 NASM 教材 722 块不被承认；与 RepDB 无关，处理方案留到第 10 课（评测体系）再决策。

### 第 5 课期间的工程改动

- **出题补货体系**（学员需求"至少放一题/补足 5 题/闸门细节前端不感知"）：tutor 出题工具加换考点重试（顺带修了无 seed 时 cert_id 空串选不到考点的旧 bug）；adapter 的"另有 x 题未过闸"从用户文案下沉到日志；quizgen 图加 `question_type` 定向题型（对话内「模拟卷」路径 single-only 仿真四大证笔试）。
- **出题页已撤**（学员拍板"生成是内部能力，不该展示给用户"）：曾短暂实现的 /quiz/generate SSE + quizgen_service 补货循环 + 前端出题页整体删除——用户界面只暴露消费（刷题），生成保留四个内部入口（对话路由/tutor 工具/教练变式/batch 脚本）。
- **题型核实待办**：四大证笔试均为四选一单选（上网核实），已记 README 改进待办（/quiz/start 模考抽题过滤 pending）。

## 五、恢复指令（新 session 对我说）

> 读 docs/course-handoff.md，继续上课（当前进度：第 10 课已结课，仅剩**第 11 课·选修：前端结构**——学员说"开始第 11 课"即开；说"课程结束"则收尾归档）。
> 遗留事项：① 检索金标准重建未拍板（详见 README 改进待办第三条）；② 学员未跑 make eval-intent（不追）。
