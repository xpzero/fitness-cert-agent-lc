"""FastAPI 入口：app 工厂 + lifespan（建表/恢复解析队列）。

端点按域拆分在 app/api/routes/，业务逻辑下沉在 app/services/；
本文件不承载任何端点逻辑。前端独立部署于 frontend/（dev/preview 经
vite 代理转发 API 到 :8770），后端不托管静态资源。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """建表 + 索引补齐 + 恢复中断的解析队列。"""
    from app.db import database
    from app.kb_worker import ingest_worker

    database.init_db()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    recovered_count = ingest_worker.requeue_interrupted_documents()
    if recovered_count:
        print(f"[startup] 已恢复 {recovered_count} 个中断的解析任务")
    yield


app = FastAPI(title="fitness-cert-agent", version="0.3.0", lifespan=lifespan)

# ------------------------------------------------------------- 路由装配
from app.api.routes import chat  # noqa: E402
from app.api.routes import eval as eval_routes  # noqa: E402
from app.api.routes import kb, plan, quiz  # noqa: E402
from app.api.routes import settings as settings_routes  # noqa: E402

for _router in (chat.router, plan.router, quiz.router, kb.router,
                settings_routes.router, eval_routes.router):
    app.include_router(_router)
