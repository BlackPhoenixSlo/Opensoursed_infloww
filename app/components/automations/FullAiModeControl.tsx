"use client";

/**
 * FullAiModeControl — the Full AI page's Mode control (ticket 74, the flip gate): Off / Live over
 * `useFullAiMode` (GET / PUT /admin/full-ai/mode). Live asks to confirm first ("Replies will be sent to fans on
 * OnlyFans") and is disabled while the server names a blocker (a Writer or TypeSafe key missing).
 * A legacy rule with no Mode reads "Shadow (records only)" until Off or Live is picked; Shadow itself is not
 * offered. Off stays pressable while the Mode read is loading or failed. FULL_AI_CHAT_OFF wins over the Mode: shown when set. One value (the confirm being open): plain useState.
 */

import { useState } from "react";

import { ROW } from "@/components/automations/automationPage";
import { IfButton, IfModal } from "@/components/ui/infloww";
import { useFullAiMode, useSetFullAiMode, type FullAiMode } from "@/hooks/useFullAiMode";
import { cn } from "@/lib/utils";

export const LIVE_CONFIRM = "Replies will be sent to fans on OnlyFans.";

const MODE_LABEL: Record<FullAiMode, string> = { off: "Off", live: "Live", shadow: "Shadow (records only)" };

export function FullAiModeControl({ accountId }: { accountId: string }) {
  const modeQ = useFullAiMode(accountId);
  const setMode = useSetFullAiMode(accountId);
  const [confirming, setConfirming] = useState(false);
  const m = modeQ.data;
  const blocked = (m?.blockers.length ?? 0) > 0;

  return (
    <div className={ROW} data-testid="full-ai-mode">
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div>
          <div className="text-[14px] text-fg">Full AI Chat</div>
          <div className="text-[12px] text-muted" data-testid="full-ai-mode-now">{m ? MODE_LABEL[m.mode] : "…"}</div>
        </div>
        <div role="group" aria-label="Mode" className="flex gap-2">
          {(["off", "live"] as const).map((v) => (
            <IfButton key={v} aria-pressed={m?.mode === v} variant={m?.mode === v ? "primary" : "default"}
              disabled={setMode.isPending || m?.mode === v || (v === "live" && (!m || blocked))}
              onClick={() => (v === "live" ? setConfirming(true) : setMode.mutate("off"))}>
              {MODE_LABEL[v]}
            </IfButton>
          ))}
        </div>
      </div>
      <div className={cn("space-y-1", (modeQ.isError || setMode.isError || m?.off_switch || blocked) && "pb-3")}>
        {modeQ.isError && <p className="text-[12px] text-err">Couldn&apos;t read the Mode, so this can&apos;t say whether it is Live.</p>}
        {setMode.isError && <p className="text-[12px] text-err">{setMode.error?.message || "Couldn't change the Mode."} Try again.</p>}
        {m?.off_switch && (
          <p className="text-[12px] text-warn">FULL_AI_CHAT_OFF is on: nothing is sent on any Creator, whatever the Mode.</p>
        )}
        {blocked && (
          <ul aria-label="Live blockers" className="space-y-0.5 text-[12px] text-err">
            {m?.blockers.map((b) => <li key={b}>{b}</li>)}
          </ul>
        )}
      </div>
      {confirming && (
        <IfModal width={416} title="Go Live?" onClose={() => setConfirming(false)}
          footer={(
            <>
              <IfButton onClick={() => setConfirming(false)}>Cancel</IfButton>
              <IfButton variant="primary" disabled={setMode.isPending}
                onClick={() => { setConfirming(false); setMode.mutate("live"); }}>
                Go Live
              </IfButton>
            </>
          )}>
          <p className="text-fg-dim">{LIVE_CONFIRM}</p>
        </IfModal>
      )}
    </div>
  );
}
