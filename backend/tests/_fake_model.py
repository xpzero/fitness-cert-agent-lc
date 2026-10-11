"""Fake 工具调用模型（ChatOpenAI 子类）：按脚本吐 tool_calls，无网络。"""
import json
from typing import Any, AsyncIterator, Iterator

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


class ScriptedToolCallModel(ChatOpenAI):
    """responses 逐次返回；tool_calls 转 chunk 流（模型节点 astream/_agenerate 两路）。"""

    def __init__(self, responses: list[AIMessage], **kw: Any):
        super().__init__(api_key="fake", base_url="http://localhost:1", **kw)
        self._resp_iter = iter(responses)

    def _next_msg(self) -> AIMessage:
        return next(self._resp_iter)

    def _chunk(self, msg: AIMessage) -> AIMessageChunk:
        return AIMessageChunk(
            content=msg.content,
            tool_call_chunks=[
                {"name": tc["name"], "args": json.dumps(tc["args"], ensure_ascii=False),
                 "id": tc["id"], "index": i, "type": "tool_call_chunk"}
                for i, tc in enumerate(msg.tool_calls or [])])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next_msg())])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next_msg())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator[ChatGenerationChunk]:
        yield ChatGenerationChunk(message=self._chunk(self._next_msg()))

    def _astream(self, messages, stop=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        msg = self._next_msg()
        async def gen():
            yield ChatGenerationChunk(message=self._chunk(msg))
        return gen()
