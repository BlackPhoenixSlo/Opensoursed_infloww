"use client";


import { memo } from "react";
import { BadgeCheck, Ban, BellOff, Check, Hand, X } from "lucide-react";
import type { OFChatItem, OFUserMini } from "@/lib/relay";
import type { FanSpend } from "@/hooks/useFanSpend";
import { cn, decodeHtmlEntities, fmtRelTime, interpretSubStatus } from "@/lib/utils";
import { clockTime, fmtSpend } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import type { FanId } from "@/lib/fanId";
import { isUnreadChat } from "@/lib/chatUnread";
import { MP } from "@/lib/messagesPro";
import { fanDeepLinkHref } from "@/lib/nav";
import { useChatDraftText } from "@/lib/chatDrafts";
import { useFanTyping } from "@/lib/fanTyping";
import type { FanListSelection } from "./FanList";
import { ROW_BADGE_LABEL, type RowBadge, rowBadges } from "./fanRowBadges";
import { fanRowPreview } from "./fanRowPreview";
import { OpenInNewWindowMenu } from "./OpenInNewWindowMenu";
import { NOT_WIRED, NotWiredNote, notWiredTitle, useNotWiredNote } from "./NotWired";

const G = MP.fanList;
const O = MP.ours.FanRow;

// Profile cache first: a chats refetch can drop back to slim withUser and revert the name.
export function fanNameOf(c: OFChatItem, profile: OFUserMini | undefined): string {
  return decodeHtmlEntities(
    profile?.displayName ||
    c.withUser.displayName ||
    profile?.customNickname ||
    c.withUser.customNickname ||
    profile?.name ||
    c.withUser.name ||
    profile?.username ||
    c.withUser.username ||
    `fan ${c.withUser.id}`,
  );
}

