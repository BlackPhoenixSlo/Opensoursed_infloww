"use client";

/**
 * The "Do it for me" runner (docs/spec/assistant-do-mode.md, D1): while the run is `running` (doRunReducer.ts) it
 * opens the flow's page, waits for the page to register on the agent bridge, then plays the flow's steps
 * (doFlows.ts `toActions`): per step the cosmetic cursor glides to the field (AgentCursor.tsx), clicks, and the step's
 * action is dispatched into the editor's own reducer; Save is the editor's own (agentBridge). Skip animation plays the
 * rest instantly. A trusted page input outside the bot (or Escape) aborts (isTakeover) — until the save request is out
 * (`saving`): from there it lands either way. A rule editor already open (a person's, maybe half-filled) fails the run
 * before anything moves: it never fills over one, nor navigates away from it. It lives in AssistantProvider, so a
 * route change never stops it. After Save the cursor rests on the new rule's Enabled switch without clicking it.
 * A `mass_edit` run is not played here: it has no form (the provider's apply POST does it, massEdit.ts).
 */

import { useEffect, useRef, useState } from "react";

import type { AgentBridge, EditorHandle } from "./agentBridge";
import type { CursorState } from "./AgentCursor";
import { DO_FLOWS, typingFrames, type AgentStep, type DoDraft } from "./doFlows";
import { canStart, isTakeover, type DoAction, type DoRun } from "./doRunReducer";

const OPEN_TIMEOUT_MS = 8000;
const GLIDE_MS = 320;
const PAUSE_MS = 140;
const TYPE_MS = 90;
const DONE_WAIT_MS = 6000;
/** An editor missing from the bridge is closed only if it isn't back by then (a re-registration is a blip). */
const CLOSED_GRACE_MS = 500;

const aborted = () => new DOMException("aborted", "AbortError");

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(aborted()); return; }
    const t = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    const stop = () => { clearTimeout(t); reject(aborted()); };
    signal.addEventListener("abort", stop, { once: true });
  });
}

const frame = () => new Promise<void>((r) => {
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => r());
  else setTimeout(r, 16);
});

const reducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The saved rule's Enabled switch in the table (RuleTable: `Enabled: {name}`). */
const enabledSwitch = (name: string) =>
  [...document.querySelectorAll<HTMLElement>('[role="switch"]')].find((el) => el.getAttribute("aria-label") === `Enabled: ${name}`) ?? null;

