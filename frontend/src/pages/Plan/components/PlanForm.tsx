import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { PlanDraft } from "@/lib/types";

export interface PlanProfile {
  identity: string;
  city: string;
  weekly_hours: number;
  budget: number;
  exam_date: string;
  cert_id: string;
}

const CERTS: [string, string][] = [
  ["nsca_cpt", "NSCA-CPT（性价比/中文考试）"],
  ["ace_cpt", "ACE-CPT（自学友好）"],
  ["acsm_cpt", "ACSM-CPT（学术/康复衔接）"],
  ["nasm_cpt", "NASM-CPT（健身俱乐部认可）"],
];

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="min-w-[150px] flex-1">
      <div className="mb-1 text-[11.5px] font-semibold text-secondary-foreground">{label}</div>
      {children}
      {hint && <div className="mt-0.5 text-[10.5px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** 生成 / 调整计划表单 + LangGraph HITL 草稿确认 */
export function PlanForm({ draft, busy, onStart, onConfirm }: {
  draft: PlanDraft | null;
  busy: boolean;
  onStart: (profile: PlanProfile) => void;
  onConfirm: (approve: boolean, feedback?: string) => void;
}) {
  const [identity, setIdentity] = useState("在职教练");
  const [cert, setCert] = useState("nsca_cpt");
  const [fb, setFb] = useState("");

  function start() {
    const date = (document.getElementById("pl-date") as HTMLInputElement).value
      || new Date(Date.now() + 45 * 864e5).toISOString().slice(0, 10);
    onStart({
      identity,
      cert_id: cert,
      city: (document.getElementById("pl-city") as HTMLInputElement).value || "杭州",
      weekly_hours: +(document.getElementById("pl-h") as HTMLInputElement).value || 10,
      budget: +(document.getElementById("pl-b") as HTMLInputElement).value || 5000,
      exam_date: date,
    });
  }

  return (
    <>
      <div id="plan-form-anchor" className="mt-4 text-sm font-bold">生成 / 调整计划</div>
      <Card className="mt-2 border-[1.5px] border-dashed border-primary bg-accent p-4">
        <div className="flex flex-wrap gap-3">
          <Field label="备考证书" hint="影响章节排期与题库">
            <Select value={cert} onValueChange={setCert}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {CERTS.map(([v, t]) => <SelectItem key={v} value={v}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="当前身份">
            <Select value={identity} onValueChange={setIdentity}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {["在职教练", "体育生", "退役运动员", "健身爱好者转行"].map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="考试城市" hint="考位/报名渠道参考">
            <Input id="pl-city" placeholder="如：杭州" defaultValue="杭州" />
          </Field>
          <Field label="每周可学时长（小时）" hint="3-40">
            <Input id="pl-h" type="number" defaultValue={10} min={3} max={40} />
          </Field>
          <Field label="预算（元）" hint="影响证书推荐：低于 2000 元推荐省钱组合">
            <Input id="pl-b" type="number" defaultValue={5000} min={500} step={500} />
          </Field>
          <Field label="考试日期" hint="决定计划周数">
            <Input id="pl-date" type="date" defaultValue={new Date(Date.now() + 45 * 864e5).toISOString().slice(0, 10)} />
          </Field>
        </div>
        <Button className="mt-2.5" onClick={start} disabled={busy}>{busy ? "⏳ 生成中（10-25 秒）…" : "生成计划"}</Button>
        <div className="mt-1.5 text-[11px] text-muted-foreground">LangGraph HITL：确认前可无限轮调整；跨重启可恢复草稿</div>

        {draft?.pending_confirm && (
          <div className="mt-3">
            <div className="rounded-lg border border-border border-l-4 border-l-primary bg-accent px-3 py-2 text-xs">
              <b>推荐路径：</b>主攻 {draft.path?.primary}（{draft.path?.primary_reason}）；备选 {draft.path?.backup}
            </div>
            <div className="mt-2 space-y-2">
          {(draft.plan?.phases || []).map((ph: any, i: number) => (
            <div key={i} className="rounded-lg border border-border bg-white p-3">
              <div className="text-[13px] font-bold">{ph.name} <span className="ml-1 text-[11px] font-normal text-muted-foreground">{ph.weeks}</span></div>
              {!!ph.chapters?.length && <div className="mt-1 text-xs text-muted-foreground">章节：{ph.chapters.join("、")}</div>}
              {ph.daily_tasks && <div className="mt-1 text-xs">每日：{ph.daily_tasks}</div>}
              {ph.milestone && <div className="mt-1 text-xs text-secondary-foreground">里程碑：{ph.milestone}</div>}
            </div>
          ))}
        </div>
            <Input placeholder="修改意见（不确认时填写，会按意见重新生成）" value={fb} onChange={(e) => setFb(e.target.value)} />
            <div className="mt-1.5 flex gap-2">
              <Button onClick={() => onConfirm(true)}>✅ 确认生效</Button>
              <Button variant="outline" onClick={() => onConfirm(false, fb)}>🔁 按意见重新生成</Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