export const FanRow = memo(function FanRow({
  chat: c, accountId, profile, totalSpendCents, subscriptionStatus, expiredAt, lastPurchase, lastPpvPurchase,
  subscribedAt,
  selected: isSelected, oweDot, account, now,
  onSelect, schedulePrefetch, cancelPrefetch, prefetchNow, selectedRowRef, picked, onTogglePick, stale,
}: {
  chat: OFChatItem;
  accountId: string;
  profile: OFUserMini | undefined;
  totalSpendCents: number | null;
  subscriptionStatus: FanSpend["subscription_status"];
  expiredAt: FanSpend["expired_at"];
  lastPurchase: string | null;
  lastPpvPurchase: string | null;
  subscribedAt?: string | null;
  selected: boolean;
  oweDot: boolean;
  account: { color: string; name: string } | null;
  now: number;
  onSelect: (sel: FanListSelection) => void;
  schedulePrefetch: (accountId: string, fanId: FanId) => void;
  cancelPrefetch: () => void;
  prefetchNow: (accountId: string, fanId: FanId) => void;
  selectedRowRef: (el: HTMLButtonElement | null) => void;
  picked?: boolean;
  onTogglePick?: (chat: OFChatItem) => void;
  stale?: boolean;
}) {
  const fanName = fanNameOf(c, profile);
  const avatarUrl = proxyImage(c.withUser.avatar || profile?.avatar || null, accountId);
  const handle = profile?.username || c.withUser.username;
  const unread = isUnreadChat(c);
  const badges = rowBadges(
    {
      subscribedAt, lastPpvPurchase, lastMessageAt: c.lastMessage?.createdAt, subscriptionStatus, expiredAt,
      autoRenewOff: c.withUser.autoRenewOff,
    },
    now,
  );
  const expired = badges.includes("❌");
  const pill = totalSpendCents === null ? null : fmtSpend(totalSpendCents);
  const verified = !!(c.withUser.isVerified || profile?.isVerified);
  const draft = useChatDraftText(accountId, c.withUser.id);
  const typing = useFanTyping(accountId, c.withUser.id);
  const preview = fanRowPreview(c, { typing, draft, selected: isSelected });
  return (
    <OpenInNewWindowMenu href={fanDeepLinkHref(accountId, c.withUser.id)}>
      <button
        type="button"
        data-chat-row
        data-stale={stale || undefined}
        aria-current={isSelected ? "true" : undefined}
        aria-pressed={onTogglePick ? !!picked : undefined}
        ref={isSelected ? selectedRowRef : undefined}
        title={rowTooltip(totalSpendCents, lastPurchase, subscriptionStatus, expiredAt, now)}
        onClick={() => {
          if (onTogglePick) {
            onTogglePick(c);
            return;
          }
          // No optimistic mark-as-read here: ChatSurface owns the 1.2s grace window; firing on click cleared the blue dot instantly.
          onSelect({ accountId, fanId: c.withUser.id, chat: c });
        }}
        onMouseEnter={() => schedulePrefetch(accountId, c.withUser.id)}
        onMouseLeave={cancelPrefetch}
        onFocus={() => schedulePrefetch(accountId, c.withUser.id)}
        onBlur={cancelPrefetch}
        // Touch fires no mouseenter/focus before the tap, so hover prefetch never runs on phone; the tap is the intent.
        onPointerDown={() => prefetchNow(accountId, c.withUser.id)}
        className={cn(
          G.row,
          "group relative flex w-full text-left items-start hover:bg-bg-elev-1 transition-colors",
          stale && "opacity-50 grayscale",
          // 96px is G.row's fixed height, so the scrollbar never jumps as off-screen rows skip layout.
          "[content-visibility:auto] [contain-intrinsic-size:auto_96px]",
          "after:bg-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))]",
          isSelected && "bg-[var(--inf-row-selected,var(--color-bg-elev-1))]",
        )}
      >
        <EdgeMarker unread={unread} muted={!!c.isMutedNotifications} unreadCount={c.unreadMessagesCount ?? 0} oweDot={oweDot} />
        {account && (
          <span
            className={cn(G.accountDot, "absolute hidden lg:block border-black/20")}
            style={{ background: account.color }}
            title={account.name}
          />
        )}
        <div className="relative shrink-0">
          {expired ? (
            <div
              role="img"
              aria-label={ROW_BADGE_LABEL["❌"]}
              title={ROW_BADGE_LABEL["❌"]}
              className={cn(G.avatar, "grid place-items-center overflow-hidden bg-err text-white")}
            >
              <X aria-hidden className={G.avatarIcon} />
            </div>
          ) : (
            <div className={cn(G.avatar, "grid place-items-center overflow-hidden bg-[var(--inf-list-avatar,var(--color-bg-elev-2))]")}>
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  fetchPriority="low"
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-fg">{fanName.trim().slice(0, 2).toUpperCase()}</span>
              )}
            </div>
          )}
          {onTogglePick && (
            <span
              aria-hidden
              className={cn(
                O.pickMark, "absolute grid place-items-center",
                picked ? "bg-accent border-accent text-white" : "bg-[var(--inf-pane,var(--color-panel))] border-border",
              )}
            >
              {picked && <Check className="size-3" />}
            </span>
          )}
          {c.isOnline && (
            <span
              role="img"
              aria-label="Online"
              title="Online"
              className={cn(G.onlineDot, "absolute bg-[var(--inf-online,var(--color-ok))] group-hover:border-bg-elev-1", isSelected ? "border-[var(--inf-row-selected,var(--color-bg-elev-1))]" : "border-[var(--inf-pane,var(--color-panel))]")}
            />
          )}
          {pill && (
            <span
              className={cn(
                G.spend, "absolute whitespace-nowrap",
                "text-warn bg-[var(--inf-chip,var(--color-bg-elev-1))]",
              )}
            >
              {pill}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className={cn(G.top, "flex items-center")}>
            <span className={cn(G.name, "shrink-0 truncate")}>{fanName}</span>
            {verified && (
              <BadgeCheck role="img" aria-label="Verified" className={cn(G.verified, "shrink-0 text-info")}>
                <title>Verified</title>
              </BadgeCheck>
            )}
            <span className={cn(G.handle, "min-w-0 truncate text-fg-dim")}>{handle ? `@${handle}` : ""}</span>
            {badges.map((b) => (b === "❌" ? null : <RowBadgeMark key={b} badge={b} />))}
            {c.withUser.isRestricted && (
              <Ban role="img" aria-label="User is restricted" className={cn(G.verified, "shrink-0 text-err")}>
                <title>User is restricted</title>
              </Ban>
            )}
            {c.withUser.needsHuman && (
              <Hand role="img" aria-label="Needs human" className={cn(G.verified, "shrink-0 text-warn")}>
                <title>Needs human: a custom is owed</title>
              </Hand>
            )}
            {account && (
              <span
                className={cn(O.accountChip, "lg:hidden ml-auto shrink-0 text-white truncate")}
                style={{ background: account.color }}
              >
                {account.name}
              </span>
            )}
            <RowCloseNotWired className={account ? "lg:ml-auto" : "ml-auto"} />
          </div>
          <div className={cn(G.bottom, "flex items-center")}>
            <span
              title={preview.title}
              className={cn(G.preview, "flex-1 min-w-0 truncate", unread ? cn(G.previewUnread, "text-fg") : "text-fg-dim")}
            >
              {preview.typing ? <span className="italic">{preview.text}</span> : preview.text}
            </span>
            <span className={cn(G.time, "shrink-0 whitespace-nowrap text-fg-dim")}>
              {fmtTime(c.lastMessage?.createdAt, now)}
            </span>
            {c.isMutedNotifications && (
              <BellOff
                role="img"
                aria-label="Muted notifications"
                className={cn(G.muteIcon, "shrink-0 text-fg-dim")}
              >
                <title>Muted notifications</title>
              </BellOff>
            )}
          </div>
        </div>
      </button>
    </OpenInNewWindowMenu>
  );
});

