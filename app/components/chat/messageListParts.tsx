/**
 * MessageList's small parts: a bubble's side, its text (HTML stripped, the 🌐
 * translate layer), its quote card, the Date divider and the Thread's runs.
 * MessageList re-exports the public ones.
 */

import type { OFMessage } from "@/lib/relay";
import type { BubbleTranslation } from "@/hooks/useTranslations";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";

/** A Date divider's label (Phase 4 spec T4, F5): "Today" on `now`'s local
 *  day, the short month and day ("Sep 29") on another day of `now`'s year,
 *  yesterday included, and the year added in another year ("Sep 29, 2025"),
 *  in the browser locale. */
export function dateDividerLabel(iso: string, now: Date): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (localDateKey(iso) === localDateKey(now.toISOString())) return "Today";
  return d.toLocaleDateString(undefined, d.getFullYear() === now.getFullYear()
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" });
}

/** What a bubble's time row shows besides the time: its "Sent by" label and,
 *  on our side, its receipt. */
export interface RunLabel {
  sentBy: string | null;
  receipt: "delivered" | "seen" | null;
}

/** A Thread's runs (Phase 4 spec, Interfaces): consecutive messages on one
 *  side, on one local day and in one displayed minute, with the same "Sent by"
 *  label and, on our side, the same receipt. A pending, failed or
 *  future-scheduled message is a run of its own. `labels[i]` is
 *  `messages[i]`'s. A run's avatar sits on its last bubble. */
export function messageRuns(messages: OFMessage[], ownerUserId: number | null, labels: RunLabel[]): OFMessage[][] {
  const runs: OFMessage[][] = [];
  let prev: string | null = null;
  messages.forEach((m, i) => {
    const key = m._pending || m._failed || m._isFutureScheduled ? null : runKey(m, ownerUserId, labels[i]);
    if (key !== null && key === prev) runs[runs.length - 1].push(m);
    else runs.push([m]);
    prev = key;
  });
  return runs;
}

function runKey(m: OFMessage, ownerUserId: number | null, label: RunLabel): string {
  const side = (m._tempId ?? 0) < 0 ? "right" : resolveSide(m, ownerUserId);
  const d = new Date(m.createdAt ?? "");
  const minute = Number.isNaN(d.getTime()) ? "" : `${localDateKey(m.createdAt!)}-${d.getHours()}-${d.getMinutes()}`;
  return JSON.stringify([side, minute, label.sentBy, side === "right" ? label.receipt : null]);
}

export function QuoteCard({
  replyTo, side, ownerUserId, onClick,
}: {
  replyTo: NonNullable<OFMessage["replyToMessage"]>;
  side: "left" | "right";
  ownerUserId: number | null;
  onClick: () => void;
}) {
  // Decide who originated the quoted message — same direction test the
  // host bubble uses. Label "You" vs the author name so the chatter can
  // tell at a glance whether they're replying to their own send or the fan.
  const fromOwner =
    ownerUserId != null && replyTo.fromUser?.id === ownerUserId;
  const author =
    fromOwner
      ? "You"
      : replyTo.fromUser?.name || replyTo.fromUser?.username || "fan";
  const preview = replyTo.text
    ? stripHtml(replyTo.text)
    : replyTo.mediaCount
    ? `(${replyTo.mediaCount} media)`
    : "(message)";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        MP.ours.MessageList.quote, "block w-full text-left",
        side === "right"
          ? "bg-white/10 border-white/60 hover:bg-white/15"
          : "bg-black/10 border-fg/40 hover:bg-black/15",
      )}
      title="Jump to quoted message"
    >
      <div className={side === "right" ? "font-semibold text-white" : "font-semibold text-fg"}>
        {author}
      </div>
      <div className={cn("truncate", side === "right" ? "text-white/85" : "text-fg-dim")}>
        {preview || "(empty)"}
      </div>
    </button>
  );
}

/** Which side a bubble sits on, resolved WITHOUT comparing ids against an
 *  async fetch. Priority:
 *   1. An explicit `_side` carried on the row — DB-seed rows derive it from
 *      the authoritative `direction` column (mapped in useChatMessagesLocal),
 *      so seeded text never has to wait on the owner id.
 *   2. Optimistic outbound (tempId < 0) — always ours, even before OF echoes
 *      a real fromUser.id.
 *   3. Live OF rows (no `direction`): compare fromUser.id to ownerUserId.
 *      ownerUserId is now hydrated synchronously from a per-account
 *      localStorage cache in ChatSurface, so the FIRST paint already has it
 *      and there is no left-then-right jump.
 *  relay.ts owns OFMessage; `_side` rides along as an optional intersection
 *  field rather than widening that shared type. */
export function resolveSide(
  m: OFMessage,
  ownerUserId: number | null,
): "left" | "right" {
  const explicit = (m as { _side?: "left" | "right" })._side;
  if (explicit === "left" || explicit === "right") return explicit;
  if ((m._tempId ?? 0) < 0) return "right";
  return ownerUserId != null && m.fromUser?.id === ownerUserId ? "right" : "left";
}

/** OF returns message bodies as HTML — strip tags AND decode the most
 *  common entities so bubbles render as plain text without leaking
 *  `<br>` / `&amp;` artifacts. We avoid `dangerouslySetInnerHTML` so
 *  malformed input from OF can never inject markup into our chat. */
export function stripHtml(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

// Per-language color for the "(es)" tag — same code, same color everywhere so
// a chatter learns "amber = Spanish" at a glance. Unknown codes fall back to sky.
const LANG_TAG_COLOR: Record<string, string> = {
  es: "text-warn",
  sl: "text-accent",
  pt: "text-ok",
  fr: "text-info",
  de: "text-warn",
  it: "text-ok",
};

/** Bubble text with the 🌐 translate layer. When a translation exists and the
 *  detected language isn't English, render "(es)" (colored by language) + the
 *  English text; the original stays one hover away in the title tooltip.
 *  English / untranslated / toggle-off all render the plain original. */
export function TranslatableText({ raw, translation, textClassName }: {
  raw: string;
  translation?: BubbleTranslation | null;
  /** On the text span only, never the language tag: a PPV's title weight (ML11). */
  textClassName?: string;
}) {
  const original = stripHtml(raw);
  const t = translation;
  const show = !!t?.text && t.lang !== "en"
    && t.text.trim().toLowerCase() !== original.trim().toLowerCase();
  if (!show) return <span className={textClassName}>{original}</span>;
  return (
    <>
      <span
        className={cn(
          MP.ours.MessageList.langTag, "self-center",
          LANG_TAG_COLOR[t.lang] ?? "text-info",
        )}
      >
        ({t.lang})
      </span>
      <span className={textClassName} title={original}>{t.text}</span>
    </>
  );
}

export function localDateKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function DateSeparator({ label }: { label: string }) {
  return (
    <div
      className={cn("flex items-center select-none", MP.messageList.divider)}
      role="separator"
      aria-label={label}
    >
      <div className="flex-1 h-px bg-[var(--inf-date-rule,var(--color-border))]" />
      <span className={cn(MP.messageList.dividerLabel, "text-fg-dim")}>
        {label}
      </span>
      <div className="flex-1 h-px bg-[var(--inf-date-rule,var(--color-border))]" />
    </div>
  );
}
