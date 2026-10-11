"""API 请求模型集中地（响应仍为裸 dict——前端契约以 README/设计文档为准）。"""
from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    user_id: str = "dev"
    message: str
    session_id: str = ""        # 前端会话 id（空则服务端新生成；历史按它落库）


class PlanStartRequest(BaseModel):
    user_id: str = "dev"
    profile: dict                # {identity, city, budget, weekly_hours, exam_date, goal_venue}


class PlanConfirmRequest(BaseModel):
    thread_id: str
    approve: bool
    feedback: str = ""


class QuizStartRequest(BaseModel):
    user_id: str = "dev"
    mode: str = "practice"       # practice | mock | wrong_review | favorites
    cert_id: str = ""
    count: int = 5


class QuizSubmitRequest(BaseModel):
    user_id: str = "dev"
    mode: str = "practice"
    answers: list[dict]             # [{question_id, answer}]


class FavoriteRequest(BaseModel):
    user_id: str = "streamlit"
    question_id: str
    on: bool


class DiagnoseRequest(BaseModel):
    user_id: str = "web"
    cert_id: str = ""


class CoachStartRequest(BaseModel):
    user_id: str = "web"
    question_id: str


class CoachMessageRequest(BaseModel):
    session_id: str
    text: str


class CoachAnswerRequest(BaseModel):
    session_id: str
    answer: str


class CheckinRequest(BaseModel):
    user_id: str = "streamlit"
    task_no: int
    done: bool


QUIZ_MODES = ("practice", "mock", "wrong_review", "favorites")
