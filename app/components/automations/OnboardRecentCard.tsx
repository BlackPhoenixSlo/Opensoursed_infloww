"use client";

import { useState, type ReactNode } from "react";

import { Button, Input } from "@/components/ui/primitives";
import { useEmployee } from "@/contexts/EmployeeContext";
import { relay } from "@/lib/relay";

/** "Onboard most recent N" — a one-shot run button for process_old_fans that
 *  needs no id list: enqueues {kind:"process_old_fans", payload:{recent_limit,
 *  recent_by}} (same /admin/automation/enqueue + employee-id pattern as UnsendCard
 *  / PremadeForm). The backend builds the batch from the N most-recently
 *  subscribed/messaged fans. Confirms first — it spends LLM credits on gen_info.
 *
 *  `pushToOf` adds `push_to_of: true` (apply_profiles also writes the nickname +
 *  note onto OnlyFans); `intro` and `action` replace the default copy. Shared by
 *  the rules editor (process_old_fans) and My Automations > Gen-Info. */
export function OnboardRecentCard({ accountId, pushToOf = false, intro, action = "Onboard most recent N" }: {
  accountId: string;
  pushToOf?: boolean;
  intro?: ReactNode;
  action?: string;
}) {
  const { current: currentEmployee } = useEmployee();
  const [n, setN] = useState("100");
  const [by, setBy] = useState<"subscribed" | "messaged">("subscribed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  async function enqueue() {
    setError(null);
    setOkMsg(null);
    const recent_limit = Math.floor(Number(n));
    if (!Number.isFinite(recent_limit) || recent_limit < 1) {
      setError("Enter how many recent fans to onboard (≥ 1).");
      return;
    }
    if (
      !window.confirm(
        `Onboard the ${recent_limit} most-recent (${by}) fans on this account?\n\n` +
          "This flags them out of the AI chats and spends LLM credits profiling " +
          "each. It can't be undone.",
      )
    )
      return;

    setBusy(true);
    try {
      const resp = await relay.post<{ enqueued_job_id: number }>(
        "/admin/automation/enqueue",
        {
          account_id: accountId,
          kind: "process_old_fans",
          payload: { recent_limit, recent_by: by, ...(pushToOf ? { push_to_of: true } : {}) },
        },
        { accountId, employeeId: currentEmployee?.id },
      );
      setOkMsg(
        `Onboarding enqueued (job #${resp.enqueued_job_id}) — ${recent_limit} most-recent ` +
          `(${by}) fans. Runs within ~30s.`,
      );
    } catch (e) {
      setError((e as Error)?.message || "Enqueue failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-bg-elev-1 p-3 space-y-2">
      <div className="text-[11px] text-fg-dim">
        {intro ?? (
          <>
            Onboard the most-recent fans now — no id list needed. Flags them out of the
            AI chats, then profiles + applies each (spends LLM credits).
          </>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="block space-y-1">
          <span className="text-[11px] text-fg-dim">How many</span>
          <Input
            type="number"
            min={1}
            value={n}
            onChange={(e) => setN(e.target.value)}
            className="w-24"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-[11px] text-fg-dim">Most recent by</span>
          <select
            value={by}
            onChange={(e) => setBy(e.target.value as "subscribed" | "messaged")}
            className="rounded-lg bg-bg-elev-1 border border-border text-sm px-2 py-1.5 text-fg focus:outline-none focus:ring-2 focus:ring-accent/40"
          >
            <option value="subscribed">subscribed</option>
            <option value="messaged">messaged</option>
          </select>
        </label>
        <Button size="sm" variant="primary" onClick={enqueue} disabled={busy || !accountId}>
          {busy ? "Enqueuing…" : action}
        </Button>
      </div>
      {okMsg && (
        <div className="text-[11px] text-ok border border-ok/30 bg-ok/5 rounded-md px-2 py-1.5">
          {okMsg}
        </div>
      )}
      {error && <span className="block text-err text-[11px]">{error}</span>}
    </div>
  );
}
