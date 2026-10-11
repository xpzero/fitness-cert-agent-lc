# 知识库管理升级方案（P5-M1）

> 2026-10-06　调研 + 设计。目标：把「知识库管理」tab 从只读视图升级为完整的
> 文档生命周期管理：上传 → 解析（带进度）→ 索引 → 召回评测 → 删除。

---

## 一、调研结论：同类产品的知识库管理都在做什么

| 能力 | RAGFlow | FastGPT | Dify | 我们现状 |
|---|---|---|---|---|
| 文件上传 | ✅ 多格式（PDF/DOCX/TXT），上传时选解析模板 | ✅ | ✅ | ❌ 只能改 CORPUS 代码重跑 |
| 解析状态 | ✅ 文档列表状态流转（解析中/完成/失败），可看进度 | ✅ 索引状态列 | ✅ 状态 + 元数据列 | ❌ 无 |
| 分块预览/修正 | ✅ chunk 级查看 + **人工修正** | ✅ | ✅ 分段预览 | 🟡 只读预览（已有） |
| 检索测试 | ✅ 检索测试页 | ✅ 三模式（语义/全文/混合）带分数 | ✅ 召回测试（模拟提问，按分数排序） | 🟡 检索试驾（已有，缺分数解释与模式切换） |
| **召回质量自动评测** | ❌ | ❌（官方 Issue #1191 有需求，未实现） | ❌ | 🟡 有 eval 脚本但是命令行、全库级 |
| 文档删除 | ✅ | ✅ | ✅ | ❌ |
| 元数据/权威级 | ✅ 模板/解析器选择 | 🟡 | ✅ 元数据筛选检索 | 🟡 权威级写死在 CORPUS |

**关键洞察**：召回质量**一键自动评测**是三家都没做好的空白（FastGPT 社区明确有需求）——我们已有全库级评测脚本，把它产品化到单文档粒度就是差异化亮点。

## 二、方案设计

### M1 文档生命周期（上传 + 删除 + 状态）— 建议最先做

**数据模型**（`documents` 表加列 + 新表）：
```
documents 新增列：
  status        text     -- queued | parsing | indexed | failed
  filename      text     -- 原始文件名（ uploads/ 中的落盘文件对应）
  error         text     -- 失败原因
新表 ingest_jobs：
  id uuid PK, document_id FK, phase text,   -- upload/extract/embed/index
  progress int (0-100), detail text, created_at, updated_at
```

**API**：
```
POST   /kb/upload          multipart 文件（支持多文件）+ authority_level 参数
DELETE /kb/documents/{id}  删除（见「删除保护」）
GET    /kb/documents       列表（含 status/chunk 数/权威级/页码范围）
GET    /kb/jobs/{id}       进度查询（前端轮询）
POST   /kb/reingest/{id}   重新解析（failed 后重试）
```

**上传落盘**：`uploads/` 目录（gitignore，版权边界与 knowledge/raw 一致）。
**格式支持**：`.md/.txt` 直接走 make_chunks；`.pdf` 先 pymupdf 提取文字层，
每页字符数 < 阈值（~50 字/页）判定为扫描件 → 自动转 Vision OCR 管线（M2）。

**删除保护**：删除文档前检查 `questions.source_chunk_ids` 引用——
有引用则拒删并返回引用题数（避免题库悬空）；强制删除需带 `force=true` 并把
关联题目标记 `verified=false`（下架不出现在刷题中）。

### M2 解析进度（后台任务 + 轮询）

**为什么必须异步**：扫描 PDF 的 Vision OCR 是分钟级长任务（54 页 ≈ 3-4 分钟），
embedding 120 chunks ≈ 1 分钟——不能阻塞 API 请求。

**实现**：FastAPI `BackgroundTasks` 起单 worker（`threading.Thread` + 任务队列，
同一时刻只跑一个解析任务，避免 embedding 并发争抢）；每个阶段更新
`ingest_jobs.progress`（extract 按页数百分比，embed 按 batch 百分比）；
Streamlit 用 `st.autorefresh`（或每 3s 手动刷新）轮询 `GET /kb/jobs/{id}` 渲染进度条。

