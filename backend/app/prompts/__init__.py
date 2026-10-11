"""LLM 提示词集中地——按域分文件，节点函数只留业务逻辑。

约定：
- 静态指令（system prompt）直接 import 常量；
- 带运行期变量的用 `str.format` 模板（JSON 花括号写双份转义），
  在调用点 `.format(...)` 后再传给 llm_client.chat_*；
- 本包只被 app/ 其他模块 import，不反向依赖（保持无环）。
"""
