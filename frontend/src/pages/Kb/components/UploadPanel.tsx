import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";

const AUTHORITY_OPTIONS: [string, string][] = [
  ["1", "官方（1.05）　教材/大纲"],
  ["2", "半官方（1.00）　机构讲义"],
  ["3", "补充（0.95）　网络笔记"],
];

/** 上传文档：文件选择 + 权威级选择，上传后通过 onUploaded 通知刷新列表 */
export function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const [auth, setAuth] = useState("3");
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload() {
    const files = fileRef.current?.files;
    if (!files?.length) return alert("先选择文件");
    const fd = new FormData();
    [...files].forEach((f: File) => fd.append("files", f));
    fd.append("authority", auth);
    const r = await fetch("/kb/upload", { method: "POST", body: fd });
    (await r.json()).results.forEach((x: any) => alert(x.ok ? `已排队：${x.filename}` : `${x.filename}：${x.reason}`));
    onUploaded();
  }

  return (
    <div>
      <div className="mt-4 text-sm font-bold">上传文档</div>
      <div className="mt-2 flex gap-3.5">
        <label className="flex-1 cursor-pointer rounded-xl border-[2px] border-dashed border-input bg-accent p-5 text-center">
          <div className="text-[15px] font-semibold text-secondary-foreground">⬆️ 拖拽文件到此处，或点击选择（支持多选）</div>
          <div className="mt-1 text-[11.5px] text-muted-foreground">.md / .txt 直接解析 · .pdf 自动识别扫描件走 Vision OCR（≤500MB）</div>
          <input ref={fileRef} type="file" multiple accept=".md,.txt,.pdf" className="mt-2 text-xs" />
        </label>
        <div className="w-72 rounded-xl border border-border bg-accent p-3.5 text-[12.5px]">
          <div className="mb-1.5 text-muted-foreground">权威级（影响检索加权）</div>
          {AUTHORITY_OPTIONS.map(([v, t]) => (
            <label key={v} className="block cursor-pointer py-[3px]">
              <input type="radio" name="kb-auth" className="mr-1.5 accent-primary" checked={auth === v} onChange={() => setAuth(v)} /> {t}
            </label>
          ))}
          <Button className="mt-2 w-full" onClick={upload}>上传并解析</Button>
          <div className="mt-1 text-[11px] text-muted-foreground">扫描 PDF 约 3-4 分钟，可离开此页</div>
        </div>
      </div>
    </div>
  );
}
