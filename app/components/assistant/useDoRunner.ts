"use client";


import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { fullAiConfigKey } from "@/hooks/useFullAiConfig";
import { relay, RelayError } from "@/lib/relay";

import type { AgentBridge, EditorHandle, PanelHandle } from "./agentBridge";
import type { CursorState } from "./AgentCursor";
import { boundFlow, typingFrames, type AgentStep } from "./doFlows";
import { canStart, isTakeover, type DoAction, type DoRun } from "./doRunReducer";
import type { DoDraft } from "./doFlows";
import { applyBody, resultLine } from "./fullAiConfigEdit";

const OPEN_TIMEOUT_MS = 8000;
const GLIDE_MS = 320;
const PAUSE_MS = 140;
const TYPE_MS = 90;
const DONE_WAIT_MS = 6000;
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

const enabledSwitch = (label: string) =>
  [...document.querySelectorAll<HTMLElement>('[role="switch"]')].find((el) => el.getAttribute("aria-label") === label) ?? null;

export function useDoRunner({ run, dispatch, bridge, navigate, employeeId }: {
  run: DoRun;
  dispatch: (a: DoAction) => void;
  bridge: AgentBridge;
  navigate: (href: string) => void;
  employeeId: number | null;
}): CursorState | null {
  const queryClient = useQueryClient();
  const [cursor, setCursor] = useState<CursorState | null>(null);
  const instantRef = useRef(false);
  const phaseRef = useRef(run.phase);
  const navRef = useRef(navigate);
  useEffect(() => {
    instantRef.current = run.phase === "running" && run.instant;
    phaseRef.current = run.phase;
    navRef.current = navigate;
  });

  const runDraft = run.phase === "running" ? run.draft : null;
  useEffect(() => {
    const flow = runDraft && canStart(runDraft) ? boundFlow(runDraft) : null;
    if (!runDraft || !flow) return;
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
    const restOn = async (label: string) => {
      for (let waited = 0; waited < DONE_WAIT_MS && phaseRef.current === "done"; waited += 150) {
        const el = enabledSwitch(label);
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

    const execute = async () => {
      const steps = flow.steps;
      const acct = flow.accountId;
      const late = (what: string) => (e: unknown) => { throw signal.aborted ? e : new Error(what); };
      if (bridge.hasEditor()) throw new Error("Close the open editor first — I won't fill over it.");
      setCursor({ x: window.innerWidth - 80, y: window.innerHeight - 140, label: "Opening the page…", clicks: 0 });
      navRef.current(flow.route(acct));
      let panel: PanelHandle | null = null;
      let editor: EditorHandle | null = null;
      if (steps[0]?.action === "open") {
        panel = await bridge.waitFor(() => bridge.panel(flow.kind, acct), OPEN_TIMEOUT_MS, signal)
          .catch(late(`The ${flow.title} page didn't open in time — try again.`));
      } else {
        const page = await bridge.waitFor(() => bridge.anyEditor(flow.kind, acct), OPEN_TIMEOUT_MS, signal)
          .catch(late(`The ${flow.title} page didn't open in time — try again.`));
        if (!page.isNew) throw new Error(`${flow.title} is already set up for this creator — open it to edit; nothing was changed.`);
        editor = page;
      }
      for (let i = 0; i < steps.length; i++) {
        if (signal.aborted) return;
        const step = steps[i];
        dispatch({ type: "step", index: i });
        const animate = !instantRef.current;
        if (step.action === "open") {
          if (!panel) throw new Error(`The ${flow.title} page didn't open in time — try again.`);
          if (animate) { await glide(step); click(); }
          panel.openNew();
          editor = await bridge.waitFor(() => bridge.editor(flow.kind, acct), OPEN_TIMEOUT_MS, signal)
            .catch(late(`The new ${flow.title} editor didn't open — try again.`));
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
          // From here Stop no longer applies: the request lands either way.
          dispatch({ type: "saving" });
          const r = await editor.save();
          if (!r.ok) { dispatch({ type: "fail", msg: r.reason }); return; }
          dispatch({ type: "saved" });
          phaseRef.current = "done";
          void restOn(flow.savedSwitch);
          return;
        }
        if (step.action === "reveal") {
          if (animate) { await glide(step); click(); }
          const el = document.getElementById(step.target);
          // Synthetic click is untrusted (never a takeover), only on a closed disclosure.
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
        if (!seen) { await frame(); await glide(step); }
        await sleep(PAUSE_MS, signal);
      }
    };

    execute().catch((e: unknown) => {
      if (signal.aborted) return;
      dispatch({ type: "fail", msg: e instanceof Error && e.message ? e.message : "Something went wrong — nothing was saved." });
    });
    return () => {
      ctl.abort();
      window.removeEventListener("pointerdown", onInput, true);
      window.removeEventListener("keydown", onInput, true);
    };
  }, [runDraft, bridge, dispatch]);

  const configDraft = run.phase === "running" && run.draft.flow === "full_ai_config" ? run.draft : null;
  // The ref survives StrictMode's effect re-run: one draft PUT per started draft.
  const configured = useRef<DoDraft | null>(null);
  useEffect(() => {
    if (!configDraft || configDraft.flow !== "full_ai_config" || !configDraft.slots || configured.current === configDraft) return;
    configured.current = configDraft;
    const { slots, account_id: acct } = configDraft;
    relay.put<unknown>("/admin/full-ai/config/draft", applyBody(slots, acct), { accountId: acct, employeeId })
      .then((r) => {
        dispatch({ type: "configApplied", status: 200, line: resultLine(200, r) });
        void queryClient.invalidateQueries({ queryKey: fullAiConfigKey(acct) });
      })
      .catch((e: unknown) => dispatch(e instanceof RelayError && (e.status === 409 || e.status === 422)
        ? { type: "configApplied", status: e.status, line: resultLine(e.status, e.body) }
        : { type: "fail", msg: e instanceof Error && e.message ? e.message : "The change didn't go through" }));
  }, [configDraft, employeeId, dispatch, queryClient]);

  useEffect(() => {
    if (run.phase !== "done") return;
    const hide = (e: PointerEvent) => { if (e.isTrusted) setCursor(null); };
    window.addEventListener("pointerdown", hide, true);
    return () => window.removeEventListener("pointerdown", hide, true);
  }, [run.phase]);

  return run.phase === "running" || run.phase === "done" ? cursor : null;
}
