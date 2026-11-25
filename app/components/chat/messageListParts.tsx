import type { OFMessage } from "@/lib/relay";
import type { BubbleTranslation } from "@/hooks/useTranslations";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { isOfHtml, ofPlainText } from "@/lib/ofRichText";
import { OfRichText } from "./OfRichText";

export function dateDividerLabel(iso: string, now: Date): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (localDateKey(iso) === localDateKey(now.toISOString())) return "Today";
  return d.toLocaleDateString(undefined, d.getFullYear() === now.getFullYear()
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" });
}

export interface RunLabel {
  sentBy: string | null;
  receipt: "delivered" | "seen" | null;
}

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
  const fromOwner =
    ownerUserId != null && replyTo.fromUser?.id === ownerUserId;
  const author =
    fromOwner
      ? "You"
      : replyTo.fromUser?.name || replyTo.fromUser?.username || "fan";
  const preview = replyTo.text
    ? ofPlainText(replyTo.text)
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

// Never wait on the async owner id: seeded rows carry _side from the direction column, optimistic sends (tempId < 0) are ours.
export function resolveSide(
  m: OFMessage,
  ownerUserId: number | null,
): "left" | "right" {
  const explicit = (m as { _side?: "left" | "right" })._side;
  if (explicit === "left" || explicit === "right") return explicit;
  if ((m._tempId ?? 0) < 0) return "right";
  return ownerUserId != null && m.fromUser?.id === ownerUserId ? "right" : "left";
}

const LANG_TAG_COLOR: Record<string, string> = {
  es: "text-warn",
  sl: "text-accent",
  pt: "text-ok",
  fr: "text-info",
  de: "text-warn",
  it: "text-ok",
};

export function TranslatableText({ raw, translation, textClassName }: {
  raw: string;
  translation?: BubbleTranslation | null;
  textClassName?: string;
}) {
  const original = ofPlainText(raw);
  const t = translation;
  const show = !!t?.text && t.lang !== "en"
    && t.text.trim().toLowerCase() !== original.trim().toLowerCase();
  if (!show && !isOfHtml(raw)) return <span className={textClassName}>{original}</span>;
  if (!show) return <OfRichText raw={raw} className={textClassName} />;
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
