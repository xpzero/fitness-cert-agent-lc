import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { USER_ID } from "@/lib/constants";
import type { Overview, PlanDraft } from "@/lib/types";
import { OverviewHeader } from "./components/OverviewHeader";
import { PhaseBar } from "./components/PhaseBar";
import { PlanForm, type PlanProfile } from "./components/PlanForm";
import { WeekTasks } from "./components/WeekTasks";

export default function Plan() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [busy, setBusy] = useState(false);

  const dash = () => api<Overview>(`/plan/overview?user_id=${USER_ID}`).then(setOv).catch(() => setOv({ active: false }));
  useEffect(() => { dash(); }, []);

  async function start(profile: PlanProfile) {
    setBusy(true);
    try {
      setDraft(await api("/plan/start", { method: "POST", body: JSON.stringify({
        user_id: USER_ID, profile }) }));
    } catch (e: any) { alert("生成失败：" + e.message); }
    setBusy(false);
  }
  async function confirm(approve: boolean, feedback?: string) {
    if (!draft) return;
    setDraft(await api("/plan/confirm", { method: "POST", body: JSON.stringify({
      thread_id: draft.thread_id, approve, feedback: approve ? undefined : feedback }) }));
    dash();
  }
  async function checkin(no: number, done: boolean) {
    await api("/plan/checkin", { method: "POST", body: JSON.stringify({ user_id: USER_ID, task_no: no, done }) });
    dash();
  }

  const curIdx = ov?.phases?.findIndex((p) => p.name === ov.current_phase?.name) ?? -1;

  return (
    <div>
      {ov?.active ? (
        <>
          <OverviewHeader ov={ov} />
          <PhaseBar ov={ov} curIdx={curIdx} />
          <WeekTasks ov={ov} onCheckin={checkin} />
        </>
      ) : (
        <div className="rounded-xl border border-border bg-accent p-4 text-sm text-muted-foreground">
          暂无生效计划——用下方表单生成。
        </div>
      )}

      <PlanForm draft={draft} busy={busy} onStart={start} onConfirm={confirm} />
    </div>
  );
}
