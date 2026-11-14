"use client";

/**
 * The help bot with Ultra mode ticked (owners only; docs/plans/ultra-mode map destination 3, tickets 06 + 08): the
 * request goes to POST /admin/ultra/plans; the panel then follows that plan (useUltraPlan polls GET …/{id}) —
 * planning (turns, last tool; Stop) → the server's card, every step verbatim, one red OK (the shown sha256) →
 * running (a red line on the running step, the header dot pulses; Cancel) ⇄ needs_you (PickCard, "Send these")
 * → the end: each step's result and link, then "New request". The open plan's id is kept per browser so a reload
 * (or a collapsed dock) resumes it. State: ultraPanelReducer (this only dispatches). Look: UltraPanel.module.css,
 * dark in both app themes. AssistantPanel renders this in its own frame (dock / page / sheet).
 */
import { useCallback, useEffect, useReducer, useState } from "react";
import { ArrowUp, X } from "lucide-react";

import { errText } from "@/lib/errText";
import { LOGINS_PAGE } from "@/lib/loginPaste";
import { RelayError } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { PlanSteps } from "./PlanSteps";
import { beginStart, pendingStart, ULTRA_PLAN_KEY } from "./ultraStart";
import { useUltraPlan } from "./useUltraPlan";
import {
  INITIAL_PANEL, isOver, type PanelAction, isRunning, MAX_REQUEST, requestBody, canSubmit, ultraPanelReducer,
} from "./ultraPanelReducer";
import { planActions, refreshNote, statusNote, type Action as RunAction, type PlanView } from "./ultraRunReducer";
import styles from "./UltraPanel.module.css";

/** The Ultra tick, per browser. */
export const ULTRA_KEY = "chatterly:assistant_ultra";
export { ULTRA_PLAN_KEY } from "./ultraStart";

/** The Ultra tick: stored per browser, on only for an owner (a chatter never sees it). */
export function useUltraMode(isOwner: boolean): [boolean, (on: boolean) => void] {
  const [stored, setStored] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the store is read only after mount (no SSR access)
    try { setStored(window.localStorage.getItem(ULTRA_KEY) === "1"); } catch { /* safari private */ }
  }, []);
  const set = useCallback((on: boolean) => {
    setStored(on);
    try { window.localStorage.setItem(ULTRA_KEY, on ? "1" : "0"); } catch { /* quota */ }
  }, []);
  return [isOwner && stored, set];
}

export function UltraToggle({ checked, onChange, className }: {
  checked: boolean;
  onChange: (on: boolean) => void;
  className?: string;
}) {
  return (
    <label className={cn("flex cursor-pointer select-none items-center gap-1.5 text-[12px]", className)}
      title="Ultra: the AI plans several steps, you OK once, then it runs them all">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="size-3.5 accent-[#e11d2e]" />
      Ultra mode
    </label>
  );
}

/** A start's answer into a panel (dropped by React if it has closed: the next one hydrates from storage). */
function follow(p: Promise<PlanView>, send: (a: PanelAction) => void) {
  p.then((plan) => send({ type: "started", plan }),
    (e: unknown) => send({ type: "startFailed", status: e instanceof RelayError ? e.status : 0, message: errText(e) }));
}

const BTN = "h-10 min-w-[7.5rem] flex-1 rounded-full px-4 text-[14px] font-medium transition-colors disabled:opacity-40";