**UI**：文档表格状态列显示 🟡 解析中 35%（embed 3/8） / ✅ 已索引 / ❌ 失败（重试按钮）。

### M3 召回评测（单文档一键，差异化亮点）

**流程**（对选中文档）：
1. 从该文档采样 N=8 个 chunk（长度过滤 ≥150 字）
2. LLM 为每个 chunk 生成"考生会问的问题"（复用 build_golden 逻辑）
3. 跑 hybrid_search 测 Recall@5 / MRR@5 + 未命中 case 列表
4. 结果卡片显示：指标 + 每条 miss（问题 / 期望 chunk / 实际 top3）

**API**：`POST /kb/documents/{id}/eval` → 同步返回（8 条 × 5s ≈ 40s，可接受；
超时风险用 N=6 兜底）。

**进阶（可选）**：评测历史存表，语料/参数变更后对比回归——把 CI 门槛延伸到
页面级。

### M4 检索试驾增强（小）

- 模式切换（对标 FastGPT 三模式）：仅语义 / 仅词面 / 混合（当前默认）
- 每条命中显示分数构成（dense 排名 / sparse 排名 / RRF 融合分）

### 明确不做（本轮）

- chunk 人工修正（RAGFlow 有，但涉及编辑回写 embedding 重算，价值/成本比低）
- 元数据筛选检索（Dify 有，我们的语料规模用不上）
- 多用户/权限（内测单机场景无需求）

## 三、前端「知识库管理」tab 信息架构（改版后）

```
┌ 指标卡：文档 / Chunks / 已验证题 ┐
├ 上传区：st.file_uploader（多文件） + 权威级下拉（官方/半官方/补充） ┐
├ 文档表格：文件名 | 状态(进度) | chunks | 权威级 | 操作[评测|重解析|删除] ┐
│   └ 展开行：chunk 浏览（现有能力保留）
├ 检索试驾（M4 增强）
└ 评测结果卡（M3）：Recall@5 / MRR@5 + miss 列表
```

## 四、工作量与顺序

| 里程碑 | 内容 | 估时 |
|---|---|---|
| M1 | 表结构 + upload/delete API + 文档表格 UI + 删除保护 | ~半天 |
| M2 | 后台解析 worker + jobs 进度 + 前端轮询 + 扫描 PDF 自动 OCR | ~半天 |
| M3 | 单文档召回评测（采样→生成→评测→结果卡） | ~大半天 |
| M4 | 试驾模式切换 + 分数构成 | ~2 小时 |

合计约 2 个工作日；M1+M2 交付后即达到"同类产品标配"，M3 是超配亮点。

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| OCR 长任务占满 CPU | 单 worker 队列；页数 >100 拒绝并提示分卷 |
| 删除导致题目悬空 | 删除保护 + force 下架（M1 内置） |
| 版权文件进 git | uploads/ 与 raw/ 同策略 gitignore（第一天就划界） |
| LLM 生成评测问题偶发失败 | 失败跳过并计数，样本 ≥5 才出指标 |
| Streamlit 无 websocket | 接受 3s 轮询（内测规模够用）；正式前端（Taro）再升级 |

## 来源

- RAGFlow 官方文档 <https://ragflow.com.cn/docs/>；阿里云 RAGFlow 建库流程（状态/进度）<https://help.aliyun.com/zh/aidbs/get-started/get-started-with-ai-data-preparation>；RAGFlow 四层存储与状态流转 <https://www.cnblogs.com/aifrontiers/p/23125877>
- FastGPT 搜索测试功能解析（三模式）CSDN 2024-07；FastGPT Issue #1191（召回自动评测需求）
- Dify 知识库文档（召回测试/元数据）<https://docs.dify.ai/zh/cloud/use-dify/knowledge/readme>
- 此前 UI 调研（Perplexity citations / 来源卡）见 docs/engineering-notes.md 相关记录
