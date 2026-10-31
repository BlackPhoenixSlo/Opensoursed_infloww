"use client";

/**
 * One Buys & tips rail row (`MoneyRail`): the payer, the amount, what was
 * paid for, when, and (`ReplyLine`) where the conversation stands.
 */

import { notificationHref, onNotificationClick } from "@/lib/notificationLink";
import { fmtPrice } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";
import type { NotifTypeKey } from "@/lib/notifSettings";
import { fmtTime, renderText } from "@/lib/notifText";
import type { MergedItem, ReplyState } from "./useMoneyRailFeed";

/** The amount in OF's notification text, in the house price format (real cents, no ".00"):
 *  "Jim has purchased your message for $25.22!" → "$25.22", "…sent you a $40.00 tip" → "$40".
 *  Only this rail's amount chip is reformatted; the notification text itself is shown as OF wrote it. */
export function amountFrom(text: string): string | null {
  const m = text.match(/\$\s?([\d,]+(?:\.\d{1,2})?)/);
  if (!m) return null;
  const dollars = Number(m[1].replace(/,/g, ""));
  return Number.isFinite(dollars) ? fmtPrice(Math.round(dollars * 100)) : `$${m[1]}`;
}

/** What was paid for — tips by typeKey, purchases split post/message/stream
 *  by the notification wording. */
function kindFrom(typeKey: NotifTypeKey, text: string): string {
  if (typeKey === "tip") return "tip";
  if (/\bpost\b/i.test(text)) return "post";
  if (/\bstream\b/i.test(text)) return "stream";
  return "message";
}

export function Row({
  m,
  accountLabel,
  reply,
  dim = false,
}: {
  m: MergedItem;
  accountLabel: string | null;
  reply: ReplyState | null;
  /** Last session's snapshot, still being revalidated for this account. */
  dim?: boolean;
}) {
  const { n, accountId, typeKey } = m;
  const user = n.user || n.fromUser || {};
  const avatar = proxyImage(user.avatar ?? null, accountId);
  const text = renderText(n.text || n.description || "", n.replacePairs);
  const amount = amountFrom(text);
  const kind = kindFrom(typeKey, text);
  const name = user.name || user.username || "?";
  const href = notificationHref(accountId, user, { refresh: true });
  const body = (
    <>
      <div className="w-7 h-7 rounded-full bg-bg-elev-1 overflow-hidden shrink-0 grid place-items-center relative">
        {avatar ? (
          <img src={avatar} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
        ) : (
          <span className="text-[10px] text-fg-dim">{name.slice(0, 1).toUpperCase()}</span>
        )}
        <span className="absolute -bottom-1 -right-1 text-[10px]" aria-hidden>
          {typeKey === "tip" ? "💸" : "💰"}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 leading-snug">
          <span className="text-[12px] font-medium text-fg truncate flex-1">{name}</span>
          {amount && (
            <span className="text-[12px] font-semibold text-ok shrink-0">{amount}</span>
          )}
        </div>
        <div className="text-[10px] text-fg-dim mt-0.5 flex items-center gap-1.5">
          <span>{kind}</span>
          <span>·</span>
          <span>{fmtTime(n.createdAt)}</span>
          {accountLabel && (
            <>
              <span>·</span>
              <span className="px-1 rounded bg-bg-elev-1 border border-border">{accountLabel}</span>
            </>
          )}
        </div>
        {reply && <ReplyLine reply={reply} />}
      </div>
    </>
  );
  const cls = cn(
    "px-3 py-2 border-b border-border/60 last:border-b-0 flex items-start gap-2.5 hover:bg-bg-elev-1/40",
    dim && "opacity-60",
  );
  if (href) {
    return (
      <a
        href={href}
        className={cls}
        title={text}
        onClick={(e) => onNotificationClick(e, href)}
      >
        {body}
      </a>
    );
  }
  return <div className={cls} title={text}>{body}</div>;
}

/** Last message in the thread + where it stands.
 *
 *  The orange dot means "this thread still wants a HUMAN" — it shows when the
 *  fan spoke last, and stays lit when the only thing that answered them was an
 *  automation. It clears the moment a chatter actually replies. Blue keeps its
 *  inbox meaning: unread from the fan, or (as ✓✓) our message opened by them.
 *    blue badge  — the fan spoke last and we haven't read it.
 *    orange dot  — nobody human has answered them.
 *    ✓✓ blue     — a chatter spoke last and the fan has opened it.
 *    ✓ grey      — a chatter spoke last, delivered, not opened yet. */
function ReplyLine({ reply }: { reply: ReplyState }) {
  const { text, outbound, seen, unread, byBot } = reply;
  const tick = (
    <span
      className={cn("shrink-0", seen ? "text-info" : "text-fg-dim")}
      title={seen ? "Seen by the fan" : "Delivered — not opened yet"}
    >
      {seen ? "✓✓" : "✓"}
    </span>
  );
  return (
    <div className="text-[10px] mt-0.5 flex items-center gap-1.5">
      <span className="truncate flex-1 text-fg-dim italic" title={text}>
        {outbound ? (byBot ? "ai: " : "you: ") : ""}
        {text || "—"}
      </span>
      {outbound ? (
        <span className="flex items-center gap-1 shrink-0">
          {tick}
          {byBot && (
            <span
              className="w-2 h-2 rounded-full bg-warn"
              title="Only the AI has answered — no human reply yet"
            />
          )}
        </span>
      ) : unread ? (
        <span
          className="shrink-0 px-1 h-[14px] rounded-full bg-info text-white text-[9px] font-semibold grid place-items-center"
          title="They messaged you — unread"
        >
          new
        </span>
      ) : (
        <span
          className="shrink-0 w-2 h-2 rounded-full bg-warn"
          title="Read · awaiting your reply"
        />
      )}
    </div>
  );
}
