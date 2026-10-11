"""LLM 客户端（LangChain：init_chat_model 工厂 + OpenAI 兼容协议集成）。

模型分工（设计文档 P5 模式，LLMClient 的两个档位）：
- chat_gen  → 生成模型（问答/出题/讲解），GEN_MODEL + GEN_BASE_URL + GEN_API_KEY
- chat_fast → 轻模型（路由/自检/评分），FAST_MODEL + ZHIPU_BASE_URL + LLM_API_KEY
重试由集成层 max_retries 承担；配额类 429/1113 翻译为明确错误快速失败。
provider 由 settings.llm_provider 驱动（OpenAI 兼容协议厂商都用 "openai" +
base_url）；gen 侧换厂商只改 .env（GEN_MODEL/GEN_BASE_URL/GEN_API_KEY，
GEN_API_KEY 缺省时沿用 LLM_API_KEY），无需动代码。

调用方式：from app.llm import llm_client，然后 llm_client.chat_fast(...)。
"""
from __future__ import annotations

from functools import cached_property

from langchain.chat_models import init_chat_model
from langchain_core.messages import convert_to_messages

from app.config import settings


class LLMError(RuntimeError):
    pass


def _translate_error(e: Exception) -> LLMError:
    """集成层异常 → 语义化 LLMError（配额快速失败，其余归一）。"""
    import openai

    if isinstance(e, openai.RateLimitError) and "1113" in str(getattr(e, "body", "") or e):
        return LLMError(f"模型无配额（429/1113）: {str(e)[:200]}")
    return LLMError(f"LLM 调用失败: {str(e)[:200]}")


def _extra_kwargs(*, max_tokens: int | None, response_format_json: bool) -> dict:
    kw: dict = {}
    if max_tokens:
        kw["max_tokens"] = max_tokens
    if response_format_json:
        kw["response_format"] = {"type": "json_object"}
    return kw


def _require_key() -> None:
    if not settings.llm_api_key:
        raise LLMError("LLM_API_KEY 未配置（检查 .env）")


def extract_json(raw: str) -> dict:
    """健壮 JSON 提取：剥 ``` 围栏、截取首尾大括号。供出题/评分共用。"""
    import json

    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1] if text.count("```") >= 2 else text.replace("```", "")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    return json.loads(text[start:end + 1])


class LLMClient:
    """统一 LLM 入口：fast（轻任务）/ gen（生成）双档位客户端。

    客户端懒初始化（cached_property，首次调用才创建）——import 本模块
    不触发网络连接，与原 lru_cache 函数单例语义一致。
    """

    @cached_property
    def _fast(self):
        return self._make_client(settings.fast_model, settings.fast_base_url,
                                 settings.llm_api_key, timeout=60)

    @cached_property
    def _gen(self):
        return self._make_client(settings.gen_model, settings.gen_base_url,
                                 settings.gen_api_key or settings.llm_api_key,
                                 timeout=120)

    @staticmethod
    def _make_client(model: str, base_url: str, api_key: str, *, timeout: int):
        """init_chat_model 工厂：provider 来自配置，参数透传给底层集成类。"""
        return init_chat_model(
            model, model_provider=settings.llm_provider,
            base_url=base_url, api_key=api_key,
            timeout=timeout, max_retries=settings.llm_max_retries,
        )

    def _complete(self, client, messages: list[dict], *,
                  temperature: float = 0.3,
                  max_tokens: int | None = None,
                  response_format_json: bool = False) -> str:
        _require_key()
        msgs = convert_to_messages(messages)
        try:
            msg = client.invoke(msgs, temperature=temperature,
                                **_extra_kwargs(
                                    max_tokens=max_tokens,
                                    response_format_json=response_format_json))
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001 — 集成层异常统一翻译
            raise _translate_error(e) from e
        content = msg.content or ""
        if not content and msg.additional_kwargs.get("reasoning_content"):
            # 思考模型：content 被推理占满时至少把推理文本带出来
            content = str(msg.additional_kwargs["reasoning_content"])[:2000]
        return content

    # ------------------------------------------------------------ 对外入口

    def chat_fast(self, messages: list[dict], **kw) -> str:
        """轻任务（路由/自检/评分）统一入口。"""
        return self._complete(self._fast, messages, **kw)

    def chat_gen(self, messages: list[dict], **kw) -> str:
        """生成任务（问答/出题/讲解）统一入口。"""
        return self._complete(self._gen, messages, **kw)

    def chat_gen_stream(self, messages: list[dict], *, temperature: float = 0.3,
                        max_tokens: int | None = None):
        """生成任务流式入口（SSE，供 qa 子图实时输出 stream_mode=custom）：
        逐 token yield；连接重试由集成层承担，开始吐字后不再重试。"""
        _require_key()
        msgs = convert_to_messages(messages)
        try:
            for chunk in self._gen.stream(
                    msgs, temperature=temperature,
                    **_extra_kwargs(max_tokens=max_tokens,
                                    response_format_json=False)):
                token = chunk.content
                if token:
                    yield str(token)
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _translate_error(e) from e

    def chat_json(self, messages: list[dict], *, model_tier: str = "fast",
                  temperature: float = 0.1,
                  max_tokens: int | None = None,
                  response_format_json: bool = True) -> dict:
        """调用 LLM 并解析 JSON 响应——统一"拼消息→调用→剥围栏解析"仪式。

        model_tier: "fast"（轻模型，默认）| "gen"（生成模型）——是档位名，
        真实模型名在 settings.fast_model / gen_model。
        解析失败抛 ValueError/LLMError，由调用方决定降级策略。
        """
        chat_fn = self.chat_gen if model_tier == "gen" else self.chat_fast
        raw = chat_fn(messages, temperature=temperature, max_tokens=max_tokens,
                      response_format_json=response_format_json)
        return extract_json(raw)


llm_client = LLMClient()  # 进程级单例（懒初始化，首次调用才建客户端）
