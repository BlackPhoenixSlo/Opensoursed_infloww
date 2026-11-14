"use client";

/**
 * Full AI Chat's Test chat: two windows, Checkpoint (left, the saved config) and Draft (right), and one composer that
 * sends his Fan line to both. Each window keeps its own thread, shows typing dots while its reply is pending or
 * waiting out `wait_s`, then her bubbles and the line under them (Route, Heat, row, the Writer and how many fell).
 * On a phone held upright the windows are Checkpoint / Draft tabs. State: `fullAiTestChat.ts` (pure reducer) through
 * `useFullAiTestChat` (requests, timers), held by the page; this file only renders and dispatches. Send waits with
 * "Storing draft…" or "Draft not stored — fix it or Reload" (`sendBlock`). Each window header names its side's config
 * (`configLine`): the checkpoint's, or the draft as shown, so an applied draft shows there at once (ticket 57).
 * A reply with an Offer (ticket 49) shows its PPV bubble on the text part carrying `ppv`: from the Offer, the Pick's
 * thumbnails from the Creator's local vault mirror (`mirrorThumbSrc`) and `ppvLine` — the price with Buy / Decline under
 * it while `canSettle`, "$N · paid" / "$N · not paid" once settled (`PpvStatusLine`), or "Free".
 * His photo: the paperclip next to the composer attaches one JPG / PNG / GIF / WebP (up to 20 MB, the server's limit; the
 * server shrinks it as a downloaded frame is); his bubble shows the thumbnail and, once recorded, what that side read
 * (`photoCaption`: the description, or `[sent a photo or video]` with its `describe_fan_photos` off).
 * ASSUMPTION: named FullAiTestChatWindows, not the spec's FullAiTestChat.tsx: on a case-insensitive disk (macOS) the
 * import path `@/components/automations/FullAiTestChat` resolves to the reducer `fullAiTestChat.ts` (TS1149, observed),
 * because `.ts` is tried before `.tsx` (rung 1 for the clash, rung 5 for the name). Overturned by a reducer rename.
 */

import { Paperclip, X } from "lucide-react";
import { useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";

import {
  canSend, canSettle, configLine, factsLine, photoCaption, sendBlock, noReplyText, outcomesLine, ppvLine, replyLine,
  type Describing, type FanPhoto, type FullAiConfig, type Offer, type Outcome, type Part, type SideState, type Turn,
  type UiSide,
} from "@/components/automations/fullAiTestChat";
import { PPV_BORDER, PPV_FILL, PpvStatusLine, ppvPriceLabel } from "@/components/chat/PpvStatus";
import { MediaStrip } from "@/components/settings/MediaStrip";
import { IfButton, IfSwitch, IfTabs, IfTextArea } from "@/components/ui/infloww";
import type { FullAiTestChatApi } from "@/hooks/useFullAiTestChat";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { mirrorThumbSrc } from "@/lib/mediaUrl";
import { MP } from "@/lib/messagesPro";
import { giphyUrl } from "@/lib/ofMedia";
import { cn } from "@/lib/utils";

/** Tailwind's `sm` breakpoint: below it (a phone held upright) the two windows become tabs. */
export const PHONE_QUERY = "(max-width: 639px)";
/** The test-turn route's `text` cap (service/full_ai_api.py); a longer line is a 422 that Retry cannot fix. */
const FAN_TEXT_MAX = 2000;
/** The photo route's limits (service/automations/full_ai_photo.py, bio pages' upload rule). */
const PHOTO_TYPES = "image/jpeg,image/png,image/gif,image/webp";
const PHOTO_MAX = 20 * 1024 * 1024;

/** The picked file as a data URL, or the refusal in the server's words. */
function readPhoto(file: File): Promise<string> {
  if (!PHOTO_TYPES.split(",").includes(file.type)) return Promise.reject(new Error("Pick a JPG, PNG, GIF or WebP image."));
  if (file.size > PHOTO_MAX) return Promise.reject(new Error("The image is larger than 20 MB."));
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new Error("Could not read the image."));
    r.readAsDataURL(file);
  });
}
const TITLE: Record<UiSide, string> = { L: "Checkpoint", R: "Draft" };
const SUB: Record<UiSide, string> = { L: "saved config", R: "your draft" };

type OnSettle = (rowId: number, outcome: Outcome) => void;

/** `chat` = the page's `useFullAiTestChat` (the settings column shares its state); `accountId` = the Creator whose
 *  vault mirror serves the PPV thumbnails. */
export function FullAiTestChat({ chat, accountId }: { chat: FullAiTestChatApi; accountId: string }) {
  const { state, edit, attach, detach, send, retry, toggleSkip, newChat, settle } = chat;
  const blocked = sendBlock(state);
  const fileRef = useRef<HTMLInputElement>(null);
  // A file the browser could not read or the limits refuse: one message, cleared by the next pick.
  const [pickError, setPickError] = useState<string | null>(null);
  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    readPhoto(file).then((url) => { setPickError(null); attach(url); }, (err: Error) => setPickError(err.message));
  };
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
          <Window key={ui} ui={ui} side={state.sides[ui]} cfg={ui === "L" ? state.checkpoint : state.draft} accountId={accountId}
            describing={state.describing} onRetry={() => retry(ui)} onSettle={(rowId, outcome) => settle(ui, rowId, outcome)} />
        ))}
      </div>
      {state.photo && (
        <div className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={state.photo} alt="Attached photo" className="h-14 w-14 rounded-md object-cover" />
          <IfButton icon={X} aria-label="Remove photo" onClick={detach}>Remove</IfButton>
        </div>
      )}
      <div className="flex items-end gap-2">
        <input ref={fileRef} type="file" accept={PHOTO_TYPES} className="hidden" onChange={onPick} data-testid="photo-input" />
        <IfButton size="lg" icon={Paperclip} aria-label="Attach photo" title="Attach photo"
          disabled={state.describing !== null} onClick={() => fileRef.current?.click()} />
        <IfTextArea aria-label="Fan message" rows={2} placeholder="Type as the fan…" value={state.text}
          onChange={(e) => edit(e.target.value)} onKeyDown={onKey} className="min-h-10" maxLength={FAN_TEXT_MAX} />
        <IfButton variant="primary" size="lg" disabled={!canSend(state)} onClick={send}>Send</IfButton>
      </div>
      {blocked && <p role="status" className="text-xs text-warn">{blocked}</p>}
      {(pickError || state.photoError) && <p role="alert" className="text-xs text-err">{pickError || state.photoError}</p>}
    </div>
  );
}

