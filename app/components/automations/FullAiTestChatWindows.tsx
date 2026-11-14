"use client";

/**
 * Full AI Chat's Test chat: two windows, Checkpoint (left, the saved config) and Draft (right), and one composer that
 * sends his Fan line to both. Each window keeps its own thread, shows typing dots while its reply is pending or
 * waiting out `wait_s`, then her bubbles and the line under them (Route, Heat, row, the Writer and how many fell).
 * On a phone held upright the windows are Checkpoint / Draft tabs. State: `fullAiTestChat.ts` (pure reducer) through
 * `useFullAiTestChat` (requests, timers), held by the page; this file only renders and dispatches. Send waits with
 * "Save draft first" while a draft edit is unstored or storing (`sendBlock`). Each window header names its side's config
 * (`configLine`): the checkpoint's, or the draft as shown, so an applied draft shows there at once (ticket 57).
 * ASSUMPTION: named FullAiTestChatWindows, not the spec's FullAiTestChat.tsx: on a case-insensitive disk (macOS) the
 * import path `@/components/automations/FullAiTestChat` resolves to the reducer `fullAiTestChat.ts` (TS1149, observed),
 * because `.ts` is tried before `.tsx` (rung 1 for the clash, rung 5 for the name). Overturned by a reducer rename.
 */

import { useState, type KeyboardEvent } from "react";

import {
  canSend, configLine, factsLine, sendBlock, noReplyText, outcomesLine, replyLine,
  type FullAiConfig, type Part, type SideState, type Turn, type TurnResponse, type UiSide,
} from "@/components/automations/fullAiTestChat";
import { IfButton, IfSwitch, IfTabs, IfTextArea } from "@/components/ui/infloww";
import type { FullAiTestChatApi } from "@/hooks/useFullAiTestChat";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { MP } from "@/lib/messagesPro";
import { giphyUrl } from "@/lib/ofMedia";
import { cn } from "@/lib/utils";

/** Tailwind's `sm` breakpoint: below it (a phone held upright) the two windows become tabs. */
export const PHONE_QUERY = "(max-width: 639px)";
/** The test-turn route's `text` cap (service/full_ai_api.py); a longer line is a 422 that Retry cannot fix. */
const FAN_TEXT_MAX = 2000;
const TITLE: Record<UiSide, string> = { L: "Checkpoint", R: "Draft" };
const SUB: Record<UiSide, string> = { L: "saved config", R: "your draft" };

/** `chat` = the page's `useFullAiTestChat` (the settings column shares its state). */
export function FullAiTestChat({ chat }: { chat: FullAiTestChatApi }) {
  const { state, edit, send, retry, toggleSkip, newChat } = chat;
  const blocked = sendBlock(state);
  // Which window a phone shows; one value, nothing else depends on it.
  const [tab, setTab] = useState<UiSide>("L");
  const phone = useMediaQuery(PHONE_QUERY);

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  const shown: UiSide[] = phone ? [tab] : ["L", "R"];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4">
        <IfSwitch checked={state.skipWait} onChange={toggleSkip} label="Skip wait" />
        <IfButton onClick={newChat}>New chat</IfButton>
      </div>
      {phone && (
        <IfTabs aria-label="Test chat windows" className="px-0" value={tab} onChange={setTab}
          tabs={[{ value: "L", label: TITLE.L }, { value: "R", label: TITLE.R }]} />
      )}
      <div className={cn("grid gap-3", !phone && "grid-cols-2")}>
        {shown.map((ui) => (
          <Window key={ui} ui={ui} side={state.sides[ui]} cfg={ui === "L" ? state.checkpoint : state.draft} onRetry={() => retry(ui)} />
        ))}
      </div>
      <div className="flex items-end gap-2">
        <IfTextArea aria-label="Fan message" rows={2} placeholder="Type as the fan…" value={state.text}
          onChange={(e) => edit(e.target.value)} onKeyDown={onKey} className="min-h-10" maxLength={FAN_TEXT_MAX} />
        <IfButton variant="primary" size="lg" disabled={!canSend(state)} onClick={send}>Send</IfButton>
      </div>
      {blocked && <p role="status" className="text-xs text-warn">{blocked}</p>}
    </div>
  );
}

