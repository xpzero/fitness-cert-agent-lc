"""集中配置：.env 加载 + 模型/检索参数。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env 不覆盖已有环境变量（override 默认 False），与容器/shell 注入的变量兼容
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Settings:
    # LLM
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    gen_api_key: str = field(default_factory=lambda: os.environ.get("GEN_API_KEY", ""))
    # fast 通道 base_url（FAST_BASE_URL），缺省沿用 GEN_BASE_URL
    fast_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "FAST_BASE_URL",
            os.environ.get("GEN_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"))
    )
    gen_model: str = field(default_factory=lambda: os.environ.get("GEN_MODEL", "glm-4.6"))
    gen_base_url: str = field(
        default_factory=lambda: os.environ.get("GEN_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    )
    fast_model: str = field(default_factory=lambda: os.environ.get("FAST_MODEL", "glm-4-flash"))
    # init_chat_model 的 provider 字符串（OpenAI 兼容协议厂商都用 "openai"+base_url；
    # 换非兼容厂商时改 .env：LLM_PROVIDER=deepseek 等，需对应 langchain-* 集成包）
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "openai"))
    # 传输层重试次数（交由 langchain 集成处理）
    llm_max_retries: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_RETRIES", "3")))

    # 数据库
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://fitness:fitness@localhost:5433/fitness"
        )
    )

    # Embedding（本地 ONNX，免 key；曾有的 zhipu API 后端因无配额已移除）
    embed_model: str = field(
        default_factory=lambda: os.environ.get("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    )
    embed_dim: int = field(default_factory=lambda: int(os.environ.get("EMBED_DIM", "512")))
    embed_batch_size: int = field(
        default_factory=lambda: int(os.environ.get("EMBED_BATCH_SIZE", "16"))
    )

    # RAG 参数（设计文档 §5）
    chunk_max_chars: int = 700
    chunk_overlap_chars: int = 90
    dense_top_k: int = 20
    sparse_top_k: int = 15
    rrf_k: int = 50
    # 混合检索最终返回条数
    search_top_k: int = 8
    # 权威融合时按语料权威级微调：1 官方 / 2 半官方 / 3 补充（只做平局打破，
    # 初版 1.3/1.1/0.8 实测会把 dense 排序的正确结果压下去——见 engineering-notes）
    authority_weights: tuple = (1.05, 1.0, 0.95)
    # 词面阈值分级回退：短口语查询与长文档的 word_similarity 普遍偏低，
    # 固定阈值会整级空手而归（前端表现为"点了没反应"）
    sparse_min_sim_ladder: tuple = (0.5, 0.35, 0.2)

    # 质量闸门（出题/引用）
    # 出题证据句与原文的最低相似度（防幻觉闸门，grounding）
    evidence_min_similarity: float = 0.9
    # 与库内已有题干 word_similarity 超过即判重复
    quiz_dedupe_similarity: float = 0.8
    # 小模型 rubric 均分门槛（低于则 verified=False 进人工队列）
    quiz_quality_min_score: float = 4.0
    # 整份草稿的引用支持率（supported/checked）放行下限（qa verify_citations）
    min_citation_support_ratio: float = 0.6
    # 出题并行：generate_drafts 线程池 worker 数（各考点独立，IO-bound）
    quizgen_parallel_workers: int = field(default_factory=lambda: int(
        os.environ.get("QUIZGEN_PARALLEL_WORKERS", "4")))
    # 自动铺题（文档 indexed 后覆盖驱动出题）：开关/目标/轮数/去抖窗口
    auto_generate_on_ingest: bool = field(default_factory=lambda: os.environ.get(
        "AUTO_GENERATE_ON_INGEST", "1") == "1")
    auto_generate_target: int = field(default_factory=lambda: int(
        os.environ.get("AUTO_GENERATE_TARGET", "24")))
    auto_generate_rounds: int = field(default_factory=lambda: int(
        os.environ.get("AUTO_GENERATE_ROUNDS", "10")))
    auto_generate_debounce: float = field(default_factory=lambda: float(
        os.environ.get("AUTO_GENERATE_DEBOUNCE", "3")))
    # 对抗评审：关 = 行为与旧闸门链完全一致（一键回退）
    adversarial_gate_enabled: bool = field(default_factory=lambda: os.environ.get(
        "ADVERSARIAL_GATE_ENABLED", "1") not in ("0", "false", "False"))
    adversarial_severity_min: float = 4.0   # 较真考生投诉的最低严重级（1-5）
    guesser_confidence_min: float = 4.0     # 蒙题考生猜中且置信度达此值 → 判可猜测
    # 学情诊断 agent：工具环最大步数（防失控；超限强制收尾）
    diagnosis_max_steps: int = field(default_factory=lambda: int(
        os.environ.get("DIAGNOSIS_MAX_STEPS", "8")))
    # 讲题教练：对话轮数上限，超限强制进入完整讲解
    coach_max_rounds: int = field(default_factory=lambda: int(
        os.environ.get("COACH_MAX_ROUNDS", "5")))
    # 意图路由：LLM 路由置信度低于此值的开放式消息交给导师 agent
    route_confidence_min: float = field(default_factory=lambda: float(
        os.environ.get("ROUTE_CONFIDENCE_MIN", "0.55")))
    # 词面快筛不过关、转 NLI 语义判定的引用句条数上限（控成本）
    nli_fallback_max_claims: int = 6
    # 单条引用句的词面支持率下限（citation.verify_claim 快筛）
    lexical_support_min: float = 0.35

    # 目录（从 backend 根解析，API 不再依赖启动时的工作目录）
    uploads_dir: Path = PROJECT_ROOT / "uploads"

    # 当前主攻证书（四大证方向）
    default_cert: str = field(
        default_factory=lambda: os.environ.get("DEFAULT_CERT", "nsca_cpt"))


settings = Settings()
