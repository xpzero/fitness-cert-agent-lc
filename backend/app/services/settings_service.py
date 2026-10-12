"""运行时设置：DB 覆盖层 + 代码默认值两层读取。

可编辑项分两类：
- prompts（字符串模板）：保存时校验 {变量} 占位符集合与默认值一致（防删占位符
  导致 format 崩）并试渲染；读取方经 render() 使用
- 词表（路由关键词/复合信号）：JSON 存取，格式错误拒绝保存

表：app_settings(key TEXT PK, value TEXT, updated_at)。启动 seed_defaults()
以代码默认值补齐缺失行；删除覆盖即回退默认。
"""
from __future__ import annotations

import json
import re

from app.db import database
from app.prompts import diagnosis as p_diag
from app.prompts import qa as p_qa
from app.prompts import quizgen as p_quiz
from app.prompts import router as p_router
from app.prompts import practice as p_prac
from app.prompts import planning as p_plan
from sqlalchemy import text as sql_text

# ---------------------------------------------------------------- 可编辑项注册
# key -> (类别, 默认值, 说明)。类别：prompt=字符串模板；json=结构化词表

from app.routing_tables import COMPOSITE_SIGNALS, KEYWORD_ROUTES

_SETTINGS: dict[str, dict] = {}


def _reg(key: str, category: str, default, desc: str) -> None:
    _SETTINGS[key] = {"category": category, "default": default, "desc": desc}


# 提示词（正文可改；{var} 占位符集合必须保持）
_reg("prompt.router", "prompt", p_router.ROUTER_PROMPT, "意图路由（LLM 二级）")
_reg("prompt.tutor_system", "prompt", p_router.TUTOR_SYSTEM, "导师 agent 系统提示")
_reg("prompt.diagnosis_system", "prompt", p_diag.DIAGNOSIS_SYSTEM, "学情诊断系统提示")
_reg("prompt.synthesize", "prompt", p_diag.SYNTHESIZE_PROMPT, "诊断报告合成")
_reg("prompt.qa_rewrite", "prompt", p_qa.REWRITE_PROMPT, "查询改写")
_reg("prompt.quizgen_system", "prompt", p_quiz.QUESTION_GEN_SYSTEM, "出题生成系统提示")
# 词表（JSON）
_reg("router.keywords", "json", KEYWORD_ROUTES, "意图路由关键词（intent -> 词组）")
_reg("router.composite_signals", "json", list(COMPOSITE_SIGNALS), "复合请求嫌疑信号")


def _vars_of(template: str) -> set[str]:
    return set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template))


# ---------------------------------------------------------------- API

def seed_defaults() -> int:
    """建表 + 补齐缺失的默认行。返回补齐数。"""
    from app.db import init_db

    init_db()
    added = 0
    with database.engine.begin() as conn:
        for key, spec in _SETTINGS.items():
            val = (json.dumps(spec["default"], ensure_ascii=False)
                   if spec["category"] == "json" else spec["default"])
            r = conn.execute(sql_text(
                "INSERT INTO app_settings (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO NOTHING RETURNING key"),
                {"k": key, "v": val}).first()
            if r:
                added += 1
    return added


def list_settings() -> list[dict]:
    """全部可编辑项（含当前生效值与默认值）。"""
    rows = {r[0]: r[1] for r in database.engine.connect().execute(
        sql_text("SELECT key, value FROM app_settings")).all()}
    out = []
    for key, spec in _SETTINGS.items():
        raw = rows.get(key)
        value = spec["default"]
        overridden = False
        if raw is not None:
            value = json.loads(raw) if spec["category"] == "json" else raw
            overridden = True
        out.append({"key": key, "category": spec["category"],
                    "desc": spec["desc"], "value": value,
                    "default": spec["default"], "overridden": overridden})
    return out


def _validate(key: str, value) -> None:
    spec = _SETTINGS[key]
    if spec["category"] == "prompt":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("提示词不能为空")
        if _vars_of(value) != _vars_of(spec["default"]):
            missing = _vars_of(spec["default"]) - _vars_of(value)
            extra = _vars_of(value) - _vars_of(spec["default"])
            raise ValueError(
                f"变量占位符不一致：缺少 {sorted(missing) or '无'}，多出 {sorted(extra) or '无'}"
                "（占位符不可增删改）")
        try:  # 试渲染（全部占位符给空串），语法错误当场暴露
            value.format(**{v: "" for v in _vars_of(value)})
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(f"模板语法错误：{e}")
    else:  # json 词表
        if key == "router.keywords":
            if not isinstance(value, dict) or not all(
                    isinstance(v, list) and v for v in value.values()):
                raise ValueError("关键词表须为 {{intent: [词组...]}} 且词组非空")
        elif not isinstance(value, list) or not all(isinstance(s, str) for s in value):
            raise ValueError("复合信号须为字符串数组")


def update_setting(key: str, value) -> dict:
    """保存覆盖值（校验失败抛 ValueError）。"""
    if key not in _SETTINGS:
        raise KeyError(f"未知设置项：{key}")
    _validate(key, value)
    stored = (json.dumps(value, ensure_ascii=False)
              if _SETTINGS[key]["category"] == "json" else value)
    with database.engine.begin() as conn:
        conn.execute(sql_text(
            "INSERT INTO app_settings (key, value, updated_at) "
            "VALUES (:k, :v, now()) ON CONFLICT (key) DO UPDATE "
            "SET value = :v, updated_at = now()"),
            {"k": key, "v": stored})
    return {"key": key, "saved": True}


def reset_setting(key: str) -> dict:
    """删除覆盖，回退代码默认值。"""
    if key not in _SETTINGS:
        raise KeyError(f"未知设置项：{key}")
    with database.engine.begin() as conn:
        conn.execute(sql_text("DELETE FROM app_settings WHERE key = :k"),
                     {"k": key})
    return {"key": key, "reset": True}


def get_overrides() -> dict:
    """运行时读取覆盖层：{key: value}（消费方在启动/每次调用时合并）。"""
    rows = database.engine.connect().execute(
        sql_text("SELECT key, value FROM app_settings")).all()
    out = {}
    for key, raw in rows:
        spec = _SETTINGS.get(key)
        if not spec:
            continue
        try:
            out[key] = (json.loads(raw) if spec["category"] == "json" else raw)
        except (ValueError, TypeError):
            continue  # 脏数据跳过，走默认值
    return out
