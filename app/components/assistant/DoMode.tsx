"use client";

/** The help bot's "Do it for me" pieces (docs/spec/assistant-do-mode.md): the do-mode conversation (the request, the
 *  plan card from the server's draft, the run's progress and outcome) and the phone's pill ("Doing it… · Stop", then
 *  the outcome · Open).
 *  Presentation only: AssistantPanel passes the run (doRunReducer.ts) and its callbacks. */

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { boundFlow, PLAN_NOTE, type DoDraft } from "./doFlows";
import { canStart, type DoRun } from "./doRunReducer";
import { editPlanText, resultHeadline, resultLines, type EditResult, type MassEditSlots } from "./massEdit";

/** The messenger's card (the home screen's "Ask a question"). */
export const CARD = "rounded-xl border border-[#ededed] bg-white px-6 py-[17px] leading-5 shadow-[0_2px_8px_rgba(0,0,0,0.06)]";

const BUBBLE_ME = "self-end max-w-[85%] rounded-2xl rounded-br-md bg-[#151515] px-3.5 py-2 text-[13px] text-white whitespace-pre-wrap break-words";
const BUBBLE_BOT = "self-start max-w-[92%] rounded-2xl rounded-bl-md bg-bg-elev-1 px-3.5 py-2 text-[13px] leading-relaxed break-words";
const BTN = "h-8 rounded-full px-3.5 text-[13px] font-medium transition-colors disabled:opacity-40";
const BTN_MAIN = cn(BTN, "bg-[#151515] text-white hover:bg-black");
const BTN_SOFT = cn(BTN, "border border-[#dcdcdc] bg-white text-[#14161a] hover:border-[#bdbdbd]");

export const DO_HINT =
  "Tell me what to set up — e.g. “auto mass to fans every hour, delete after 8h, SFW folder, 10 captions”. "
  + "I can set up a new Auto Mass or Auto Story (saved OFF — you turn it on) or change unsend, schedule, "
  + "online-only, skip-recent-chats or turn off on your existing Auto Masses, here or on every model.";

/** The plan card's text, pure (DoMode.test.ts): the flow's plain-words lines, the draft's assumptions and open
 *  questions, and the fixed note. */
export function planCardText(d: DoDraft): { lines: string[]; assumptions: string[]; unresolved: string[]; note: string } | null {
  const flow = canStart(d) ? boundFlow(d) : null;
  if (!flow) return null;
  return { lines: flow.planLines, assumptions: d.assumptions, unresolved: d.unresolved, note: PLAN_NOTE };
}

/** The fixed note under an edit plan card. */
export const EDIT_NOTE = "Nothing gets switched on — rules that are off stay off. LIVE = on now and will send more.";

