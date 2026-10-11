"""qa 子图（溯源 RAG 问答）提示词与拒答文案。"""

# 拒答信号三件套（集中在此，勿散落第二份）：
# - REFUSAL_MARKER：draft 中的哨兵串，generate_draft ↔ verify_citations 传递"材料不足"
# - REFUSAL_TEXT_PREFIX：拒答文案前缀，后端 chat.py 与前端靠它识别拒答路径
# - REFUSAL_ANSWER_TEXT：给用户看的完整拒答话术
REFUSAL_MARKER = "无法溯源"
REFUSAL_TEXT_PREFIX = "该问题暂无法"
REFUSAL_ANSWER_TEXT = (
    REFUSAL_TEXT_PREFIX
    + "在当前知识库中溯源到可靠依据（现有语料：NASM 教材、四大证核心知识点）。\n"
    "· 知识类问题：换个说法再试，或经「知识库」上传涵盖该知识点的资料后重问\n"
    "· 证书/报名等政策信息：zscx.osta.org.cn（证书查询）、tyrc.org.cn（报名，以最新公告为准）"
)

REWRITE_PROMPT = (
    "把用户问题改写为独立、完整、适合检索的中文问句，"
    "补全指代、去掉寒暄。只输出 JSON：{{\"rewritten\": \"...\"}}\n"
    "用户问题：{query}"
)

# 多轮记忆：会话内有上文时用此版——单看当前句无法解析"它/这个/刚才说的"
REWRITE_HISTORY_PROMPT = (
    "把用户问题改写为独立、完整、适合检索的中文问句，"
    "结合对话历史补全指代（如\"它/这个/刚才说的\"具体指什么）、去掉寒暄。"
    "只输出 JSON：{{\"rewritten\": \"...\"}}\n"
    "对话历史（旧→新）：\n{history}\n用户问题：{query}"
)

ENTAIL_PROMPT = (
    "依次判断每条【论断】是否被对应【材料】支持。语义一致即算支持，"
    "不要求逐字相同；论断引入材料中没有的新事实才算不支持。"
    "只输出 JSON：{{\"results\": [true/false, …]}}（共 {n} 条，按序）\n"
    "{lines}"
)

GENERATE_SYSTEM = (
    "你是健身教练考证助教。只依据给定材料回答考生问题，"
    "每个关键论断末尾标注所依据的材料编号，格式如 [chunk:doc-xxx-12]。"
    "注意：引用只标在事实性论断句末；总结、过渡、括号内的补充说明不要标。"
    "若材料不足以回答，只输出一行：" + REFUSAL_MARKER + "。不得编造。"
)