function Window({ ui, side, cfg, onRetry }: { ui: UiSide; side: SideState; cfg: FullAiConfig | null; onRetry: () => void }) {
  // The newest reply stays hidden until its wait is over.
  const hidden = side.revealAt !== null;
  const shownTurns = hidden ? side.turns.slice(0, -1) : side.turns;
  const last = shownTurns[shownTurns.length - 1];
  const waiting = hidden ? side.turns[side.turns.length - 1] : null;
  const p = side.pending;
  return (
    <section aria-label={TITLE[ui]} className="flex min-h-80 flex-col rounded-lg border border-border">
      <div className="border-b border-border px-3 py-2">
        <div className="text-sm font-semibold text-fg">
          {TITLE[ui]} <span className="font-normal text-muted">· {SUB[ui]}</span>
        </div>
        {cfg && <div data-testid="config" className="text-xs text-muted">{configLine(cfg)}</div>}
        <div data-testid="facts" className="text-xs text-fg-dim">{factsLine(last?.result.fan_info)}</div>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {shownTurns.map((t) => <Exchange key={t.n} turn={t} />)}
        {waiting && <><His text={waiting.text} /><Dots /></>}
        {p && <His text={p.text} />}
        {p?.inFlight && <Dots />}
        {p && !p.inFlight && (
          <div className="flex items-center gap-2 text-xs text-err">
            <span>{p.error}</span>
            <IfButton onClick={onRetry}>Retry</IfButton>
          </div>
        )}
      </div>
    </section>
  );
}

function Exchange({ turn }: { turn: Turn }) {
  const r = turn.result;
  return (
    <>
      <His text={turn.text} />
      <CreatorReply result={r} />
    </>
  );
}

function His({ text }: { text: string }) {
  return (
    <div className="flex justify-start">
      <div className={cn(MP.ours.FullAiTestChatWindows.bubbleWidth, "whitespace-pre-wrap break-words text-fg", MP.messageList.bubble,
        MP.messageList.bubbleTailIn, "bg-[var(--inf-bubble-in,var(--color-bg-elev-1))]")}>{text}</div>
    </div>
  );
}

function CreatorReply({ result }: { result: TurnResponse }) {
  const none = noReplyText(result);
  return (
    <div className="flex flex-col items-end gap-1">
      {none ? (
        <p className={cn(MP.ours.FullAiTestChatWindows.noReply, "text-fg-dim")}>{none}</p>
      ) : (
        result.parts.map((part, i) => <HerPart key={i} part={part} />)
      )}
      {result.status === "failed" && result.attempts.length > 0 && (
        <p className={cn(MP.ours.FullAiTestChatWindows.meta, "text-right text-err")}>{outcomesLine(result.attempts)}</p>
      )}
      <p data-testid="reply-line" className={cn(MP.ours.FullAiTestChatWindows.meta, "text-right text-muted")}>{replyLine(result)}</p>
    </div>
  );
}

function HerPart({ part }: { part: Part }) {
  if ("gif" in part) {
    return (
      <div className={cn("block overflow-hidden", MP.ours.MessageList.gif, MP.ours.MessageList.gifWidthCompact)}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={giphyUrl(part.gif)} alt={`GIF ${part.tag}`} loading="lazy" className="h-auto w-full object-cover" />
      </div>
    );
  }
  return (
    <div className={cn(MP.ours.FullAiTestChatWindows.bubbleWidth, "whitespace-pre-wrap break-words bg-accent text-white", MP.messageList.bubble,
      MP.messageList.bubbleTailOut)}>{part.text}</div>
  );
}

function Dots() {
  return (
    <div role="status" aria-label="typing" className="flex justify-end">
      <span className={cn(MP.ours.FullAiTestChatWindows.dots, "inline-flex bg-accent/20", MP.messageList.bubble)}>
        {[0, 1, 2].map((i) => (
          <span key={i} aria-hidden className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent"
            style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
    </div>
  );
}