function Notes({ assumptions, unresolved }: { assumptions: string[]; unresolved: string[] }) {
  return (
    <>
      {assumptions.length > 0 && (
        <div className="mt-3">
          <div className="text-[12px] font-medium text-[#6d6f74]">I assumed</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[#3a3c40]">
            {assumptions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        </div>
      )}
      {unresolved.length > 0 && (
        <div className="mt-3 rounded-lg bg-[#fff6e5] px-3 py-2 text-[#8a5a00]" role="note">
          <div className="flex items-center gap-1.5 text-[12px] font-medium">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />Couldn&apos;t match
          </div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {unresolved.map((u) => <li key={u}>{u}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}

/** The mass_edit plan card: the change, "N rules · M models", each model's rules with before → after. */
function EditPlanCard({ draft, slots, children }: { draft: DoDraft; slots: MassEditSlots; children?: ReactNode }) {
  const t = editPlanText(slots);
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-[#14161a]")} data-testid="do-edit-plan">
      <div className="mb-1 text-[14px] font-semibold">Change existing Auto masses</div>
      <ul className="space-y-0.5">{t.changes.map((l) => <li key={l} className="font-medium">{l}</li>)}</ul>
      <div className="mt-2 text-[12px] text-[#6d6f74]">{t.headline}</div>
      <div className="mt-1 max-h-[40vh] space-y-2 overflow-y-auto">
        {t.groups.map((g) => (
          <div key={g.model}>
            <div className="text-[12px] font-semibold text-[#3a3c40]">{g.model}</div>
            <ul className="space-y-1 pl-2">
              {g.rules.map((r) => (
                <li key={r.id} className="break-words">
                  <span className="font-medium">{r.name}</span>
                  {r.live && <span className="ml-1.5 rounded bg-[#ffe9e6] px-1 text-[11px] font-semibold text-[#b42318]">LIVE</span>}
                  {r.lines.map((l) => <div key={l} className="text-[#3a3c40]">{l}</div>)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {t.notes.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-[#6d6f74]">{t.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <Notes assumptions={draft.assumptions} unresolved={draft.unresolved} />
      <p className="mt-3 text-[12px] text-[#6d6f74]">{EDIT_NOTE}</p>
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/** The apply's per-rule outcome: ✓ or the skip reason. */
function EditResults({ results, slots }: { results: EditResult[]; slots: MassEditSlots }) {
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-[#14161a]")} role="status" data-testid="do-edit-results">
      <div className="flex items-center gap-2 font-semibold">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-[#1a7f37]" aria-hidden />{resultHeadline(results)}
      </div>
      <ul className="mt-2 space-y-0.5">
        {resultLines(results, slots).map((l) => (
          <li key={l.id} className={l.ok ? "text-[#1a7f37]" : "text-[#8a5a00]"}>{l.text}</li>
        ))}
      </ul>
    </div>
  );
}

/** The do-mode conversation for a mass_edit draft: plan card → applying → results (no cursor, no Stop once out). */
function EditThread({ run, draft, slots, on, request }: {
  run: Exclude<DoRun, { phase: "off" | "idle" | "drafting" }>; draft: DoDraft; slots: MassEditSlots; on: DoCallbacks; request: ReactNode;
}) {
  return (
    <>
      {request}
      {run.phase === "planned" ? (
        <EditPlanCard draft={draft} slots={slots}>
          <button type="button" className={BTN_MAIN} onClick={on.start}>Do it</button>
          <button type="button" className={BTN_SOFT} onClick={on.cancel}>Cancel</button>
        </EditPlanCard>
      ) : <EditPlanCard draft={draft} slots={slots} />}
      {run.phase === "running" && (
        <div className={cn(BUBBLE_BOT, "text-fg")} role="status"><span className="animate-pulse">Changing the rules…</span></div>
      )}
      {run.phase === "done" && <EditResults results={run.results ?? []} slots={slots} />}
      {(run.phase === "aborted" || run.phase === "failed") && (
        <>
          <div className={cn(BUBBLE_BOT, "text-fg-dim")} role="status">
            {run.phase === "failed"
              ? `Couldn't finish: ${run.msg.trim().replace(/[.\s]*$/, ".")} Some rules may have changed — check the Auto mass table.`
              : `${run.reason}.`}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={BTN_SOFT} onClick={on.cancel}>Start over</button>
          </div>
        </>
      )}
    </>
  );
}

function PlanCard({ draft, children }: { draft: DoDraft; children?: ReactNode }) {
  const t = planCardText(draft);
  if (!t) return null;
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-[#14161a]")} data-testid="do-plan">
      <div className="mb-2 text-[14px] font-semibold">Plan</div>
      <ul className="space-y-1">
        {t.lines.map((l) => <li key={l} className="break-words">{l}</li>)}
      </ul>
      <Notes assumptions={t.assumptions} unresolved={t.unresolved} />
      <p className="mt-3 text-[12px] text-[#6d6f74]">{t.note}</p>
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

export interface DoCallbacks {
  start: () => void;
  skipAnimation: () => void;
  cancel: () => void;
  stop: () => void;
  /** Send the request to Q&A instead (a flow:null draft). */
  askAsQuestion: (request: string) => void;
}

/** The do-mode conversation. `text` renders an answer (markdown + links) like a Q&A bubble. */
export function DoThread({ run, on, text }: { run: DoRun; on: DoCallbacks; text: (body: string, muted?: boolean) => ReactNode }) {
  if (run.phase === "off") return null;
  if (run.phase === "idle") return <div className={cn(BUBBLE_BOT, "text-fg")}>{DO_HINT}</div>;
  const request = <div className={BUBBLE_ME}>{run.request}</div>;
  if (run.phase === "drafting") {
    return (
      <>
        {request}
        <div className={cn(BUBBLE_BOT, "text-fg-dim animate-pulse")}>planning…</div>
      </>
    );
  }
  const draft = run.draft;
  if (run.phase === "failed" && !draft) {
    return <>{request}<div className={cn(BUBBLE_BOT, "text-fg-dim")}>{run.msg}</div></>;
  }
  if (!draft) return null;
  if (!canStart(draft)) {
    // Not a flow the bot can do (or the draft failed): its sentence, and the Q&A swap.
    return (
      <>
        {request}
        <div className={cn(BUBBLE_BOT, draft.error ? "text-fg-dim" : "text-fg")}>{text(draft.answer, !!draft.error)}</div>
        <button type="button" className={cn(BTN_SOFT, "self-start")} onClick={() => on.askAsQuestion(run.request)}>
          Ask as a question
        </button>
      </>
    );
  }
  if (draft.flow === "mass_edit") return <EditThread run={run} draft={draft} slots={draft.slots} on={on} request={request} />;
  const flow = boundFlow(draft);
  if (!flow) return null;
  const total = flow.steps.length;
  return (
    <>
      {request}
      {run.phase === "planned" ? (
        <PlanCard draft={draft}>
          <button type="button" className={BTN_MAIN} onClick={on.start}>Do it</button>
          <button type="button" className={BTN_SOFT} onClick={on.skipAnimation}>Skip animation</button>
          <button type="button" className={BTN_SOFT} onClick={on.cancel}>Cancel</button>
        </PlanCard>
      ) : <PlanCard draft={draft} />}
      {run.phase === "running" && (
        <div className={cn(BUBBLE_BOT, "flex flex-wrap items-center gap-2 text-fg")} role="status">
          {run.saving ? <span className="animate-pulse">Saving…</span> : (
            <>
              <span className="animate-pulse">Doing it… step {Math.min(run.step + 1, total)} of {total}</span>
              {!run.instant && <button type="button" className={BTN_SOFT} onClick={on.skipAnimation}>Skip animation</button>}
              <button type="button" className={BTN_MAIN} onClick={on.stop}>Stop</button>
            </>
          )}
        </div>
      )}
      {run.phase === "done" && (
        <div className={cn(CARD, "flex items-start gap-3 px-5 py-4 text-[13px] text-[#14161a]")} role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#1a7f37]" aria-hidden />
          <span>{flow.doneText}</span>
        </div>
      )}
      {(run.phase === "aborted" || run.phase === "failed") && (
        <>
          <div className={cn(BUBBLE_BOT, "text-fg-dim")} role="status">
            {run.phase === "aborted"
              ? `${run.reason}. The page is left as it was — nothing more is filled in or saved.`
              : `Couldn't finish: ${run.msg.trim().replace(/[.\s]*$/, ".")} The editor is left open for you.`}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={BTN_MAIN} onClick={on.start}>Do it again</button>
            <button type="button" className={BTN_SOFT} onClick={on.cancel}>Start over</button>
          </div>
        </>
      )}
    </>
  );
}

/** Phone: the pill instead of the sheet — while running, and after a run (not a failed draft) until the user taps
 *  Open on that outcome (`expanded`, the run object they opened). */
export function pillFor(run: DoRun, expanded: DoRun | null): boolean {
  if (run.phase === "running") return true;
  const ranOver = run.phase === "done" || run.phase === "aborted" || (run.phase === "failed" && run.draft !== null);
  return ranOver && expanded !== run;
}

/** The pill's short outcome line once the run is over (DoMode.test.ts). */
export function pillStatus(run: DoRun): string {
  if (run.phase === "done") return run.results ? resultHeadline(run.results) : "Created OFF";
  if (run.phase === "aborted") return "Stopped";
  if (run.phase === "failed") return "Couldn't finish";
  return run.phase === "running" && run.saving ? "Saving…" : "Doing it…";
}

/** Phone portrait during a run and after it: the sheet folds to this pill so the form under it shows. Running → Stop
 *  (none once saving); over → the outcome and Open (back to the sheet with the full card). */
export function DoPill({ run, onStop, onOpen }: { run: DoRun; onStop: () => void; onOpen: () => void }) {
  const running = run.phase === "running";
  const btn = "h-9 rounded-full bg-white px-4 text-[14px] font-medium text-black";
  return (
    <div
      data-assistant-ui
      role="status"
      className={cn(
        "fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom))] z-[60] mx-auto flex w-max items-center gap-3",
        "rounded-full bg-[#151515] py-1.5 pl-4 pr-1.5 text-[14px] text-white shadow-[0_4px_16px_rgba(0,0,0,0.35)]",
      )}
    >
      <span className={cn(running && "animate-pulse")}>{pillStatus(run)}</span>
      {running
        ? !run.saving && <button type="button" onClick={onStop} className={btn}>Stop</button>
        : <button type="button" onClick={onOpen} className={btn}>Open</button>}
    </div>
  );
}
