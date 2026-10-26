"use client";

/**
 * FanRow — one row of the Fan List, rendered from raw facts its parent
 * computes (docs/spec/phase-02-fan-list-pane.md, Interfaces › FanRow).
 * FanList keeps data, selection, pagination and prefetch; the row only
 * draws them and reports hover, focus, press and click back. A right-click
 * offers the Fan's Deep link as a Pop-out window (`OpenInNewWindowMenu`).
 *
 * Built for a list of 500+ rows (All Models, five Creators): the row is
 * memoized, so FanList passes it stable callbacks and primitive or
 * reference-stable props, and a live message re-renders only its own row; and
 * an off-screen row skips layout and paint (`content-visibility: auto`, sized
 * by the row's fixed height) while staying in the DOM, so scroll-to-selected,
 * Tab focus, find-in-page and the bulk bar's picks see every row.
 */

import { memo } from "react";
import { BadgeCheck, Ban, BellOff, Check, Hand, X } from "lucide-react";
import type { OFChatItem, OFUserMini } from "@/lib/relay";
import type { FanSpend } from "@/hooks/useFanSpend";
import { cn, decodeHtmlEntities, fmtRelTime, interpretSubStatus } from "@/lib/utils";
import { clockTime, fmtSpend } from "@/lib/format";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId, sameUserId } from "@/lib/fanId";
import { isUnreadChat } from "@/lib/chatUnread";
import { MP } from "@/lib/messagesPro";
import { fanDeepLinkHref } from "@/lib/nav";
import { useChatDraftText } from "@/lib/chatDrafts";
import { useFanTyping } from "@/lib/fanTyping";
import type { FanListSelection } from "./FanList";
import { ROW_BADGE_LABEL, type RowBadge, rowBadges } from "./fanRowBadges";
import { OpenInNewWindowMenu } from "./OpenInNewWindowMenu";
import { NOT_WIRED, NotWiredNote, notWiredTitle, useNotWiredNote } from "./NotWired";

const G = MP.fanList;
const O = MP.ours.FanRow;

