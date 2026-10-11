.PHONY: infra api serve _serve-api _serve-web web-dev web-build web-preview test ingest \
        eval-golden eval-retrieval eval-adversarial eval-citation-golden eval-citation eval-intent

infra:            ## 启动 PostgreSQL(pgvector) + Langfuse
	docker compose up -d

api:              ## 仅启动 FastAPI :8770
	cd backend && .venv/bin/python -m uvicorn app.api.main:app --reload --port 8770

serve: web-build  ## 前后端一起跑：API :8770 + 前端 :5173（Ctrl-C 全停）
	$(MAKE) -j2 _serve-api _serve-web

_serve-api:
	cd backend && .venv/bin/python -m uvicorn app.api.main:app --port 8770 --reload

_serve-web:
	cd frontend && pnpm preview --port 5173 --strictPort

web-dev:           ## 前端开发模式（:5173 热重载，API 代理到 :8770）
	cd frontend && pnpm dev

web-build:         ## 构建前端 → frontend/dist
	cd frontend && pnpm build

web-preview:       ## 仅预览前端构建产物（:5173，API 代理到 :8770）
	cd frontend && pnpm preview --port 5173

test:             ## 单元测试
	cd backend && .venv/bin/python -m unittest discover -s tests -v

ingest:           ## 语料入库（chunk → embedding → pgvector）
	cd backend && .venv/bin/python scripts/ingest.py

eval-golden:       ## 自动构建检索金标准集
	cd backend && .venv/bin/python eval/scripts/build_golden.py

eval-retrieval:   ## 检索评测（门槛 Recall@5 ≥ 0.75）
	cd backend && .venv/bin/python eval/scripts/run_retrieval_eval.py

eval-adversarial: ## 对抗评审评测（门槛 捕获 ≥0.70、误伤 ≤0.20，需 LLM key）
	cd backend && .venv/bin/python eval/scripts/run_adversarial_eval.py

eval-citation-golden: ## 构建引用金标准（90 引用题 + 10 拒答题）
	cd backend && .venv/bin/python eval/scripts/build_citation_golden.py

eval-citation:     ## 引用正确率评测（门槛 命中 ≥0.95、拒答 ≥0.9，需 LLM key + DB）
	cd backend && .venv/bin/python eval/scripts/run_citation_eval.py

eval-intent:       ## 意图路由评测（门槛 准确率 ≥0.92，需 LLM key）
	cd backend && .venv/bin/python eval/scripts/run_intent_eval.py
