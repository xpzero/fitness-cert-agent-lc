"""SQLAlchemy 表定义（设计文档 §3）。init_db 负责建表与索引。

chunks.embedding 使用 pgvector 的 Vector（维度由 EMBED_DIM 驱动）。

十五张表按数据流分四域（读懂本图 = 读懂系统）：

    知识域   certificates → exam_points（考点树）
             documents（生命周期）→ ingest_jobs（解析进度）→ chunks（向量+页码）
    题库域   questions（verified = 闸门结论）
    行为域   user_answers → wrong_book(SM-2) · mock_reports · favorites
             study_plans(draft→active) · study_checkins
    会话域   diagnosis_reports（调查轨迹存档）

主数据流「一道题的一生」：
    quizgen 四闸全过 → INSERT questions（verified=true）
    → /quiz/start SELECT（只取 verified）→ /quiz/submit INSERT user_answers
    → 答错 INSERT/UPDATE wrong_book（SM-2 排期）→ 模考 INSERT mock_reports
    → 教练进程内会话 → 变式题又一行 questions（结果回写原题 SM-2）
"""
from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

EMBED_DIM = settings.embed_dim  # bge-small-zh=512；换 BGE-M3 时设 EMBED_DIM=1024


class Base(DeclarativeBase):
    pass


class Certificate(Base):
    """证书主数据：planning 的 compare_certs 从这里读（空表时 SEED_CERTS 种子入库）。"""

    __tablename__ = "certificates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    issuer: Mapped[str] = mapped_column(String(128))
    fee_range: Mapped[str] = mapped_column(String(64), default="")
    official_urls: Mapped[dict] = mapped_column(JSONB, default=dict)


class Document(Base):
    """语料文档（知识库上传 / 种子摄入共用一条管线）。

    status 是解析生命周期：queued→parsing→embedding→indexed|failed，
    由 kb_worker 按相推进（细目进度在 ingest_jobs）；error 记失败原因。
    """

    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    source_type: Mapped[str] = mapped_column(String(16))       # 教材|大纲|笔记|百科
    cert_ids: Mapped[list] = mapped_column(JSONB, default=list)
    authority_level: Mapped[int] = mapped_column(Integer)      # 1 官方 2 半官方 3 补充
    version_date: Mapped[date] = mapped_column(Date, nullable=True)
    # M1：生命周期（老库行默认 indexed，兼容既有语料）
    status: Mapped[str] = mapped_column(String(16), default="indexed")  # queued|parsing|embedding|indexed|failed
    filename: Mapped[str] = mapped_column(String(256), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IngestJob(Base):
    """M2：解析任务进度（单 worker 队列，一文档一任务）。"""
    __tablename__ = "ingest_jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str] = mapped_column(String(16))     # ocr|extract|embed|done|failed（upload 阶段从未发出）
    progress: Mapped[int] = mapped_column(Integer, default=0)   # 0-100
    detail: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                 onupdate=func.now())


class Chunk(Base):
    """检索切片——RAG 的原子单位。

    id 形如 {doc_id}-{idx}；page_no/section_path 支撑引用溯源（出处脚标的根基）；
    两路检索索引在此表上：embedding HNSW 近邻（dense 语义）+ content trgm GIN（sparse 词面）。
    """

    __tablename__ = "chunks"
    # 检索索引：HNSW（dense 向量近邻）+ trgm GIN（中文 trigram 词面）。
    # 新库由 create_all 随表创建；旧库（表已存在时 create_all 跳过索引）由
    # init_db 的 CREATE INDEX IF NOT EXISTS 兜底。
    __table_args__ = (
        Index("idx_chunks_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("idx_chunks_content_trgm", "content", postgresql_using="gin",
              postgresql_ops={"content": "gin_trgm_ops"}),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # {doc_id}-{idx}
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_no: Mapped[int] = mapped_column(Integer)              # 引用溯源根基
    section_path: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text)
    exam_point_ids: Mapped[list] = mapped_column(JSONB, default=list)
    embedding = mapped_column(Vector(EMBED_DIM))


class ExamPoint(Base):
    """考点树（knowledge/syllabus/*.yaml 导入），覆盖分析的基准。

    parent_id 空为章节点、非空为叶子（出题只取叶子）；id 形如 T02.3；
    weight 为考试权重（覆盖分析里"新覆盖优先、重要考点次之"的排序依据）。
    """

    __tablename__ = "exam_points"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # T02.3
    cert_id: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[str] = mapped_column(String(16), default="")
    chapter: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class Question(Base):
    """题库。防幻觉三字段：evidence_text（逐字依据，grounding 闸校验）、
    source_chunk_ids（引用链，讲题回原文）、verified（闸门结论——
    用户侧所有查询一律带 verified 过滤，被拒的题不可见）。"""

    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    cert_id: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(8))               # single|multi|judge|case|oral
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    answer: Mapped[str] = mapped_column(String(512))
    explanation: Mapped[str] = mapped_column(Text, default="")
    source_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_text: Mapped[str] = mapped_column(Text, default="")  # 逐字依据（防幻觉柱子）
    exam_point_ids: Mapped[list] = mapped_column(JSONB, default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    origin: Mapped[str] = mapped_column(String(16), default="AI生成")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)


class UserAnswer(Base):
    """作答流水：每次提交、每题一行（practice 确定性判分写入；诊断 agent 的原始数据源）。"""

    __tablename__ = "user_answers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str] = mapped_column(String(40))
    answer: Mapped[str] = mapped_column(String(512))
    is_correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WrongBook(Base):
    """SM-2 错题本：ease/interval_days/reps/due_date 四参数即算法全部状态。

    答对推进间隔、答错重置（演进规则见 tools/sm2.py）；(user_id, question_id) 主键
    意味着每题每用户至多一行——是"状态"不是"流水"。"""

    __tablename__ = "wrong_book"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    due_date: Mapped[date] = mapped_column(Date, default=date.today)


class Favorite(Base):
    """题目收藏（M-刷题改版）。"""
    __tablename__ = "favorites"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MockReport(Base):
    """模考历史（规划驾驶舱趋势线）。"""
    __tablename__ = "mock_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    pass_probability: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StudyCheckin(Base):
    """每日任务打卡（规划驾驶舱）。"""
    __tablename__ = "study_checkins"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    task_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class StudyPlan(Base):
    """学习计划。plan 为 JSONB（phases/weekly_tasks/adjustments 等）；
    status：draft→（用户确认）→active；诊断/导师的 plan_adjust 追加 adjustments 留痕。"""

    __tablename__ = "study_plans"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    cert_id: Mapped[str] = mapped_column(String(32))
    exam_date: Mapped[date] = mapped_column(Date, nullable=True)
    plan: Mapped[dict] = mapped_column(JSONB, default=dict)    # JSONB
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|confirmed|active


class DiagnosisReport(Base):
    """学情诊断 agent 的报告存档（W3）。"""
    __tablename__ = "diagnosis_reports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    cert_id: Mapped[str] = mapped_column(String(32), default="")
    findings: Mapped[list] = mapped_column(JSONB, default=list)
    suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    steps: Mapped[list] = mapped_column(JSONB, default=list)   # agent 调查轨迹（工具+理由）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """对话历史（/chat 会话恢复）：session_id 聚合一轮对话，
    assistant 行的 sources 存引用块——刷新页面/重启后整段取回。"""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("idx_chat_messages_session", "user_id", "session_id", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(16))            # user | assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
