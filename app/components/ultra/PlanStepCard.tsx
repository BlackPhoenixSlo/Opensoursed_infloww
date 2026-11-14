"use client";

/**
 * One step of an Ultra plan as the server's card draws it (service/ultra_decide.py `card`): its title, what kind of
 * step it is, its rows (a send: Creator, audience, price, media count, when; a judge: question, candidates, picks;
 * a write or read: every arg) and a send's FULL text exactly as it will go out. Once it ran: its state, the error,
 * the note (fewer fans than approved), the id it made (a send's OnlyFans id; a report file: ReportDownload) or
 * a judge's picks, and a link to where it landed. `data-step-num` / `data-state` let a container (the Ultra panel) style the number and a running
 * step's progress line.
 */
import Link from "next/link";

import { cn } from "@/lib/utils";
import { ReportDownload } from "./ReportDownload";
import { STEP_LABEL, type PlanCard, type StepStatus } from "./ultraRunReducer";

const EFFECT_LABEL: Record<PlanCard["effect"], string> = {
  send: "Sends to fans", write: "Changes", read: "Reads", judge: "AI picks",
};
/** Send tools that do not message fans now (service/toolbox_sends.py: post_create, RULE_KIND). */
const TOOL_LABEL: Record<string, string> = {
  post_create: "Posts to the feed", auto_mass: "Turns on a recurring rule", auto_story: "Turns on a recurring rule",
};
const STATE_TONE: Record<StepStatus["state"], string> = {
  pending: "text-fg-dim", started: "text-accent", needs_you: "text-accent", done: "text-ok", failed: "text-err",
  uncertain: "text-warn", skipped: "text-fg-dim",
};

export function PlanStepCard({ card, step, index, finishedAt = null }: {
  card: PlanCard;
  step: StepStatus | undefined;
  index: number;
  /** The plan's finished_at: a report file's link is known dead 15 minutes after it. */
  finishedAt?: string | null;
}) {
  const state = step?.state ?? "pending";
  const ids = step?.result?.ids;
  // report_file's id is the held file's (service/report_recipe_api.py GET /admin/reports/files/{id}, 15 min).
  const fileId = card.tool === "report_file" && state === "done" ? step?.result?.id : undefined;
  return (
    <li data-step={card.id} data-state={state}
      className={cn("relative rounded-[12px] bg-bg-elev-1 px-4 py-4 sm:px-6",
        card.effect === "send" && "ring-1 ring-accent/40")}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="min-w-0 break-words text-[15px] font-medium text-fg">
          <span data-step-num>{index + 1}.</span> {card.title}
          <span className="ml-2 text-[12px] font-normal text-fg-dim">{TOOL_LABEL[card.tool] ?? EFFECT_LABEL[card.effect]}</span>
        </h3>
        <span className={cn("text-[13px] font-medium", STATE_TONE[state])}>{STEP_LABEL[state]}</span>
      </div>
      <dl className="mt-3 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
        {card.rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-fg-dim">{label}</dt>
            <dd className="break-words text-fg">{value}</dd>
          </div>
        ))}
      </dl>
      {card.text !== undefined && (
        <div className="mt-3">
          <div className="text-[12px] text-fg-dim">Text, exactly as it goes out</div>
          <p data-step-text className="mt-1 whitespace-pre-wrap break-words rounded-md bg-bg px-3 py-2 text-[14px] text-fg">
            {card.text}
          </p>
        </div>
      )}
      {step?.error && <p className="mt-2 break-words text-[13px] text-err">{step.error}</p>}
      {step?.note && <p data-step-note className="mt-2 break-words text-[13px] text-warn">{step.note}</p>}
      {fileId !== undefined && (
        <ReportDownload fileId={String(fileId)} finishedAt={finishedAt}
          fallbackName={`report.${card.rows.find(([label]) => label === "format")?.[1] ?? "csv"}`} />
      )}
      {step?.result?.id !== undefined && fileId === undefined && (
        <p className="mt-2 break-words text-[13px] text-fg-dim">
          {card.tool.startsWith("auto_") ? "Rule id" : card.effect === "send" ? "OnlyFans id" : "Id"}: <span className="text-fg">{step.result.id}</span>
        </p>
      )}
      {ids && (
        <p data-step-picks className="mt-2 break-words text-[13px] text-fg-dim">
          Picked {step?.picked_by === "owner" ? "by you" : "by the AI"}: <span className="text-fg">{ids.join(", ")}</span>
        </p>
      )}
      {step?.open_url && state !== "pending" && state !== "skipped" && (
        <Link href={step.open_url} className="mt-2 inline-block text-[13px] text-accent hover:text-accent-hover">
          Open in the app
        </Link>
      )}
    </li>
  );
}
