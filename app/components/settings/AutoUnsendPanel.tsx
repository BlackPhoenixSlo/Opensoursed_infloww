"use client";

/** The Mass messages tab's hourly Auto-unsend card, one panel per model
 *  (moved out of MassMessagesTab.tsx as is). */

import { useEffect, useMemo, useRef, useState } from "react";

import { IfButton, IfInput, IfSwitch } from "@/components/ui/infloww";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
} from "@/hooks/useAutomations";

/** Name + cadence of the scheduled auto-unsend rule this tab manages (one
 *  `unsend_messages` automation_rules row per account, keyed by this name). */
const AUTO_RULE_NAME = "Auto-unsend mass";
const AUTO_EVERY_SECONDS = 3600; // hourly sweep

/** Per-model auto-unsend config. Reads/writes the single `unsend_messages` rule
 *  named AUTO_RULE_NAME for this account; the payload carries
 *  `policy.{mass_text_hours,mass_media_hours,mass_price_hours}` for the enabled
 *  classes (mirrors the backend sweep). */
export function AutoUnsendPanel({ accountId, label }: { accountId: string; label: string }) {
  const rulesQ = useAutomationRules(accountId);
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const existing = useMemo(
    () =>
      (rulesQ.data ?? []).find(
        (r) => r.kind === "unsend_messages" && r.name === AUTO_RULE_NAME,
      ),
    [rulesQ.data],
  );

  const [enabled, setEnabled] = useState(false);
  const [text, setText] = useState({ on: true, h: 4 });
  const [img, setImg] = useState({ on: false, h: 24 });
  const [price, setPrice] = useState({ on: false, h: 48 });

  // Hydrate the form once from the saved rule when it first loads.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current || !existing) return;
    hydratedRef.current = true;
    setEnabled(existing.is_enabled);
    const p = (existing.payload?.policy ?? {}) as Record<string, number>;
    setText(p.mass_text_hours != null ? { on: true, h: p.mass_text_hours } : { on: false, h: 4 });
    setImg(p.mass_media_hours != null ? { on: true, h: p.mass_media_hours } : { on: false, h: 24 });
    setPrice(p.mass_price_hours != null ? { on: true, h: p.mass_price_hours } : { on: false, h: 48 });
  }, [existing]);

  const saving = createM.isPending || updateM.isPending;
  const err = createM.error || updateM.error;
  // Save guard: an empty policy is never sent. The Relay reads one as the
  // per-chat sweep of outbound DMs (`not wants_mass`, unsend_messages.py).
  const noClass = !text.on && !img.on && !price.on;

  const save = () => {
    if (noClass) return;
    const policy: Record<string, number> = {};
    if (text.on) policy.mass_text_hours = text.h;
    if (img.on) policy.mass_media_hours = img.h;
    if (price.on) policy.mass_price_hours = price.h;
    const payload = { policy };
    if (existing) {
      updateM.mutate({
        id: existing.id,
        is_enabled: enabled,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
      });
    } else {
      createM.mutate({
        account_id: accountId,
        kind: "unsend_messages",
        name: AUTO_RULE_NAME,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
        is_enabled: enabled,
      });
    }
  };

  return (
    <div className="rounded-md border border-border p-4 space-y-3 text-[14px]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <IfSwitch label={<span className="font-medium">{label}</span>} checked={enabled} onChange={setEnabled} />
          {existing?.is_enabled && (
            <span className="rounded-[4px] bg-accent/15 px-1.5 text-[12px] text-accent">Active</span>
          )}
        </div>
        <span className="text-[12px] text-fg-dim">Runs hourly</span>
      </div>
      <AutoClassRow label="Free text-only" v={text} set={setText} />
      <AutoClassRow label="With image / video" v={img} set={setImg} />
      <AutoClassRow label="PPV (priced)" v={price} set={setPrice} />
      <div className="flex items-center gap-3 pt-1 flex-wrap">
        <IfButton onClick={save} disabled={saving || noClass}>
          {saving ? "Saving…" : existing ? "Update" : "Save"}
        </IfButton>
        {noClass && (
          <span className="text-[12px] text-fg-dim">Turn on at least one class to save.</span>
        )}
        {err && <span className="text-[12px] text-err">{err.message}</span>}
        {existing?.last_run && (
          <span className="text-[12px] text-fg-dim">
            Last run: {existing.last_run.status}
            {existing.next_due_at
              ? ` · next ${new Date(existing.next_due_at).toLocaleTimeString()}`
              : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function AutoClassRow({
  label, v, set,
}: {
  label: string;
  v: { on: boolean; h: number };
  set: (x: { on: boolean; h: number }) => void;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap md:flex-nowrap">
      <IfSwitch className="w-full md:w-52" label={label} checked={v.on} onChange={(on) => set({ ...v, on })} />
      <span className="text-fg-dim">after</span>
      <IfInput
        type="number"
        min={1}
        aria-label={`${label} hours`}
        className={v.on ? "w-20" : "w-20 opacity-50"}
        value={v.h}
        disabled={!v.on}
        onChange={(e) => set({ ...v, h: Math.max(1, Number(e.target.value) || 1) })}
      />
      <span className="text-fg-dim">hours</span>
    </div>
  );
}
