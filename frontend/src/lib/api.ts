import { USER_ID } from "@/lib/constants";

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** 解析 /chat 的 SSE 流：逐事件回调（sessionId 用于服务端会话持久化） */
export async function sseChat(
  message: string,
  on: (evt: any) => void,
  userId = USER_ID,
  sessionId = "",
) {
  const resp = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, message, session_id: sessionId }),
  });
  const reader = resp.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop()!;
    for (const p of parts) {
      if (p.startsWith("data: ")) on(JSON.parse(p.slice(6)));
    }
  }
}

/** POST 任意端点并解析 SSE 流（W3 学情诊断等）：逐事件回调 */
export async function ssePost(path: string, body: any, on: (evt: any) => void) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = resp.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop()!;
    for (const p of parts) {
      if (p.startsWith("data: ")) on(JSON.parse(p.slice(6)));
    }
  }
}
