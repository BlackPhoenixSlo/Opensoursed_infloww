"use client";

/**
 * UltraPlanPage — `/ultra/plans/[id]`, the page an MCP client's `propose_plan` links (its open_url; ultra tickets
 * 06 + 13). The owner reads every step as the server drew it (a send: Creator, audience, price, media count and its
 * FULL text), presses the one OK, which posts the hash of exactly that plan (POST /admin/ultra/plans/{id}/ok), then
 * the page re-reads it every 2 s while it runs, with Cancel; a `needs_you` judge shows its pick card (PickCard,
 * "Send these" posts exactly pick_n). When it ends: each step's state and link, and a plain
 * statement for uncertain / interrupted / expired. State lives in `ultraRunReducer` (this only dispatches); I/O in `useUltraPlan`.
 *
 * Signed out, AuthGate's in-place sign-in comes back here (`signInReturn`). A chatter or another owner gets the
 * Relay's 403 / 404 as a line, never the plan.
 */
import { useReducer } from "react";

import { EmptyState, IfButton, IfBody, InflowwPageHeader } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";
import { PlanSteps } from "./PlanSteps";
import { useUltraPlan } from "./useUltraPlan";
import { INITIAL_RUN, planActions, refreshNote, statusNote, ultraRunReducer } from "./ultraRunReducer";

// The sticky bar's height (border 1 + pt/pb 12 each + h-9 buttons, gap-2 between when stacked) plus the phone
// safe-area, so the last step can scroll clear of it: stacked on a phone, one row from `sm`.
const BAR_PAD_TWO = "pb-[calc(105px+env(safe-area-inset-bottom))] sm:pb-[calc(61px+env(safe-area-inset-bottom))]";
const BAR_PAD_ONE = "pb-[calc(61px+env(safe-area-inset-bottom))]";

export default function UltraPlanPage({ planId }: { planId: string }) {
  const [state, dispatch] = useReducer(ultraRunReducer, INITIAL_RUN);
  const { read, act } = useUltraPlan(planId, state, dispatch);

  const plan = state.plan;
  const actions = planActions(state);
  const refresh = refreshNote(state);
  return (
    <div className="min-w-0">
      <InflowwPageHeader title="Ultra plan" />
      <IfBody className="mx-auto w-full max-w-3xl px-3 sm:px-6">
        {state.load === "loading" && <EmptyState kind="data" text="Loading the plan…" size="sm" art={false} />}
        {state.load === "missing" && <EmptyState kind="data" text="No such plan, or it is not one of yours." />}
        {state.load === "error" && (
          <EmptyState kind="error" text={state.loadError ?? "Could not read the plan."} onRetry={() => void read()} />
        )}
        {plan && (
          <div className="flex flex-col gap-4" data-plan-status={plan.status}>
            <div>
              <h2 className="break-words text-[18px] font-medium text-fg">{plan.summary}</h2>
              <p role="status" className="mt-1 text-[14px] text-fg-dim">{statusNote(plan)}</p>
              {refresh && (
                <p className="mt-1 break-words text-[13px] text-warn">
                  {refresh.text}
                  {refresh.retry && <> <button type="button" className="underline" onClick={() => void read()}>Try again</button></>}
                </p>
              )}
            </div>
            <PlanSteps state={state} dispatch={dispatch}
              className={cn(actions.length > 1 ? BAR_PAD_TWO : actions.length === 1 && BAR_PAD_ONE)} />
            {actions.length > 0 && (
              <div className="sticky bottom-0 -mx-3 flex flex-col gap-2 border-t border-border bg-bg px-3 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:mx-0 sm:flex-row sm:justify-end sm:px-0">
                {actions.map((b) => (
                  <IfButton key={b.kind} variant={b.primary ? "primary" : "default"} size="lg" className="w-full sm:w-auto"
                    disabled={!b.enabled} onClick={() => void act(b.kind)}>
                    {b.label}
                  </IfButton>
                ))}
              </div>
            )}
            {state.actionError && <p role="alert" className="text-[13px] text-err">{state.actionError}</p>}
          </div>
        )}
      </IfBody>
    </div>
  );
}
