"use client";


import { notificationHref, onNotificationClick } from "@/lib/notificationLink";
import { fmtPrice } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";
import type { NotifTypeKey } from "@/lib/notifSettings";
import { fmtTime, renderText } from "@/lib/notifText";
import type { MergedItem, ReplyState } from "./useMoneyRailFeed";

export function amountFrom(text: string): string | null {
  const m = text.match(/\$\s?([\d,]+(?:\.\d{1,2})?)/);
  if (!m) return null;
  const dollars = Number(m[1].replace(/,/g, ""));
  return Number.isFinite(dollars) ? fmtPrice(Math.round(dollars * 100)) : `$${m[1]}`;
}

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
  leaseRef,
}: {
  m: MergedItem;
  accountLabel: string | null;
  reply: ReplyState | null;
  dim?: boolean;
  leaseRef?: (el: Element | null) => void;
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
        ref={leaseRef}
        href={href}
        className={cls}
        title={text}
        onClick={(e) => onNotificationClick(e, href)}
      >
        {body}
      </a>
    );
  }
  return <div ref={leaseRef} className={cls} title={text}>{body}</div>;
}

// Orange dot = thread still wants a HUMAN: stays lit when only an automation answered.
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