/** The Fan's name as the row shows it. Priority: team-set nickname (from our
 *  SQLite, stitched onto /users/list by the relay) → OF display name → OF
 *  username → numeric id. Reads from the per-fan profile cache first (the
 *  stable side channel that enrichWithUsers populates), falling back to
 *  whatever's on the chat row — so a chats refetch that drops back to slim
 *  withUser doesn't make the rail revert. */
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
  onSelect, schedulePrefetch, cancelPrefetch, prefetchNow, selectedRowRef, picked, onTogglePick,
}: {
  chat: OFChatItem;
  /** The Creator this chat belongs to. */
  accountId: string;
  /** The Fan's cached profile, which outlives a chats refetch's slim withUser. */
  profile: OFUserMini | undefined;
  /** Total spend in cents, or null while it is unknown: spend-batch is still
   *  loading or has no entry for the Fan (spec, Rows). 0 is a known zero. */
  totalSpendCents: number | null;
  subscriptionStatus: FanSpend["subscription_status"];
  expiredAt: FanSpend["expired_at"];
  /** ISO time of the Fan's last purchase, or null. */
  lastPurchase: string | null;
  /** ISO time of the Fan's last PPV purchase, or null, for 🔥. */
  lastPpvPurchase: string | null;
  /** ISO time the Fan subscribed, for the "New" badge. FanList fetches no
   *  such field and passes none, so New ships dark (spec, Rows, New). */
  subscribedAt?: string | null;
  selected: boolean;
  /** Show the yellow "awaiting your reply" dot (the unread dot still wins). */
  oweDot: boolean;
  /** All Models only: the Creator's colour and name. Null in one Creator's scope. */
  account: { color: string; name: string } | null;
  /** Epoch ms the row's time column is measured from. */
  now: number;
  onSelect: (sel: FanListSelection) => void;
  /** Hover or focus: warm this Fan's messages and vault after a dwell. */
  schedulePrefetch: (accountId: string, fanId: FanId) => void;
  cancelPrefetch: () => void;
  /** Pointer-down: warm this Fan's messages and vault at once. */
  prefetchNow: (accountId: string, fanId: FanId) => void;
  /** Attached to the selected row only; scrolls it into view once per selection. */
  selectedRowRef: (el: HTMLButtonElement | null) => void;
  /** Bulk select (`FanListBulkBar`): this row is picked. */
  picked?: boolean;
  /** Set only in select mode: a click toggles the pick (of this row's chat)
   *  instead of opening the chat. */
  onTogglePick?: (chat: OFChatItem) => void;
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
  // The pill under the avatar on every row whose spend is known, "$0" for a
  // known zero; unknown spend shows none (Phase 2, Spend under the avatar).
  const pill = totalSpendCents === null ? null : fmtSpend(totalSpendCents);
  // Only what the cached chat row or profile says; nothing is fetched for it.
  const verified = !!(c.withUser.isVerified || profile?.isVerified);
  const draft = useChatDraftText(accountId, c.withUser.id);
  const typing = useFanTyping(accountId, c.withUser.id);
  return (
    <OpenInNewWindowMenu href={fanDeepLinkHref(accountId, c.withUser.id)}>
      <button
        type="button"
        data-chat-row
        // Phase 2 rebuilds the Fan List and keeps this marker: the route
        // test and scripts/ui-shots.sh read the selection from it.
        aria-current={isSelected ? "true" : undefined}
        // Select mode: the row is a toggle, pressed while picked.
        aria-pressed={onTogglePick ? !!picked : undefined}
        ref={isSelected ? selectedRowRef : undefined}
        title={rowTooltip(totalSpendCents, lastPurchase, subscriptionStatus, expiredAt, now)}
        onClick={() => {
          if (onTogglePick) {
            onTogglePick(c);
            return;
          }
          // No optimistic mark-as-read patch here — ChatSurface owns
          // the timing (1.2s grace window). Firing it on click was
          // overriding that delay so the blue dot vanished instantly.
          onSelect({ accountId, fanId: c.withUser.id, chat: c });
        }}
        onMouseEnter={() => schedulePrefetch(accountId, c.withUser.id)}
        onMouseLeave={cancelPrefetch}
        onFocus={() => schedulePrefetch(accountId, c.withUser.id)}
        onBlur={cancelPrefetch}
        // Touch never fires mouseenter/focus before the tap, so the
        // hover-prefetch strategy is dead on phone. Fire the prefetchers
        // directly (skipping the 120ms dwell — the tap IS the intent).
        // prefetchQuery no-ops while the query is fresh, so a mouse user
        // who already warmed this row on hover issues nothing extra.
        onPointerDown={() => prefetchNow(accountId, c.withUser.id)}
        className={cn(
          G.row,
          "group relative flex w-full text-left items-start hover:bg-bg-elev-1 transition-colors",
          // Off screen: no layout or paint. 96px is G.row's fixed h-24, so
          // the scrollbar never jumps as rows come into view.
          "[content-visibility:auto] [contain-intrinsic-size:auto_96px]",
          "after:bg-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))]",
          isSelected && "bg-[var(--inf-row-selected,var(--color-bg-elev-1))]",
        )}
      >
        <EdgeMarker unread={unread} unreadCount={c.unreadMessagesCount ?? 0} oweDot={oweDot} />
        {/* All Models, from lg up: the Creator's colour dot, in the left
         *  padding above the Edge marker, so the avatar keeps its place. */}
        {account && (
          <span
            className={cn(G.accountDot, "absolute hidden lg:block border-black/20")}
            style={{ background: account.color }}
            title={account.name}
          />
        )}
        {/* The avatar with the online dot on its edge, and the Total spend
         *  pill under it (Compare FL1). */}
        <div className="relative shrink-0">
          {expired ? (
            // ❌ is the avatar treatment: a red circle with ✕ (spec, Rows;
            // `.av.coral` / `.xmark`, mh:164, mh:167).
            <div
              role="img"
              aria-label={ROW_BADGE_LABEL["❌"]}
              title={ROW_BADGE_LABEL["❌"]}
              className={cn(G.avatar, "grid place-items-center overflow-hidden bg-err text-white")}
            >
              <X aria-hidden className={G.avatarIcon} />
            </div>
          ) : (
            // Its own grey, never a row fill, so the circle still reads on the
            // selected and hovered row: the capture's grey circle behind the
            // person glyph (Compare FL1, ticket 151).
            <div className={cn(G.avatar, "grid place-items-center overflow-hidden bg-[var(--inf-list-avatar,var(--color-bg-elev-2))]")}>
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  // Browser hint: avatars are decorative, never above
                  // the fold of attention. Yields network/decode budget
                  // to message media + the active chat surface.
                  fetchPriority="low"
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-fg">{fanName.trim().slice(0, 2).toUpperCase()}</span>
              )}
            </div>
          )}
          {/* Select mode: a check on the avatar, filled while picked. */}
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
              // The ring takes the row's background, as `.dot` and
              // `.conv.selected .dot` do (mh:169-170); on hover, the row's hover fill.
              className={cn(G.onlineDot, "absolute bg-[var(--inf-online,var(--color-ok))] group-hover:border-bg-elev-1", isSelected ? "border-[var(--inf-row-selected,var(--color-bg-elev-1))]" : "border-[var(--inf-pane,var(--color-panel))]")}
            />
          )}
          {/* Centred under the avatar and out of flow, so a wide figure
           *  ("$12.5k") never pushes the text column. */}
          {pill && (
            <span
              className={cn(
                G.spend, "absolute whitespace-nowrap",
                // Orange at "$0" too, on the chip fill, as Infloww (2026-10-18 capture).
                "text-warn bg-[var(--inf-chip,var(--color-bg-elev-1))]",
              )}
            >
              {pill}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className={cn(G.top, "flex items-center")}>
            {/* The name keeps its width (up to its cap), so the @handle
             *  truncates first (Compare FL2). */}
            <span className={cn(G.name, "shrink-0 truncate")}>{fanName}</span>
            {verified && (
              <BadgeCheck role="img" aria-label="Verified" className={cn(G.verified, "shrink-0 text-info")}>
                <title>Verified</title>
              </BadgeCheck>
            )}
            <span className={cn(G.handle, "min-w-0 truncate text-fg-dim")}>{handle ? `@${handle}` : ""}</span>
            {/* The badge strip, after the name and @handle in `rowBadges`'s
             *  order (spec, Rows); ❌ is drawn in the avatar slot instead. */}
            {badges.map((b) => (b === "❌" ? null : <RowBadgeMark key={b} badge={b} />))}
            {/* Smart signals the relay stamps on the chat row (Infloww's
             *  "User is restricted" and "Needs human"); muted is the bell on
             *  line two. */}
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
            {/* Below lg the 8px colour dot is hidden, so this named chip
             *  is the only model identifier on the row. lg:hidden ⇒
             *  nothing renders at ≥1024px, where the dot is back. */}
            {account && (
              <span
                className={cn(O.accountChip, "lg:hidden ml-auto shrink-0 text-white truncate")}
                style={{ background: account.color }}
              >
                {account.name}
              </span>
            )}
            {/* Infloww's ✕ (Compare FL3): no source names its action, so a
             *  click or press neither selects the row nor warms the Fan; it
             *  only says so (`RowCloseNotWired`). Below lg it follows the
             *  Creator chip; from lg up it takes the free space itself. */}
            <RowCloseNotWired className={account ? "lg:ml-auto" : "ml-auto"} />
          </div>
          <div className={cn(G.bottom, "flex items-center")}>
            <span className={cn(G.preview, "flex-1 min-w-0 truncate", unread ? cn(G.previewUnread, "text-fg") : "text-fg-dim")}>
              {/* Infloww's preview states (MP2 message-HF80yTBL.js; 04 M3,
               *  M25): "is typing…" while the Fan types, else an unsent draft
               *  as "[Draft] …" in the preview's own emphasis (not on the open
               *  chat, whose composer shows it), else the last message. */}
              {typing
                ? <span className="italic">is typing…</span>
                : draft && !isSelected
                  ? `[Draft] ${draft}`
                  : previewText(c)}
            </span>
            <span className={cn(G.time, "shrink-0 whitespace-nowrap text-fg-dim")}>
              {fmtTime(c.lastMessage?.createdAt, now)}
            </span>
            {/* After the time only the muted bell, unread or not (Compare
             *  FL5-FL6); the unread and owe dots are the Edge marker. */}
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

/** The row's Edge marker in its left padding, centred on the avatar
 *  (Compare FL8):
 *    • Blue dot (count in its name and tooltip) → genuinely unread, OF said so
 *    • Yellow dot → read but the Fan sent the last message ("I owe a reply")
 *    • Nothing    → we sent last; ball's in their court
 *
 *  `oweDot` is FanList's `lastMessageFromFan`, which owns the compare so this
 *  dot and the Owe reply chip's filter can't drift. FanList passes it only
 *  while Owe reply is the active filter (spec, Rows;
 *  ADR-0003). It is string-normalized: `fromUser.id` is numeric on OF but a
 *  string snowflake on Fansly, and the old `!== Number(accountId)` was true
 *  for EVERY Fansly row — the dot stuck on threads we had already answered. */
function EdgeMarker({ unread, unreadCount, oweDot }: { unread: boolean; unreadCount: number; oweDot: boolean }) {
  if (unread) {
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

/** One badge of the strip on line one (spec, Rows; Gap row 22). */
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

/** 🔥 or ❄️: the 13px glyph, named for screen readers and in its tooltip. */
function GlyphBadge({ glyph }: { glyph: Extract<RowBadge, "🔥" | "❄️"> }) {
  const label = ROW_BADGE_LABEL[glyph];
  return (
    <span role="img" aria-label={label} title={label} className={cn(O.glyphBadge, "shrink-0")}>
      {glyph}
    </span>
  );
}

/** The row's tooltip: the old third line under the preview, the spend,
 *  "last buy …" and "renews/ends …" (spec, Rows; story 37). Undefined when
 *  there is none, so the row carries no empty `title`. */
function rowTooltip(
  totalSpendCents: number | null,
  lastPurchase: string | null,
  subscriptionStatus: FanSpend["subscription_status"],
  expiredAt: FanSpend["expired_at"],
  now: number,
): string | undefined {
  // No spend entry means no status and no expiry, which reads "—". The
  // row's one clock, so the tooltip and the badges agree on "expired".
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

/** Tag the preview with "you:" when the last message came from us — this
 *  is huge for triage: at a glance you see whether the fan replied or is
 *  still waiting on us. The model account's id is the row's __accountId
 *  (which == that account's own creator id). Same `sameUserId` compare the
 *  yellow dot uses: this line said "you: ghj" while the dot beside it said
 *  "awaiting your reply" on the very same Fansly row, because only one of
 *  the two normalized the id. */
function previewText(c: OFChatItem): string {
  const lm = c.lastMessage;
  if (!lm) return "";
  const fromMe = sameUserId(lm.fromUser?.id, c.__accountId);
  const prefix = fromMe ? "you: " : "";
  // Quick visual cues so triage doesn't need opening every row:
  //   💰  tip       — money came in
  //   🔒  PPV       — paid content sent/received
  //   📎 N media    — free media only
  const marker =
    lm.isTip ? "💰 " :
    (lm.isFree === false || lm.lockedText) ? "🔒 " :
    "";
  if (lm.text) return prefix + marker + stripHtml(lm.text);
  if (lm.mediaCount) return `${prefix}${marker || "📎 "}${lm.mediaCount} media`;
  return (prefix + marker).trim();
}

function stripHtml(s: string): string {
  return s.replace(/<[^>]+>/g, "").trim();
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
// Built once (`toLocaleDateString` with options builds a formatter per call); same output.
const WEEKDAY = new Intl.DateTimeFormat([], { weekday: "short" });
const MONTH_DAY = new Intl.DateTimeFormat([], { month: "short", day: "numeric" });

/** The row's ✕ (Compare FL3), a `span` because the row is a button. A click
 *  shows its excuse in a note to its left and never reaches the row. */
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