function Window({ ui, side, cfg, accountId, describing, onRetry, onSettle }: {
  ui: UiSide; side: SideState; cfg: FullAiConfig | null; accountId: string; describing: Describing | null;
  onRetry: () => void; onSettle: OnSettle;
}) {
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
        {shownTurns.map((t) => <Exchange key={t.n} turn={t} accountId={accountId} onSettle={onSettle} />)}
        {waiting && <><His text={waiting.text} photo={waiting.photo} /><Dots /></>}
        {describing && <><His text={describing.text} image={describing.image} />
          <p role="status" className="text-xs text-muted">Reading his photo…</p></>}
        {p && <His text={p.text} photo={p.photo} />}
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

function Exchange({ turn, accountId, onSettle }: { turn: Turn; accountId: string; onSettle: OnSettle }) {
  return (
    <>
      <His text={turn.text} photo={turn.photo} />
      <CreatorReply turn={turn} accountId={accountId} onSettle={onSettle} />
    </>
  );
}

/** His line; with a photo, its thumbnail (`image` before the photo route answered) and, once recorded (`read` set),
 *  what this side read in small type. */
function His({ text, photo, image }: { text: string; photo?: FanPhoto | null; image?: string }) {
  const src = photo?.thumb ?? image;
  return (
    <div className="flex justify-start">
      <div className={cn(MP.ours.FullAiTestChatWindows.bubbleWidth, "whitespace-pre-wrap break-words text-fg", MP.messageList.bubble,
        MP.messageList.bubbleTailIn, "bg-[var(--inf-bubble-in,var(--color-bg-elev-1))]")}>
        <div className="flex flex-col gap-1">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {src && <img src={src} alt="His photo" className="max-h-48 w-auto max-w-full rounded-md object-contain" />}
          {text && <span>{text}</span>}
          {photo && photo.read !== undefined && (
            <span data-testid="photo-caption" className="text-xs text-muted">{photoCaption(photo)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

function CreatorReply({ turn, accountId, onSettle }: { turn: Turn; accountId: string; onSettle: OnSettle }) {
  const result = turn.result;
  const none = noReplyText(result);
  return (
    <div className="flex flex-col items-end gap-1">
      {none ? (
        <p className={cn(MP.ours.FullAiTestChatWindows.noReply, "text-fg-dim")}>{none}</p>
      ) : (
        // `ppv` marks the bubble; the server sends it exactly when the row has an Offer, which holds what it shows.
        result.parts.map((part, i) => ("text" in part && part.ppv && result.offer && result.row_id !== null
          ? <PpvBubble key={i} text={part.text} offer={result.offer} turn={turn} rowId={result.row_id} accountId={accountId}
            onSettle={onSettle} />
          : <HerPart key={i} part={part} />))
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

/** Her PPV message: caption, the Pick's thumbnails (locked media, then previews) and `ppvLine` — the price with Buy /
 *  Decline under it while `canSettle`, a settled outcome, or "Free". Everything comes from the row's Offer. */
function PpvBubble({ text, offer, turn, rowId, accountId, onSettle }: {
  text: string; offer: Offer; turn: Turn; rowId: number; accountId: string; onSettle: OnSettle;
}) {
  const media = [...offer.media, ...offer.previews].map((id) => ({ id }));
  const line = ppvLine(turn);
  const open = canSettle(turn);
  const pending = turn.settle?.kind === "pending" ? turn.settle.outcome : null;
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div data-testid="ppv" className={cn("flex flex-col whitespace-pre-wrap break-words text-white", MP.messageList.ppv,
        PPV_BORDER, PPV_FILL)}>
        <span className={MP.messageList.ppvTitle}>{text}</span>
        <MediaStrip media={media} accountId={accountId} thumbSrc={(m) => mirrorThumbSrc(accountId, m.id)} />
        {line?.kind === "settled" && <PpvStatusLine price={line.dollars} paid={line.paid} />}
        {line?.kind === "price" && <div className={MP.messageList.paidTag}>{ppvPriceLabel(line.dollars)}</div>}
        {line?.kind === "free" && <div className={MP.messageList.paidTag}>Free</div>}
      </div>
      {(open || pending) && (
        <div className="flex gap-2">
          <IfButton variant="primary" disabled={!open} onClick={() => onSettle(rowId, "bought")}>
            {pending === "bought" ? "Buying…" : "Buy"}
          </IfButton>
          <IfButton disabled={!open} onClick={() => onSettle(rowId, "declined")}>
            {pending === "declined" ? "Declining…" : "Decline"}
          </IfButton>
        </div>
      )}
      {turn.settle?.kind === "failed" && <p role="alert" className="text-xs text-err">{turn.settle.error}</p>}
    </div>
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