export function useDoRunner({ run, dispatch, bridge, navigate }: {
  run: DoRun;
  dispatch: (a: DoAction) => void;
  bridge: AgentBridge;
  navigate: (href: string) => void;
}): CursorState | null {
  const [cursor, setCursor] = useState<CursorState | null>(null);
  const instantRef = useRef(false);
  const phaseRef = useRef(run.phase);
  const navRef = useRef(navigate);
  useEffect(() => {
    instantRef.current = run.phase === "running" && run.instant;
    phaseRef.current = run.phase;
    navRef.current = navigate;
  });

  // The run: one per start (its draft); leaving `running` aborts it.
  const runDraft = run.phase === "running" ? run.draft : null;
  useEffect(() => {
    if (!runDraft || !canStart(runDraft) || runDraft.flow !== "mass_premade") return;
    const ctl = new AbortController();
    const { signal } = ctl;

    const onInput = (e: Event) => {
      const t = e.target instanceof Element ? e.target : null;
      const inside = !!t?.closest("[data-assistant-ui],[data-agent-cursor]");
      const key = e instanceof KeyboardEvent ? e.key : undefined;
      if (isTakeover({ isTrusted: e.isTrusted, type: e.type, key }, inside)) {
        dispatch({ type: "abort", reason: key === "Escape" ? "Stopped with Esc" : "Stopped — you took over" });
      }
    };
    window.addEventListener("pointerdown", onInput, true);
    window.addEventListener("keydown", onInput, true);

    const click = () => setCursor((c) => (c ? { ...c, clicks: c.clicks + 1 } : c));
    const glide = async (step: Pick<AgentStep, "target" | "label">): Promise<boolean> => {
      const el = document.getElementById(step.target);
      if (!el) { setCursor((c) => (c ? { ...c, label: step.label } : c)); return false; }
      el.scrollIntoView?.({ block: "center", inline: "nearest" });
      await frame();
      const r = el.getBoundingClientRect();
      setCursor((c) => ({ x: r.left + Math.min(r.width / 2, 28), y: r.top + r.height / 2, label: step.label, clicks: c?.clicks ?? 0 }));
      await sleep(reducedMotion() ? 60 : GLIDE_MS, signal);
      return true;
    };
    const restOn = async (name: string) => {
      for (let waited = 0; waited < DONE_WAIT_MS && phaseRef.current === "done"; waited += 150) {
        const el = enabledSwitch(name);
        if (el) {
          el.scrollIntoView?.({ block: "center", inline: "nearest" });
          await frame();
          const r = el.getBoundingClientRect();
          setCursor((c) => ({ x: r.left + r.width / 2, y: r.top + r.height / 2, label: "Turn it on here when ready", clicks: c?.clicks ?? 0 }));
          return;
        }
        await new Promise((res) => setTimeout(res, 150));
      }
    };

    const execute = async (draft: DoDraft & { flow: "mass_premade" }) => {
      const flow = DO_FLOWS[draft.flow];
      const slots = draft.slots!;
      const steps = flow.toActions(slots);
      const acct = draft.account_id;
      if (bridge.hasEditor()) throw new Error("Close the open editor first — I won't fill over it.");
      setCursor({ x: window.innerWidth - 80, y: window.innerHeight - 140, label: "Opening the page…", clicks: 0 });
      navRef.current(flow.route(acct));
      const panel = await bridge.waitFor(() => bridge.panel(flow.kind, acct), OPEN_TIMEOUT_MS, signal)
        .catch((e) => { throw signal.aborted ? e : new Error("The Auto Mass page didn't open in time — try again."); });
      let editor: EditorHandle | null = null;
      for (let i = 0; i < steps.length; i++) {
        if (signal.aborted) return;
        const step = steps[i];
        dispatch({ type: "step", index: i });
        const animate = !instantRef.current;
        if (step.action === "open") {
          if (animate) { await glide(step); click(); }
          panel.openNew();
          editor = await bridge.waitFor(() => bridge.editor(flow.kind, acct), OPEN_TIMEOUT_MS, signal)
            .catch((e) => { throw signal.aborted ? e : new Error("The new Auto Mass editor didn't open — try again."); });
          continue;
        }
        if (!editor) throw new Error("The editor was closed — nothing was saved.");
        if (bridge.editor(flow.kind, acct) !== editor) {
          const held = editor;
          await bridge.waitFor(() => (bridge.editor(flow.kind, acct) === held ? held : null), CLOSED_GRACE_MS, signal)
            .catch((e) => { throw signal.aborted ? e : new Error("The editor was closed — nothing was saved."); });
        }
        if (step.action === "save") {
          if (animate) { await glide(step); click(); }
          if (signal.aborted) return;
          dispatch({ type: "saving" });   // from here Stop no longer applies: the request lands either way
          const r = await editor.save();
          if (!r.ok) { dispatch({ type: "fail", msg: r.reason }); return; }
          dispatch({ type: "saved" });
          phaseRef.current = "done";
          void restOn(flow.savedName(slots));
          return;
        }
        if (step.action === "reveal") {
          if (animate) { await glide(step); click(); }
          // A synthetic click (untrusted: never a takeover), only on a closed disclosure.
          const el = document.getElementById(step.target);
          if (el?.getAttribute("aria-expanded") === "false") el.click();
          await frame();
          continue;
        }
        if (!animate) { editor.dispatch(step.action); continue; }
        const seen = await glide(step);
        click();
        const frames = typingFrames(step);
        for (let f = 0; f < frames.length; f++) {
          editor.dispatch(frames[f]);
          if (f < frames.length - 1) await sleep(TYPE_MS, signal);
        }
        // A box the step itself adds (a new caption) exists only now.
        if (!seen) { await frame(); await glide(step); }
        await sleep(PAUSE_MS, signal);
      }
    };

    execute(runDraft as DoDraft & { flow: "mass_premade" }).catch((e: unknown) => {
      if (signal.aborted) return;
      dispatch({ type: "fail", msg: e instanceof Error && e.message ? e.message : "Something went wrong — nothing was saved." });
    });
    return () => {
      ctl.abort();
      window.removeEventListener("pointerdown", onInput, true);
      window.removeEventListener("keydown", onInput, true);
    };
  }, [runDraft, bridge, dispatch]);

  // The cursor shows while running; after Save it rests on the switch until the user's next press.
  useEffect(() => {
    if (run.phase !== "done") return;
    const hide = (e: PointerEvent) => { if (e.isTrusted) setCursor(null); };
    window.addEventListener("pointerdown", hide, true);
    return () => window.removeEventListener("pointerdown", hide, true);
  }, [run.phase]);

  return run.phase === "running" || run.phase === "done" ? cursor : null;
}