export function UltraPanel({ frame, column, composerPad, inputText, onClose, onOff }: {
  frame: string;
  column: string;
  composerPad: string;
  inputText: string;
  onClose?: () => void;
  onOff: () => void;
}) {
  const [s, send] = useReducer(ultraPanelReducer, INITIAL_PANEL);
  const runDispatch = useCallback((action: RunAction, planId: string) => send({ type: "run", planId, action }), []);
  const { read, act } = useUltraPlan(s.planId, s.run, runDispatch);

  useEffect(() => {
    let id: string | null = null;
    try { id = window.localStorage.getItem(ULTRA_PLAN_KEY); } catch { /* safari private */ }
    // A start still out (sent by a panel closed since): shown as in flight, its answer followed here.
    const p = pendingStart();
    send({ type: "hydrate", planId: id || null, starting: !id && p !== null });
    if (!id && p) follow(p, send);
  }, []);
  useEffect(() => {
    if (!s.hydrated) return;
    try {
      if (s.planId) window.localStorage.setItem(ULTRA_PLAN_KEY, s.planId);
      else window.localStorage.removeItem(ULTRA_PLAN_KEY);
    } catch { /* quota */ }
  }, [s.hydrated, s.planId]);

  function start() {
    const body = requestBody(s);
    send({ type: "start" }); // a login in the draft: refused here, never sent
    if (body) follow(beginStart(body), send);  // beginStart stores the plan id before this hears it
  }

  const run = s.run;
  const plan = run.plan;
  const over = isOver(s);
  const actions = planActions(run);
  const refresh = refreshNote(run);
  return (
    <div data-assistant-ui data-ultra data-plan-status={plan?.status}
      className={cn(styles.panel, "flex flex-col overflow-hidden", frame)}>
      <div className="shrink-0 border-b border-border pt-[max(0.75rem,env(safe-area-inset-top))] pb-3">
        <div className={cn("flex h-8 items-center gap-2 px-5", column)}>
          <span className={styles.title}>ULTRA</span>
          {isRunning(s) && <span className={styles.dot} data-ultra-dot role="img" aria-label="Running" />}
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close help" title="Close"
              className="-mr-2 ml-auto grid h-8 w-8 place-items-center rounded-md text-fg hover:bg-white/10">
              <X className="h-5 w-5" aria-hidden />
            </button>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-4">
        <div className={cn("flex flex-col gap-3 px-4", column)}>
          {!s.planId && (
            <p className="text-[14px] leading-relaxed text-fg-dim">
              Say what to get done, in your own words. The AI reads what it needs and shows the exact plan; nothing
              runs until your OK, then the steps run in order. It stops to ask you only where the plan says you pick
              the media.
            </p>
          )}
          {s.starting && <p role="status" className="text-[14px] text-fg">Sending your request to the planner…</p>}
          {s.loginRefused && (
            <p role="alert" className="break-words text-[13px] text-err">
              OnlyFans logins never go to Ultra: <a href={LOGINS_PAGE} className="underline">paste logins in the Connect card</a>.
            </p>
          )}
          {s.startError && <p role="alert" className="break-words text-[13px] text-err">{s.startError}</p>}
          {s.planId && run.load === "loading" && <p className="text-[14px] text-fg-dim">Loading the plan…</p>}
          {s.planId && run.load === "error" && (
            <p role="alert" className="break-words text-[13px] text-err">
              {run.loadError ?? "Could not read the plan."}{" "}
              <button type="button" className="underline" onClick={() => void read()}>Try again</button>
            </p>
          )}
          {plan && (
            <>
              {plan.summary && <h2 className="break-words text-[16px] font-medium text-fg">{plan.summary}</h2>}
              <p role="status" className="break-words text-[13px] text-fg-dim">{statusNote(plan)}</p>
              {refresh && (
                <p className="break-words text-[13px] text-warn">
                  {refresh.text}
                  {refresh.retry && <> <button type="button" className="underline" onClick={() => void read()}>Try again</button></>}
                </p>
              )}
              <PlanSteps state={run} dispatch={(a) => runDispatch(a, plan.id)} className={styles.steps} />
              {run.actionError && <p role="alert" className="break-words text-[13px] text-err">{run.actionError}</p>}
            </>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-border">
        <div className={cn("flex flex-col gap-2 px-4 pt-2.5 pb-4", composerPad, column)}>
          {!s.planId ? (
            <div className={cn(styles.composer, "flex items-end gap-2 rounded-3xl py-1.5 pl-4 pr-1.5")}>
              <textarea value={s.draft} rows={1} maxLength={MAX_REQUEST} disabled={s.starting}
                onChange={(e) => send({ type: "draft", text: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    start();
                  }
                }}
                placeholder="What should Ultra do?"
                title="The AI plans it; you check the plan and OK once. Enter to send · Shift+Enter for a new line"
                className={cn("min-w-0 max-h-28 flex-1 resize-none bg-transparent py-1.5 leading-5 text-fg placeholder:text-muted focus:outline-none [field-sizing:content]", inputText)} />
              <button type="button" onClick={start} disabled={!canSubmit(s)} aria-label="Plan it"
                title="Plan it" className={cn(styles.ok, "grid h-8 w-8 shrink-0 place-items-center rounded-full disabled:opacity-30")}>
                <ArrowUp className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {actions.map((b) => (
                <button key={b.kind} type="button" className={cn(BTN, b.primary ? styles.ok : styles.ghost)}
                  disabled={!b.enabled} onClick={() => void act(b.kind)}>{b.label}</button>
              ))}
              {(over || run.load === "error") && (
                <button type="button" className={cn(BTN, styles.ghost)} onClick={() => send({ type: "reset" })}>
                  New request
                </button>
              )}
            </div>
          )}
          <UltraToggle checked onChange={(on) => { if (!on) onOff(); }} className="self-end text-fg-dim" />
        </div>
      </div>
    </div>
  );
}