// oweDot is string-normalized upstream: fromUser.id is a string snowflake on Fansly, so a Number compare marked every row owed.
function EdgeMarker({ unread, muted, unreadCount, oweDot }: {
  unread: boolean; muted: boolean; unreadCount: number; oweDot: boolean;
}) {
  if (unread) {
    if (muted) return null;
    const label = `Unread${unreadCount ? ` (${unreadCount})` : ""}`;
    return <span role="img" aria-label={label} title={label} className={cn(G.edgeMarker, G.unreadDot, "absolute bg-info")} />;
  }
  if (oweDot) {
    return (
      <span
        role="img"
        aria-label="Read · awaiting your reply"
        title="Read · awaiting your reply"
        className={cn(G.edgeMarker, G.oweDot, "absolute bg-warn ring-warn/20")}
      />
    );
  }
  return null;
}

function RowBadgeMark({ badge }: { badge: Exclude<RowBadge, "❌"> }) {
  switch (badge) {
    case "New":
      return (
        <span title={ROW_BADGE_LABEL.New} className={cn(G.newBadge, "shrink-0 bg-info text-white")}>
          New
        </span>
      );
    case "🔥":
      return <GlyphBadge glyph="🔥" />;
    case "❄️":
      return <GlyphBadge glyph="❄️" />;
    case "Off":
      return (
        <span title={ROW_BADGE_LABEL.Off} className={cn(G.offLabel, "shrink-0 text-[var(--inf-accent-text,var(--color-accent))]")}>
          Off
        </span>
      );
  }
}

function GlyphBadge({ glyph }: { glyph: Extract<RowBadge, "🔥" | "❄️"> }) {
  const label = ROW_BADGE_LABEL[glyph];
  return (
    <span role="img" aria-label={label} title={label} className={cn(O.glyphBadge, "shrink-0")}>
      {glyph}
    </span>
  );
}

function rowTooltip(
  totalSpendCents: number | null,
  lastPurchase: string | null,
  subscriptionStatus: FanSpend["subscription_status"],
  expiredAt: FanSpend["expired_at"],
  now: number,
): string | undefined {
  const status = interpretSubStatus(subscriptionStatus, expiredAt, now);
  const parts: string[] = [];
  if (totalSpendCents !== null && totalSpendCents > 0) parts.push(fmtSpend(totalSpendCents));
  if (lastPurchase) parts.push(`last buy ${fmtRelTime(lastPurchase)}`);
  if (status.short !== "—") {
    parts.push(
      status.short === "Active" && expiredAt
        ? `renews ${fmtRelTime(expiredAt)}`
        : status.short === "Won't renew" && expiredAt
          ? `ends ${fmtRelTime(expiredAt)}`
          : status.short,
    );
  }
  return parts.length ? parts.join(" · ") : undefined;
}

function fmtTime(iso: string | undefined | null, nowMs: number): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date(nowMs);
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) {
    return clockTime(d);
  }
  const diffDays = (now.getTime() - d.getTime()) / 86_400_000;
  if (diffDays < 7) return WEEKDAY.format(d);
  return MONTH_DAY.format(d);
}
const WEEKDAY = new Intl.DateTimeFormat([], { weekday: "short" });
const MONTH_DAY = new Intl.DateTimeFormat([], { month: "short", day: "numeric" });

function RowCloseNotWired({ className }: { className: string }) {
  const note = useNotWiredNote();
  return (
    <span className={cn("relative shrink-0", className)}>
      <span
        role="img"
        aria-label="Not wired"
        title={notWiredTitle("rowClose")}
        onClick={note.onClick}
        onPointerDown={(e) => e.stopPropagation()}
        className={cn(G.notWired, "cursor-help text-fg-dim hover:text-fg")}
      >
        ×
      </span>
      <NotWiredNote open={note.open} className="right-full top-0 mr-1">{NOT_WIRED.rowClose}</NotWiredNote>
    </span>
  );
}
