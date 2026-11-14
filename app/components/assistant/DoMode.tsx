"use client";

/** The help bot's "Do it for me" pieces (docs/spec/assistant-do-mode.md): the do-mode conversation (the request, the
 *  plan card from the server's draft, the run's progress and outcome) and the phone's pill ("Doing it… · Stop", then
 *  the outcome · Open).
 *  Presentation only: AssistantPanel passes the run (doRunReducer.ts) and its callbacks. */

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { boundFlow, PLAN_NOTE, type DoDraft } from "./doFlows";
import { exportPlanText, type ExportSlots } from "./doExport";
import { diffLine, type FullAiConfigSlots } from "./fullAiConfigEdit";
import { canStart, type DoOutcome, type DoRun } from "./doRunReducer";
import { editPlanText, resultHeadline, resultLines, type EditResult, type MassEditSlots } from "./massEdit";

/** The messenger's card (home screen cards, Do plan/results). */
export const CARD = "rounded-xl border border-border bg-bg-elev-1 [[data-look=messenger]_&]:bg-white [html[data-theme=light]_&]:bg-white px-6 py-[17px] leading-5 shadow-[0_2px_8px_rgba(0,0,0,0.06)]";

const BUBBLE_ME = "self-end max-w-[85%] rounded-2xl rounded-br-md bg-fg text-panel px-3.5 py-2 text-[13px] whitespace-pre-wrap break-words";
const BUBBLE_BOT = "self-start max-w-[92%] rounded-2xl rounded-bl-md bg-bg-elev-1 px-3.5 py-2 text-[13px] leading-relaxed break-words";
const BTN = "h-8 rounded-full px-3.5 text-[13px] font-medium transition-colors disabled:opacity-40";
const BTN_MAIN = cn(BTN, "bg-fg text-panel hover:opacity-90");
const BTN_SOFT = cn(BTN, "border border-border-light bg-panel text-fg hover:border-muted");

