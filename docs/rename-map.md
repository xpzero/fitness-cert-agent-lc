# 命名重构映射表（rename-map）

> **执行状态（2026-10-09）：批次一～四已全部落地。** 96 个单测全绿、
> `app.api.main` 导入冒烟通过、`web` 前端构建通过、旧名残留扫描为零。
> 第 5 节外部契约项（DB 列/API 键/路由路径）**保持未改**，待拍板。
> 执行中的补充发现（已处理）：tests 对 `_insert`/`.run`/`.grounding`/`"final"`/
> `"message"`/`"cert_compare"`/`type=`/`mode=` 的直接引用已同步；
> `embedder.py` 也引用了 `zhipu_base_url`（已随改名）。

> 生成：2026-10-09，基于全部 50 个 app/*.py + tests/ + scripts/ + web/src 的逐符号审查。
> 每条连动点均已 grep 核实（行号为当日 HEAD 基准，执行时以 grep 结果为准）。
> 用途：供执行 agent 按批次直接照做。**行号可能漂移，执行每条前先 grep 现名确认。**

## 0. 执行规则

1. **批次顺序**：批次一（文件内）→ 批次二（跨文件）→ 批次三（模块改名）→ 批次四（语义修正）。
   每批完成后跑 `make test`（`.venv/bin/python -m unittest discover -s tests -v`），绿了再进下一批；每批一个 commit。
2. **不改清单**：
   - 领域惯例缩写：HyDE、NLI、RAG、HITL、SM-2、OCR、RRF 的 `k`、cert/cert_id、chunk/chunk_id、stem（题干）、rubric
   - 外部契约字符串：SSE 事件名与载荷键、API 响应键、路由路径、DB 列名、`REFUSE_PREFIX` 的**值**（`"该问题暂无法"`，chat.py:57 与前端 startswith 依赖）——统一列在第 5 节待决策，本表默认不动
   - `chat_fast` / `chat_gen` / `chat_gen_stream`（llm.py docstring 已定义 fast/gen 档位黑话，全库一致）
3. **响应键保护模式**：state 字段名与 API 响应键同名时（如 practice 的 `scheduled`），
   改 state 字段、在出口处显式映射回原响应键（见各条目注明）。
4. 每改完一个符号：`grep -rn "<旧名>" app tests scripts eval` 应只剩注释/文档中的有意引用。

---

## 1. 批次一：文件内改名（零跨文件连动）

### 1.1 app/graphs/qa/graph.py（本文件是全库命名质量最低的，收益最大）

**图节点**（节点名/边/路由映射都在本文件 `build_qa_graph` 内引用；chat.py 的 astream 未开
`subgraphs=True` 且子图经适配器 `invoke()` 调用，**节点名不会进 SSE**，改名安全）：

| 现名（节点名/函数名） | 新名 | 理由 |
|---|---|---|
| `rewrite` | `rewrite_query` | 改写的是用户查询；无宾语读不出操作对象 |
| `retrieve` | `retrieve_chunks` | 检索语料 chunk 候选 |
| `grade_retrieval`（节点名 `grade`） | `guard_no_candidates`（节点名 `guard`） | 实际只做"候选为空→wrong"短路，不做判级 |
| `generate` | `generate_draft` | 产出带引用草稿；与 quizgen 的 generate 区分 |
| `verify` | `verify_citations` | 只校验引用（存在性+支撑度） |
| `refuse` | `refuse_answer` | 写拒答文案 |
| `format` | `format_answer` | 角标化+出处清单 |
| `error_out` | `emit_error` | 透传生成端错误 |
| `after_verify` | `route_after_verify` | 路由函数，加 route_ 前缀 |

同步点（同文件）：`build_qa_graph` 的 add_node/add_edge/add_conditional_edges 映射表、
`route_after_verify` 返回的节点名字符串、模块 docstring 的主链路描述。

**state 字段**（仅本文件读写；supervisor 适配器不触碰这三个键——已核实）：

| 现名 | 新名 | 理由 |
|---|---|---|
| `grade` | `verdict` | 存的是校验结论枚举不是分数；注释同步改为 `# correct \| ambiguous \| wrong \| error`（**补上现在漏掉的 error**） |
| `rewritten` | `rewritten_query` | 分词丢宾语；与 `query` 成对 |
| `draft` | `draft_answer` | 同上 |

注意：`final`、`refused` 不在本批（跨文件/涉语义，见 2.1 与 4.6）。

**函数/局部**：

| 现名 | 新名 | 位置 |
|---|---|---|
| `_expand_glossary` | `_expand_query_with_glossary` | :89，现名读作"扩展词表本身" |
| `_glossary_pairs` | `_glossary_alias_pairs` | :84，返回 (alias, canon) 对 |
| `_llm_entail_batch(pairs)` 参数 | `claim_evidence_pairs` | :40 |
| `_llm_entail_batch` 内 `c, e` | `claim, evidence` | :51-52 |
| `base` | `rewritten_base` | rewrite 内 :108 |
| `cands` | `candidates` | retrieve :128 |
| `hyde`（局部） | `use_hyde` | retrieve :127 |
| `c`（多处循环变量） | `candidate` | :130,149,150,195,201,239 |
| `by_id`（三个节点各一处） | `candidates_by_id` | :195? :201, :239 |
| `known` | `known_chunk_ids` | verify :195 |
| `fallback_pairs` | `nli_fallback_pairs` | verify :202-211 |
| `ok` | `all_checks_passed` | verify :216-221 |
| `parts` | `token_parts` | generate :161 |
| `tok` | `token` | generate :162-165 |
| `refs` | `footnote_lines` | format :241 |
| `text`（format 内） | `draft_text` | format :240 |
| `_sentences_with(text, cid)` | `_sentences_citing(draft, chunk_id)` | :250 |

### 1.2 app/graphs/practice/graph.py

节点名（仅本文件 `build_practice_graph` 的 dict 引用；practice 不走流式）：

| 现名 | 新名 |
|---|---|
| `grade` | `grade_answers` |
| `diagnose` | `diagnose_weak_points` |
| `explain` | `explain_wrong_answers` |
| `schedule` | `schedule_reviews` |
| `report` | `build_report` |

对应函数名同步：`_grade_all`→`grade_answers`（去下划线前缀可保留，建议 `_grade_all`→`_grade_answers`）、
`_diagnose`→`_diagnose_weak_points`、`_explain`→`_explain_wrong`、`_schedule`→`_schedule_reviews`、
`_report`→`_build_report`；模块 docstring 的链路描述同步。

state/局部（`scheduled` 改名后**出口映射回原响应键**）：

| 现名 | 新名 | 位置/说明 |
|---|---|---|
| state `scheduled` | `scheduled_count` | :36；`run_submission` 初始 dict :286 与返回 :288 同步，返回键保持 `"scheduled"`（响应契约） |
| state `mode` 注释 | 补 `favorites` | :28，实际支持 4 种模式 |
| `per` | `chapter_stats` | _diagnose :120 |
| `row` | `point_row` | _diagnose :126 |
| `weak` | `weak_rows` | _diagnose :131（state 键 `weak_points` 是响应键，不动） |
| `qmap` | `questions_by_id` | :94 |
| `hist` | `history_by_question` | :89 |
| `a` / `q` / `r`（_grade_all） | `submission` / `question` / `graded` | :95-109 |
| `truth` | `answer_key` | :101-104 |
| `out` | `explanation_rows` | _explain :139 |
| `wrong` | `wrong_results` | _explain :140 |
| `text` | `explanation_text` | _explain :149-159 |
| `in_book` | `existing_sm2_row` | _schedule :176-192 |
| `rec` | `sm2_rec` | _schedule :182-199 |
| `per_chapter` | `stats_by_point_id` | _report :216（**key 是考点 id 不是章**）；输出键 `"per_question"` 是响应契约不动（待决策项 5.2） |
| `p_pass` | `pass_probability` | _report :226-236 |

### 1.3 app/graphs/quizgen/graph.py（节点名与局部）

节点名（仅本文件 build dict 引用；`batch_generate.py` 只调 `build_quizgen_graph().invoke`，不引节点名）：

| 现名（dict 键） | 新名 | 对应函数 |
|---|---|---|
| `generate` | `generate_drafts` | `generate`（函数同名改） |
| `gate` | `quality` | `quality_gate`（函数名保留） |
| `report` | `coverage` | `coverage_report`（函数名保留） |
| `grounding` / `dedupe` | 保留 | 函数 `grounding_check` 保留 |

局部：

| 现名 | 新名 | 位置 |
|---|---|---|
| `pt` | `point` | :98-102 |
| `cands` | `candidates` | :100 |
| `d`（LLM dict 处） | `resp` | :112-131（**同文件其他 6 处 `d`=QuestionDraft 改 `draft`**：:151-243） |
| `(temp, mt)` | `(temperature, max_tokens)` | :113-116 |
| `gate`（局部） | `min_quality_score` | :211-220（与门闸机制名撞车） |
| `contents` | `chunks_by_id` | :152-160 |
| `best` | `best_ratio` | :159-166 |
| `dup` | `dup_row` | :180-184 |
| `_insert` | `_insert_question` | :227 |

### 1.4 app/graphs/planning/graph.py

| 现名 | 新名 | 位置 |
|---|---|---|
| `n` | `cert_count` | _seed_certs :54 |
| `c` | `cert` | :58-64 |
| `q` | `phase_span_weeks` | generate_plan :128-136（骨架计划阶段基准周数） |
| `weak` | `weak_chapters` | auto_adjust_from_mock :180-190 |
| `action` | `action_text` | :181-183 |
| `_after_hitl` | `_route_after_hitl` | :223 |

### 1.5 app/graphs/supervisor.py

| 现名 | 新名 | 位置/说明 |
|---|---|---|
| 节点 `todo` | `fallback_notice` | :67 函数、:253 add_node、:265 条件边映射；NODE_CN 无此键（前端 trail 显示原名，见 4.7） |
| `intent_conf` | `intent_confidence` | MainState :31 + classify_intent :38-47（改前 grep tests 确认无断言） |
| `conf` | `confidence` | :39,45,47 |
| 适配器内 `result` | `subgraph_state` | :87,134,192 |
| `c`（qa 适配器） | `candidate` | :99 |
| `c`（planning 适配器） | `cert` | :152 |
| `d` | `draft` | :207-213 |
| `sg` | `subgraph` | :254-258 |

### 1.6 app/graphs/common.py

| 现名 | 新名 |
|---|---|
| `a, b` | `src, dst` |
| `fn` | `node_fn` |
| `g` | `graph` |

### 1.7 app/llm.py

| 现名 | 新名 | 位置 |
|---|---|---|
| `_complete(make=...)` 参数 | `client_factory` | :70-76（实参 `_fast_client`/`_gen_client` 位置不动） |
| `fn` | `chat_fn` | chat_json :142-143 |
| `msg` / `content` | 保留 | 语义清楚 |

### 1.8 app/rag/search.py（文件内部分）

| 现名 | 新名 | 位置/说明 |
|---|---|---|
| `rerank` | `rerank_placeholder` | :65 定义、:138 调用、:6 模块 docstring——恒等占位如实命名 |
| `_fetch` | `_fetch_rows` | :59 定义、:94,101,110 调用 |
| `authority`（局部 dict） | `authority_by_id` | :121-126 |
| `by_id` | `rows_by_chunk_id` | :129-136 |
| `mode` 参数 | → 批次二 2.9（有跨文件调用方） |

### 1.9 app/rag/embedder.py

| 现名 | 新名 | 位置 |
|---|---|---|
| `_local_model` | `_local_embedder` | :23 |
| `out` | `all_vectors` | :34 |
| `data` | `resp_json` | :49-50（避开 `data["data"]` 同名嵌套） |
| `FastEmbedAdapter` | `DualBackendEmbeddings` | :72（**已核实无外部使用点**，改名零连动） |

### 1.10 app/rag/ingest.py（模块改名见批次三；此处为文件内）

| 现名 | 新名 | 位置 |
|---|---|---|
| `_s`（`settings as _s`） | 直接用 `settings` | :76-77 |

### 1.11 app/rag/pipeline.py（文件内局部；跨文件参数见 2.11）

| 现名 | 新名 | 位置 |
|---|---|---|
| `doc` | `pdf_doc` | :43-64（避免与"知识库文档"撞名） |
| `parts` | `page_parts` | :44-65 |
| `n` | `page_count` | :46-63 |
| `done` | `translated_count` | :87-99 |
| `raw` | `summary_text` | :90-94 |
| `batch` | `batch_size` | :105-107（int，区别于 embedder 的 list） |

### 1.12 app/services/kb_service.py（文件内局部）

| 现名 | 新名 | 位置 |
|---|---|---|
| `EVAL_SAMPLE_BOUNDS` | 拆成 `EVAL_MIN_SAMPLES` / `EVAL_MAX_SAMPLES` | :21,133,140 |
| `lo, hi` | `min_samples, max_samples` | :133,140 |
| `vecs` / `all_vecs` | `sampled_chunk_vectors` / `all_chunk_vectors` | :144,159-171 |
| `cases` | `eval_cases` | :145-186 |
| `skipped` | `skipped_count` | :145-190（响应键 `"skipped"` 保留，return 处映射） |
| `q` | `question` | :148-153 |
| `expand`（闭包） | `expand_relevant_set` | :164-173 |
| `base` / `out` | `source_vector` / `equivalent_ids` | :167-172 |
| `hits5` | `hits_at_5` | :175-183 |
| `ids` | `top5_chunk_ids` | :179-181 |
| `relevant` | `relevant_chunk_ids` | :180-186 |
| `misses`（局部） | `miss_details` | :186-191（响应键 `"misses"` 保留） |
| `mrr` | `mrr_sum` | :175-190（除法前是累加和；响应键 `"mrr5"` 不动） |
| `n` | `case_count` | :188-190 |
| `refs` | `referencing_question_count` | :86-98 |
| `unverified` | `unverified_question_count` | :87-105 |
| `n`（delete 内） | `deleted_count` | :100-105 |
| `force` 参数 | `force_delete` | :83（调用方 routes/kb.py:28 位置传参，安全） |

### 1.13 app/services/plan_stats.py

| 现名 | 新名 | 位置 |
|---|---|---|
| `exam_d` | `parsed_exam_date` | :63-64 |
| `cur` | `current_phase` | :67-80 |
| `w` | `week_nums` | :42-43 |
| `answered` 参数/响应键 | 参数改 `answered_count`；**响应键 `"answered"` 保留** | :59,75（前端 Plan 页契约） |

### 1.14 app/services/quiz_stats.py

| 现名 | 新名 | 位置 |
|---|---|---|
| `badges` | `badge_counts` | :25（调用方 routes/quiz.py:58 同步，归入本批一起改） |
| `r` | `row` | :14-19 |
| `due, total` 解包 | `counts.due_count` 等属性访问（配合 2.8 NamedTuple） | :27-29 |
| 响应键 `wrong`/`wrong_total`/`favorites`/`questions`/`covered`/`total`/`covered_total`/`uncovered` | **不动**（前端契约，见 5.2） | — |

### 1.15 app/api/routes/chat.py（局部）

| 现名 | 新名 | 位置 |
|---|---|---|
| `state_in` | `initial_state` | :28 |
| `gen()` | `sse_event_stream()` | :31 |
| `streamed` | `tokens_streamed` | :35-57 |
| `mode, chunk` | `stream_mode, payload` | :37-46（LangGraph 流通道名，非业务 mode） |
| `out` | `subgraph_output` | :50-53 |
| healthz 键 `phase`/`ui`/`try` | **不动**（5.2 待决策） | :19-21 |

### 1.16 app/api/routes/plan.py（局部）

| 现名 | 新名 | 位置 |
|---|---|---|
| `g` | `graph` | :21,35 |
| `row` | `plan_row` | :49 |

### 1.17 app/tools/grader.py（参数名改动，调用方全部位置传参——已核实，安全）

| 现名 | 新名 | 位置 |
|---|---|---|
| `grade(correct_answer=...)` 参数 | `answer_key` | :75（与 `resolve_answer_key` 术语对齐） |
| `_grade_exact(user, truth)` | `(user_answer, answer_key)` | :47-50 |
| `_grade_multi(user, truth)` | `(user_answer, answer_key)` | :53-69 |
| `_DROP` | `_DROP_SEPARATORS` | :13,19 |
| `text`（normalize_answer 内） | `cleaned` | :18-23 |
| `up` | `upper` | :21-22 |
| `GradeResult.detail` | 保留（低收益；响应键 `"detail"` 同名） | — |

### 1.18 app/tools/sm2.py（`correct` 改名调用方全为位置传参——已核实）

| 现名 | 新名 | 位置 |
|---|---|---|
| `review(record, correct=...)` 参数 | `is_correct` | :34 |
| `new_record` 内 `d` | `day` | :30 |
| `is_due` 内 `due` | `due_date_str` | :63-66 |
| `to_dict` / `ease` / `reps` / `interval_days` / `from_row` | `from_row` → 批次二 2.10（practice 有调用）；其余保留 | — |

### 1.19 app/kb_worker.py（文件内部分）

| 现名 | 新名 | 位置 |
|---|---|---|
| `_process` | `_process_document` | :57,65 |
| `_update_job` | `_write_progress` | :59,79,82,87,89,93,95（名字补上"同步文档状态"的职责，docstring 已有说明） |
| `md` | `markdown_text` | :81,85 |
| `n` | `chunk_count` | :84,90 |
| `stuck` | `stuck_rows` | :45-50 |

---

## 2. 批次二：跨文件符号（逐符号连动点）

### 2.1 qa 拒答常量族（3 个常量 2 个模块，区分度重做）

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `app/prompts/qa.py:4` `REFUSE_MARK` | `REFUSAL_MARKER` | 导入：`app/graphs/qa/graph.py:26`；使用：graph.py:172,193；prompts/qa.py:23 拼接处；graph.py docstring:184 |
| `app/graphs/qa/graph.py:31` `REFUSE_PREFIX` | `REFUSAL_TEXT_PREFIX` | 导入：`app/api/routes/chat.py:12`；使用：chat.py:57；graph.py:33 拼接处、:30 注释 |
| `app/graphs/qa/graph.py:32` `REFUSE_ANSWER` | `REFUSAL_ANSWER_TEXT` | 仅 graph.py:234（文件内） |

**字符串值一律不动。** 建议同时把两个文案常量挪到 prompts/qa.py 集中（`REFUSAL_MARKER` 旁），消除"分居两模块"。

### 2.2 `QAState.final` → `final_answer`

- 定义：graph.py:78；本文件使用：:174,226,233-234,240,247
- 连动：`app/graphs/supervisor.py:111` `result.get("final")` → `result.get("final_answer")`（**subgraph_output 键保持 `"final"`**，chat.py:51 与前端不动）
- 测试：`tests/test_supervisor.py:139` `_StubGraph({"final": ...})` → 键名同步

### 2.3 `deps.get_graph()` → `get_main_graph()`

- 定义：`app/api/deps.py:12`；docstring :13
- 连动：`app/api/routes/chat.py:10` 导入、:37 调用

### 2.4 `llm.chat_json(model=...)` 参数 `model` → `model_tier`

- 定义：`app/llm.py:134`（docstring :139 同步）
- 关键字调用点（3 处）：`app/graphs/quizgen/graph.py:115`、`app/graphs/planning/graph.py:125`、`app/services/kb_service.py:151`
- 其余 4 处调用用默认值，不动；tests/test_llm_json.py 先 grep `model=` 确认

### 2.5 settings 字段（4 个）

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `config.py:23` `zhipu_base_url` | `fast_base_url` | env 读取改为 `os.environ.get("FAST_BASE_URL") or os.environ.get("ZHIPU_BASE_URL", 默认)`（仿 llm_api_key 的旧名回退模式）；使用：`app/llm.py:37`；`config.py:30` gen_base_url 的 env 回退链保留 `ZHIPU_BASE_URL` 字符串 |
| `config.py:78` `citation_support_min` | `min_citation_support_ratio` | 使用：`app/graphs/qa/graph.py:219`；**注释错位一并修**（见 4.1） |
| `config.py:79` `nli_fallback_limit` | `nli_fallback_max_claims` | 使用：`app/graphs/qa/graph.py:210` |
| `config.py:76` `quiz_quality_gate` | `quiz_quality_min_score` | 使用：`app/graphs/quizgen/graph.py:211`；grep tests 确认 |
| `config.py:62` `rerank_top_k` | `search_top_k` | 使用：`app/rag/search.py:92`（实为最终 top_k，非 rerank 截断） |

### 2.6 `rag/citation.py` 三个函数

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `check_citations_exist`（:30） | `find_missing_citations`（极性与名字一致） | 导入 `qa/graph.py:27`、使用 :196；`tests/test_rag_pure.py:3,29`；citation.py 模块 docstring:4 |
| `verbatim_in`（:57） | `verbatim_coverage` | 导入 `quizgen/graph.py:24`、使用 :159；`tests/test_verbatim.py` 8 处；citation.py docstring:6；quizgen:3 docstring |
| `verify_claim(claim, chunk_content)` 参数 | `chunk_text` | 定义 :48；调用全为位置传参（qa:206-207、tests:33-42），安全 |
| `_lexical_support(claim, evidence)` 参数 | `chunk_text`（源材料义） | 定义 :35，文件内 |
| `verbatim_in(evidence, content)` 参数 | `quote, chunk_text`（摘抄义） | 定义 :57；调用位置传参，安全 |
| 返回 dict 键 `"by"` | `"method"` | 定义 :52,54；grep 消费点（qa 只读 `["supported"]`；tests grep `"by"`） |
| `verbatim_in(threshold=0.9)` 死参数 | **删除** | 函数体从未引用；无调用方传它（已核实 quizgen/tests 均位置传参） |

### 2.7 `rrf_merge(list_weights=...)` 参数 → `channel_weights`

- 定义：`app/rag/retriever.py:18`；docstring :21,24 与循环变量 `source_w`（:32）→ `channel_weight`
- 无外部关键字调用（tests 只传 dense/sparse/authority/k/top_k——已核实）

### 2.8 `repositories` 三个裸 tuple 返回 NamedTuple 化

| 定义处 | 改法 | 连动点 |
|---|---|---|
| `coverage_totals`（:36）→ 返回 `CoverageTotals(covered_count, total_count)` | NamedTuple 定义放 repositories.py | `app/api/routes/plan.py:55`；`app/services/plan_stats.py:58` 参数注解 + :68 解包 `covered, total = ...`（NamedTuple 可解包，兼容）；`tests/test_plan_stats.py:96` 传裸 tuple 仍可跑（duck-typed），建议顺手改 |
| `wrongbook_counts`（:70）→ `WrongbookCounts(due_count, total_count)` | 同上 | `app/services/quiz_stats.py:27-28` 解包处 |
| `chunks_by_ids`（:97）→ 值类型 `ChunkRef(page_no, content)` | 同上 | 消费点改属性访问：`app/graphs/practice/graph.py:145-146`（`contents[cid][0]`→`.page_no`、`[1]`→`.content`）；`app/graphs/quizgen/graph.py:152-160`（`contents[cid][1]`→`.content`） |

配套：`today_checkins`（:63）→ `checkins_on_day`（名字写死 today 却接受任意日期）；
连动：`app/api/routes/plan.py:59`。
`exam_point_counts` 返回行里的 SQL 别名 `n` → `verified_count`（**可选**）：连动
`quiz_stats.py:18-19`（`r["n"]`）、`scripts/batch_generate.py:29-31`（`r["n"]`）。

### 2.9 `hybrid_search(mode=...)` 参数 → `retrieval_mode`

- 定义：`app/rag/search.py:86`；文件内使用 :96,106,115
- 关键字调用点：`app/api/routes/kb.py:46`（`mode=mode`；路由 query 参数 `mode` 是否改 `search_mode` 见 5.2——**本批只改函数参数**，kb.py 写成 `retrieval_mode=mode`）
- `app/rag/langchain_adapter.py`：字段 `mode`（:30）→ `retrieval_mode` + :39 传参同步；先 grep `tests/test_langchain_adapter.py` 是否构造时传 `mode=`

### 2.10 `Sm2Record.from_row` → `from_fields`

- 定义：`app/tools/sm2.py:22`（签名是 4 个散字段，名实不符）
- 连动：`app/graphs/practice/graph.py:192`

### 2.11 `pipeline.ingest_markdown` 参数 `md` → `markdown_text`、`replace` → `replace_existing`

- 定义：`app/rag/pipeline.py:68-70`
- 连动：`app/kb_worker.py:85`（`md=md` 关键字）；`scripts/ingest.py`（grep `ingest_markdown(` 与 `md=`、`replace=` 确认）
- 配套：`count_question_refs`（:135）→ `count_referencing_questions`：连动 `kb_service.py:15,86`；
  `slug_doc_id`（:24）→ `doc_id_from_title`：连动 `kb_service.py:15,43`、`scripts/ingest.py` 导入行

### 2.12 kb 侧函数与单例

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `kb_service.document_list`（:61） | `documents_overview`（返回聚合 dict 非 list） | `routes/kb.py:23` |
| `kb_service.latest_lib_recall`（:24） | `latest_lib_recall_display`（返回 str 含占位） | `kb_service.py:80`（文件内） |
| `kb_service.run_doc_eval`（:125） | `run_document_retrieval_eval` | `routes/kb.py:38`（位置传参） |
| `kb_worker.latest_job`（:115） | `get_latest_job` | `kb_service.py:78` |
| `kb_worker.worker`（:127） | `ingest_worker` | `kb_service.py:55,78,119`；`app/api/main.py:20,24` |
| `kb_worker.recover`（:42） | `requeue_interrupted_documents` | `app/api/main.py:24` |

### 2.13 quizgen 跨文件字段

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `QuestionDraft.grounding`（quizgen:45） | `grounding_score`（与 quality_score 对齐） | 本文件 :159,161-162；`scripts/batch_generate.py:53`（`d.grounding`）；`tests/test_quizgen_gates.py:58` |
| `QuestionDraft.type`（:35） | `question_type` | 本文件 :44,106?,125,237；`scripts/batch_generate.py:52`（`d.type`）；tests draft(**base) 的 base dict（grep） |
| `QuizGenState.points`（:54） | `exam_points` | 本文件 :85（写）,:98（读）；`supervisor.py:199`（初始 dict）；`scripts/batch_generate.py:56`（`state["points"]`） |
| `GroundingGate.run` / `DedupeGate.run` / `QualityGate.run` | `filter` | 定义 :151,176,196；包装节点 :248,253,258；**`tests/test_quizgen_gates.py` 9 处 `.run(` 全部同步** |

### 2.14 planning 跨文件字段

| 定义处 | 新名 | 连动点 |
|---|---|---|
| `PlanningState.message`（:33） | `final`（与 qa 统一） | 本文件 :74-78,156-160,213；`routes/plan.py:27,42`（`state.get("message")` → `"final"`；**响应键 `"message"` 保留**，构造处显式映射）；supervisor `_planning_adapter` 不读该键（已核实） |
| `PlanningState.cert_compare`（:28） | `cert_comparison`（可选，收益中等） | 本文件 :87,152-154；`supervisor.py:153`；`routes/plan.py:29`（响应键 `"cert_compare"` 保留） |

### 2.15 `GradeResult.correct` → `is_correct`

- 定义：`app/tools/grader.py:42`
- 连动：`app/graphs/practice/graph.py:105`（`r.correct` → `r.is_correct`；**results dict 的键 `"correct"` 保留**——响应契约）；`tests/test_grader.py:25,28,29,35,36`

---

## 3. 批次三：模块改名（2 个）

| 现名 | 新名 | 理由 | 连动点 |
|---|---|---|---|
| `app/rag/retriever.py` | `app/rag/fusion.py` | 文件内无检索（只有 rrf_merge 纯函数）；真检索在 search.py、真 Retriever 在 langchain_adapter.py——三名抢一 | 导入：`app/rag/search.py:18`；`tests/test_rag_pure.py:4`；docstring 重写（删除"tsvector BM25 待实现"过期声明，见 4.4） |
| `app/rag/ingest.py` | `app/rag/chunking.py` | 文件内无入库（纯文本切分）；落库在 pipeline.ingest_markdown、CLI 在 scripts/ingest.py——"ingest"三名三义 | 导入：`app/rag/pipeline.py:19`；`tests/test_ingest.py:3`；pipeline.py docstring 提及处 |

`git mv` 保留历史；改名后全库 grep `rag.retriever` / `rag.ingest` 应为零。

---

## 4. 批次四：语义/注释修正（非纯改名，含小的行为补丁）

| # | 位置 | 修正 |
|---|---|---|
| 4.1 | `config.py:77-79` | **注释错位**：`citation_support_min` 上方的"引用句 lexical 支持率下限（快筛）"描述的是 `lexical_support_min` 的职责。重写为：`min_citation_support_ratio`＝整份草稿 `supported/checked` 的放行比例下限（qa verify）；`lexical_support_min`＝单句词面快筛阈值（verify_claim）；`nli_fallback_max_claims`＝词面不过关转 NLI 的句子条数上限 |
| 4.2 | `qa/graph.py` `verdict` 注释 | 值域补 `error`（generate 服务错误分支写入，现注释遗漏） |
| 4.3 | `rag/ingest.py`（→chunking.py）`split_section` | docstring 声称"相邻标题拼接成 第三章/3.2 xxx"，实现只返回单级 `title`。改 docstring 如实描述；`Chunk.section_path` 注释同步（"当前为单级标题"）。若要真层级拼接属功能开发，不在本表 |
| 4.4 | `rag/retriever.py`（→fusion.py）docstring | 删除"数据库部分（tsvector BM25）在 P1 接库后实现"——已由 search.py 用 pg_trgm 落地，声明过期 |
| 4.5 | `rag/citation.py` `verbatim_in` | 删除死参数 `threshold`（见 2.6，随批次二做掉） |
| 4.6 | `qa/graph.py` `emit_error`（原 error_out） | `refused: True` 语义混杂（服务错误≠拒答）。最小改法：QAState 增 `error: bool = False`（supervisor 初始 dict 同步补 `error: False`），`emit_error` 返回 `{"error": True}`（不再碰 refused），`_qa_adapter` 在 subgraph_output 透传 `"error"`；chat.py 与前端本批不动（done 事件加 error 字段属前端需求，见 5.2） |
| 4.7 | `web/src/pages/Chat/index.tsx:9-12` `NODE_CN` | **死映射清理**：chat.py 的 astream 未开 `subgraphs=True` 且子图经适配器 `invoke()` 调用，`rewrite/retrieve/grade/generate/verify/format/refuse` 七个键运行时永不命中。选项 A（推荐）：键同步为批次一的新节点名并保留（将来开 subgraphs 流即生效）；选项 B：删掉死条目只留 `classify/qa/smalltalk/fallback_notice`。改前端需 `cd web && pnpm build` 验证 |
| 4.8 | `app/graphs/practice/graph.py:28` | `mode` 注释补 `favorites`（见 1.2，随批次一做掉） |
| 4.9 | `app/models/tables.py:65` `IngestJob.phase` 注释 | 值域列了 `upload`，但 kb_worker `PHASE_STATUS` 注释明言"upload 阶段从未发出"——从注释值域中删去 |

---

## 5. 待决策：外部契约（本表默认**不改**；如拍板再做，需配迁移/前端同步）

### 5.1 DB 列/表名（需 migration，涉及存量数据）

| 现名 | 问题 | 建议 |
|---|---|---|
| `questions.answer` vs `user_answers.answer` | **同词双义**（标准答案/考生作答），join 极易拿错 | `correct_answer` / `user_answer` |
| `questions.type` | 泛名 | `question_type` |
| `questions.verified` / `study_checkins.done` | 分词裸布尔 | `is_verified` / `is_done` |
| `questions.origin` | 像出处文本，实为来源分类 | `origin_type` |
| `documents.error` | 像异常对象，实为最近失败原因 | `last_error` |
| `ingest_jobs.detail` | 像结构化明细，实为一句话进度 | `progress_detail` |
| `mock_reports.total` | 与 score 并列不知所云 | `total_questions` |
| `study_plans.plan` | 表名列名同词 | `plan_data` |
| `study_checkins.day` | 脱离库内 `*_date` 惯例 | `checkin_date` |
| `wrong_book` 表名 | 全库唯一单数表 | `wrong_books` |

### 5.2 API/SSE 契约（需同步 web/src，改前 grep 对应页面）

| 键/参数 | 位置 | 问题 | 消费方 |
|---|---|---|---|
| SSE `done.final` / `node_end.node` | chat.py:60,49 | final 什么；主图节点名（classify/qa/todo…） | `web/src/pages/Chat/index.tsx` |
| `FavoriteRequest.on` + 响应 `on` | schemas.py:39 / quiz.py:52 | 布尔无宾语 | Quiz 页收藏 |
| `/quiz/favorite` 响应 `total` | quiz.py:53 | 收藏总数裸名 | Quiz 页 |
| `/quiz/badges` 响应 `wrong` | quiz_stats.py:29 | 实为**到期**错题数，与 `wrong_total` 并排易误读 | Quiz 页徽章 |
| `coverage_summary` 的 `questions`/`covered`/`total`/`covered_total`/`uncovered` | quiz_stats.py:16-22 | 名词键装整数/分词裸名 | 覆盖分析页 |
| `/plan/start` 响应 `path` | plan.py:28 | 缩写丢义（recommended_path） | Plan 页 |
| `/plan/overview` 的 `covered/total/pct/answered` | plan_stats.py:73-75 | 实为考点数 | Plan 页 |
| `/quiz/submit` 的 `results[].correct/detail/correct_answer`、`explanations[].explain`、`report.per_question`（key 实为考点 id） | practice/graph.py | explain≠explanation 两副面孔；per_question 名实不符 | Quiz 页交卷卡 |
| `/kb/search` 响应 `label`/`authority`；query 参数 `mode`/`hyde` | kb.py:42-50 | 与内部 `source_label`/`authority_level` 双轨 | Kb 页检索试驾 |
| `/kb/upload` Form 参数 `authority` | kb.py:13 | 等级非机构 | Kb 页上传表单 |
| `/kb/documents/{id}` query 参数 `force` | kb.py:27 | force 什么 | Kb 页删除确认 |
| `/kb/documents/{id}/eval` 响应 `refs_dropped`/`misses[].got_top3` | kb_service.py:105,187 | refs_dropped 实为被下架题数 | Kb 页评测卡 |
| healthz `phase`/`ui`/`try` | chat.py:19-21 | 随想式键名 | 探活脚本 |
| 路由 `/coverage/{cert_id}` | quiz.py:61 | 缺 `/quiz` 前缀 | 覆盖分析页 |
| 路由 `/kb/reingest/{doc_id}` | kb.py:31 | 脱离 `/kb/documents/{id}/` 层级 | Kb 页 |
| `REFUSE_PREFIX` 字符串值 `"该问题暂无法"` | graph.py:31 | 前端 startswith 拒答识别 | Chat 页 |

---

## 6. 验证清单（每批结束后执行）

```bash
# 1) 单测全绿
make test

# 2) 导入冒烟（图能编译、路由能装配）
.venv/bin/python -c "from app.api.deps import get_main_graph, get_plan_graph; \
  from app.graphs.qa.graph import build_qa_graph; \
  from app.graphs.practice.graph import run_submission; \
  from app.graphs.quizgen.graph import build_quizgen_graph; print('ok')"

# 3) 旧名残留扫描（应只剩第 5 节待决策项与 docstring 中有意保留者）
for s in cands check_citations_exist verbatim_in grade_retrieval REFUSE_MARK \
         REFUSE_PREFIX rerank_top_k zhipu_base_url citation_support_min \
         quiz_quality_gate nli_fallback_limit intent_conf today_checkins \
         from_row count_question_refs slug_doc_id document_list run_doc_eval \
         latest_job "\.run(" "\.grounding\b" "model=\"gen\"" get_graph ; do
  grep -rn "$s" app tests scripts eval --include="*.py" | grep -v "rename-map"
done

# 4) 模块改名后
grep -rn "rag\.retriever\|rag\.ingest" app tests scripts eval --include="*.py"

# 5) 前端若动过 NODE_CN / 契约键
cd web && pnpm build
```

## 7. 规模统计

- 批次一（文件内）：~110 处改名，覆盖 15 个文件
- 批次二（跨文件）：24 个符号，连动点 ~70 处（含 tests 12 处、scripts 2 处、main.py 2 处）
- 批次三：2 个模块改名（4 个导入点）
- 批次四：9 项语义/注释修正（含 1 项前端死映射）
- 待决策：DB 10 项、API/SSE 18 项（默认不动）