export const DO_HINT =
  "Tell me what to set up — e.g. “auto mass to fans every hour, delete after 8h, SFW folder, 10 captions”. "
  + "I can set up a new Auto Mass or Auto Story (saved OFF — you turn it on) or change unsend, schedule, "
  + "online-only, skip-recent-chats or turn off on your existing Auto Masses, here or on every model. "
  + "Owners can also export a report — e.g. “last month's sales per Creator as Excel”, "
  + "or change a Creator's Full AI Chat draft — e.g. “reply slower”.";

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
          <div className="text-[12px] font-medium text-fg-dim">I assumed</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-fg">
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
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-fg")} data-testid="do-edit-plan">
      <div className="mb-1 text-[14px] font-semibold">Change existing Auto masses</div>
      <ul className="space-y-0.5">{t.changes.map((l) => <li key={l} className="font-medium">{l}</li>)}</ul>
      <div className="mt-2 text-[12px] text-fg-dim">{t.headline}</div>
      <div className="mt-1 max-h-[40vh] space-y-2 overflow-y-auto">
        {t.groups.map((g) => (
          <div key={g.model}>
            <div className="text-[12px] font-semibold text-fg">{g.model}</div>
            <ul className="space-y-1 pl-2">
              {g.rules.map((r) => (
                <li key={r.id} className="break-words">
                  <span className="font-medium">{r.name}</span>
                  {r.live && <span className="ml-1.5 rounded bg-[#ffe9e6] px-1 text-[11px] font-semibold text-[#b42318]">LIVE</span>}
                  {r.lines.map((l) => <div key={l} className="text-fg">{l}</div>)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {t.notes.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-fg-dim">{t.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <Notes assumptions={draft.assumptions} unresolved={draft.unresolved} />
      <p className="mt-3 text-[12px] text-fg-dim">{EDIT_NOTE}</p>
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/** The apply's per-rule outcome: ✓ or the skip reason. */
function EditResults({ results, slots }: { results: EditResult[]; slots: MassEditSlots }) {
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-fg")} role="status" data-testid="do-edit-results">
      <div className="flex items-center gap-2 font-semibold">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-ok [html[data-theme=light]_&]:text-[#1a7f37]" aria-hidden />{resultHeadline(results)}
      </div>
      <ul className="mt-2 space-y-0.5">
        {resultLines(results, slots).map((l) => (
          <li key={l.id} className={l.ok ? "text-ok [html[data-theme=light]_&]:text-[#1a7f37]" : "text-warn [html[data-theme=light]_&]:text-[#8a5a00]"}>{l.text}</li>
        ))}
      </ul>
    </div>
  );
}

type ShownRun = Exclude<DoRun, { phase: "off" | "idle" | "drafting" }>;

/** A message as one sentence ending in a full stop. */
const sentence = (msg: string) => msg.trim().replace(/[.\s]*$/, ".");

/** The do-mode conversation for a flow with no steps (mass_edit, report_export, full_ai_config): the plan card with
 *  its start button → the busy line while the one request is out → `done(outcome)`, or the failure / abort line with Start
 *  over (and Try again, `retry`: a new attempt). `card` renders the flow's card around the planned buttons. */
function DirectThread({ run, on, request, card, startLabel, canGo = true, busy, done, failed, retry = false,
  startOverWhenDone = false }: {
  run: ShownRun; on: DoCallbacks; request: ReactNode; card: (actions?: ReactNode) => ReactNode; startLabel: string;
  canGo?: boolean; busy: string; done: (outcome: DoOutcome) => ReactNode; failed: (msg: string) => string; retry?: boolean;
  startOverWhenDone?: boolean;
}) {
  const ended = run.phase === "aborted" || run.phase === "failed";
  return (
    <>
      {request}
      {card(run.phase === "planned" ? (
        <>
          <button type="button" className={BTN_MAIN} onClick={on.start} disabled={!canGo}>{startLabel}</button>
          <button type="button" className={BTN_SOFT} onClick={on.cancel}>Cancel</button>
        </>
      ) : undefined)}
      {run.phase === "running" && (
        <div className={cn(BUBBLE_BOT, "text-fg")} role="status"><span className="animate-pulse">{busy}</span></div>
      )}
      {run.phase === "done" && done(run.outcome)}
      {ended && (
        <div className={cn(BUBBLE_BOT, "text-fg-dim")} role="status">
          {run.phase === "failed" ? failed(run.msg) : `${run.reason}.`}
        </div>
      )}
      {(ended || (startOverWhenDone && run.phase === "done")) && (
        <div className="flex flex-wrap gap-2">
          {retry && ended && <button type="button" className={BTN_MAIN} onClick={on.start}>Try again</button>}
          <button type="button" className={BTN_SOFT} onClick={on.cancel}>Start over</button>
        </div>
      )}
    </>
  );
}

/** mass_edit: plan card → applying → results (no cursor, no Stop once out). */
function EditThread({ run, draft, slots, on, request }: {
  run: ShownRun; draft: DoDraft; slots: MassEditSlots; on: DoCallbacks; request: ReactNode;
}) {
  return (
    <DirectThread
      run={run} on={on} request={request} startLabel="Do it" busy="Changing the rules…"
      card={(actions) => <EditPlanCard draft={draft} slots={slots}>{actions}</EditPlanCard>}
      done={(o) => <EditResults results={o.kind === "applied" ? o.results : []} slots={slots} />}
      failed={(msg) => `Couldn't finish: ${sentence(msg)} Some rules may have changed — check the Auto mass table.`}
    />
  );
}

/** The report_export plan card: what the file holds (no row count — that would cost a second run). */
function ExportPlanCard({ draft, slots, children }: { draft: DoDraft; slots: ExportSlots; children?: ReactNode }) {
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-fg")} data-testid="do-export-plan">
      <div className="mb-2 text-[14px] font-semibold">Export</div>
      <ul className="space-y-1">
        {exportPlanText(slots).map((l) => <li key={l} className="break-words">{l}</li>)}
      </ul>
      <Notes assumptions={draft.assumptions} unresolved={draft.unresolved} />
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/** report_export: plan card → Download → building → the saved file, or the error and Try again (a new attempt).
 *  Download stays off while a name is unresolved (canStart). */
function ExportThread({ run, draft, slots, on, request }: {
  run: ShownRun; draft: DoDraft; slots: ExportSlots; on: DoCallbacks; request: ReactNode;
}) {
  return (
    <DirectThread
      run={run} on={on} request={request} startLabel="Download" canGo={canStart(draft)} busy="Building the file…" retry
      card={(actions) => <ExportPlanCard draft={draft} slots={slots}>{actions}</ExportPlanCard>}
      done={(o) => (
        <div className={cn(CARD, "flex items-start gap-3 px-5 py-4 text-[13px] text-fg")} role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok [html[data-theme=light]_&]:text-[#1a7f37]" aria-hidden />
          <span className="break-words">Downloaded {o.kind === "downloaded" ? o.file : slots.filename}</span>
        </div>
      )}
      failed={(msg) => `Couldn't build the file: ${sentence(msg)}`}
    />
  );
}

/** The fixed note under a full_ai_config card: the assistant only edits the draft. */
export const CONFIG_NOTE = "Only the draft changes. Save on the Full AI Chat page makes it live.";

/** The full_ai_config card: the Creator, each changed setting before → after. */
function ConfigCard({ draft, slots, children }: { draft: DoDraft; slots: FullAiConfigSlots; children?: ReactNode }) {
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-sm text-fg")} data-testid="do-config-plan">
      <div className="mb-1 font-semibold">Change {slots.account_name || "this Creator"}&apos;s Full AI draft</div>
      <ul className="space-y-0.5">{slots.diffs.map((d) => <li key={d.field} className="break-words">{diffLine(d)}</li>)}</ul>
      <Notes assumptions={draft.assumptions} unresolved={draft.unresolved} />
      <p className="mt-3 text-xs text-fg-dim">{CONFIG_NOTE}</p>
      {children && <div className="mt-3 flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/** full_ai_config: card → Apply (one draft PUT) → the PUT's line (a 409 / 422 says why; no retry — ask again). */
function ConfigThread({ run, draft, slots, on, request }: {
  run: ShownRun; draft: DoDraft; slots: FullAiConfigSlots; on: DoCallbacks; request: ReactNode;
}) {
  return (
    <DirectThread
      run={run} on={on} request={request} startLabel="Apply to draft" busy="Updating the draft…" startOverWhenDone
      card={(actions) => <ConfigCard draft={draft} slots={slots}>{actions}</ConfigCard>}
      done={(o) => (
        <div className={cn(CARD, "flex items-start gap-3 px-5 py-4 text-sm text-fg")} role="status" data-testid="do-config-result">
          {o.kind === "config" && o.status === 200
            ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
            : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />}
          <span className="break-words">{o.kind === "config" ? o.line : ""}</span>
        </div>
      )}
      failed={(msg) => `Couldn't update the draft: ${sentence(msg)}`}
    />
  );
}

function PlanCard({ draft, children }: { draft: DoDraft; children?: ReactNode }) {
  const t = planCardText(draft);
  if (!t) return null;
  return (
    <div className={cn(CARD, "self-stretch px-5 py-4 text-[13px] text-fg")} data-testid="do-plan">
      <div className="mb-2 text-[14px] font-semibold">Plan</div>
      <ul className="space-y-1">
        {t.lines.map((l) => <li key={l} className="break-words">{l}</li>)}
      </ul>
      <Notes assumptions={t.assumptions} unresolved={t.unresolved} />
      <p className="mt-3 text-[12px] text-fg-dim">{t.note}</p>
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
  // An export with an unresolved name still shows its card (Download off), not the Q&A swap.
  if (draft.flow === "report_export" && draft.slots && !draft.error) {
    return <ExportThread run={run} draft={draft} slots={draft.slots} on={on} request={request} />;
  }
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
  if (draft.flow === "full_ai_config") return <ConfigThread run={run} draft={draft} slots={draft.slots} on={on} request={request} />;
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
        <div className={cn(CARD, "flex items-start gap-3 px-5 py-4 text-[13px] text-fg")} role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok [html[data-theme=light]_&]:text-[#1a7f37]" aria-hidden />
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
  if (run.phase === "done") {
    const o = run.outcome;
    if (o.kind === "config") return o.status === 200 ? "Draft updated" : "Not applied";
    return o.kind === "applied" ? resultHeadline(o.results) : o.kind === "downloaded" ? "Downloaded" : "Created OFF";
  }
  if (run.phase === "aborted") return "Stopped";
  if (run.phase === "failed") return "Couldn't finish";
  if (run.phase === "running" && run.draft.flow === "report_export") return "Building the file…";
  if (run.phase === "running" && run.draft.flow === "full_ai_config") return "Updating the draft…";
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
