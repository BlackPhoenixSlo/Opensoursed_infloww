"use client";

/**
 * ChatHeader — the Chat header Region of the Thread: phone back, avatar, the
 * Fan's name (tooltip "@username · Creator") over the presence line, then the
 * header tools and the Kebab menu.
 *
 * Moved out of ChatSurface unchanged (ticket 84, Phase 3 prefactor). The
 * search panel, quote state, send path, refresh handler and Fan insights open
 * state stay in the Thread; this module gets them through its props. It owns
 * the Kebab menu's open state.
 *
 * Ticket 85: the name is 16px / 700 on one line, the presence line reads
 * "Available now", "Last seen <time ago>" or "Offline" (spec, Implementation
 * Decisions, Presence), and the row takes the Clone's Geometry from md up
 * (`MP.chatHeader`).
 *
 * Ticket 86: the icon row follows the name: star "Priority" and pin "Pinned
 * chat" are Not wired (spec F3), mute is wired, and "Find" replaces
 * "🔍 search". The header owns the one mute state; the Kebab menu's mute row
 * reads it and calls the same toggle.
 *
 * Ticket 87: "Notes" sits between mute and pin and calls `onOpenNotes`, which
 * opens Fan insights and asks it to focus the Fan notes field (spec F23).
 *
 * Ticket 88: "Gallery" sits between pin and "Find" and opens the "Chat
 * gallery" sheet (`ChatGallery`), whose open state the header owns.
 *
 * Ticket 90: the right group ends the row: "Open in new tab" (Phase 1's
 * button), the refresh icon, the Fan insights toggle and the vertical kebab.
 * "↗ pop out" is gone; a Pop-out window for one Fan opens from the Fan List
 * row's "Open in a new window" (ADR-0002, amended).
 *
 * Ticket 91: 📈 "Message statistics" (`MessageStatsLink`) opens the right
 * group, with its own menu in the shared Chat header menu Geometry.
 *
 * Ticket 92: the "+" Extras overflow (`ChatHeaderExtras`) follows "Find" and
 * holds our extras: Scheduled, Group chat, Mark as unread and the MASS
 * toggles. The 🌐 translate toggle and its batch hints are gone: the
 * Composer toolbar's Translator drives the same translate mode (spec F12).
 *
 * Ticket 93: the automation surfaces show only with the Legacy flag on. The
 * Persona button sits after "Find", before "+". The Kebab menu's
 * automation-restrict row is gated the same way. (The AI strip band that sat
 * under the header row went with the legacy selling engine it explained.)
 *
 * Ticket 95: the avatar (with the name and presence line it sits beside)
 * opens the Avatar menu (`FanAvatarMenu`), which now holds "Add to lists ▸";
 * it no longer opens Fan insights, which its toggle opens at every width.
 *
 * Ticket 108: the header compacts to the Thread's width (spec D4, CH14). The
 * words of "Gallery" and "Find" (and "Open in new tab", in `FanTabs`) are
 * screen-reader text in a Thread narrower than 886px (`MP.chatHeader.labelText`),
 * and the name and presence line end in an ellipsis.
 *
 * Ticket 140 (docs/spec/messages-pro-look-and-feel/phase-03-chat-header.md):
 * no Inflowwww extra renders inline. 📈's rows and the "+" Extras overflow
 * (as the Kebab menu's "Inflowwww extras ▸" submenu, with the flag-on
 * Persona row) are reached through the Kebab menu (`ChatActionsMenu`).
 *
 * Ticket 141: the Region is Infloww's two lines, a grid (`MP.chatHeader.bar`).
 * Line 1 (`data-chat-header-line="1"`): the phone back control, the Fan's name
 * with the verified badge, and at its end the right group, centred on the
 * Region from md up. Line 2 (`data-chat-header-line="2"`): after the presence
 * line, star, bell, notes, pin, "Gallery" and "Find", a divider before each.
 * No avatar is drawn: the name, badge and presence line are the one "Avatar
 * menu" button, a subgrid over the name's column and the rest of line 1, so
 * line 2's icons start right after the presence text, whatever the name's
 * width. Nothing in either line depends on the Legacy flag.
 *
 * Ticket 142: the edit pencil, "Edit name", follows the name (or the badge)
 * on line 1 and calls `onEditName`, which opens Fan insights on Nickname. It
 * is its own button, outside the "Avatar menu" one: a row over the name's
 * cell whose invisible copy of the name (and badge) truncates as the name
 * does, so the pencil lands in the slot the name row keeps for it.
 */

import {
  ArrowLeft, BadgeCheck, Bell, BellOff, EllipsisVertical, FileText, Image as ImageIcon, Info, Pencil, Pin, RotateCw, Search, Star,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { useAccountLabel } from "@/hooks/useAccounts";
import { useCachedOFUser } from "@/hooks/useOFUser";
import { relay, type OFChatItem, type OFUserMini } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { useFanTyping } from "@/lib/fanTyping";
import { fmtAgo } from "@/lib/format";
import { MP } from "@/lib/messagesPro";

import { ChatActionsMenu } from "./ChatActionsMenu";
import { FanAvatarMenu } from "./AvatarMenu";
import { ChatGallery } from "./ChatGallery";
import { ICON_BUTTON } from "./MenuParts";
import { OpenInNewTabButton } from "./FanTabs";
import { isFanOnline, newestSeen, type Seen } from "./isFanOnline";
import { NotWiredButton, type NotWiredKey } from "./NotWired";
import { useMenuDismiss } from "./useMenuDismiss";

/** The right group's icon buttons' colours (refresh, Fan insights, the
 *  kebab). Colours stay out of the Geometry module (ADR-0001). */
const RIGHT_ICON_COLOUR = "text-fg-dim hover:text-fg hover:bg-bg-elev-1";

/** "Gallery" and "Find" (Compare CH3): the icon and word on one line, in a
 *  24px target (`lineTarget`). Each adds its colours. */
const LABEL_BUTTON = cn(MP.chatHeader.label, MP.chatHeader.lineTarget, "flex items-center whitespace-nowrap");

/** Line 2's icon buttons (star, bell, notes, pin): the icon's box padded out
 *  to a 24px target that keeps the drawn spacing (`lineTarget`). Each adds
 *  its colours. */
const LINE_ICON = cn(MP.chatHeader.lineTarget, "grid place-items-center");

/** The divider before each of line 2's items (Compare CH3), in Phase 1's
 *  divider colour. */
function Divider() {
  return <span aria-hidden className={cn(MP.chatHeader.divider, "flex-none bg-border")} />;
}

export interface ChatHeaderProps {
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
  /** The Fan's name and @username as the Thread resolves them (the
   *  Composer's placeholder reads the same name). */
  name: string;
  username?: string | null;
  /** Phone back (below lg). Absent in a Pop-out window and in /group. */
  onBack?: () => void;
  /** The Thread's search panel, opened and closed by "Find". */
  findOpen: boolean;
  onToggleFind: () => void;
  /** The Thread's ↻ refresh handler, and whether a refresh is in flight. */
  refreshing: boolean;
  onRefresh: () => void;
  /** "Notes": open Fan insights and focus its Fan notes field (spec F23). */
  onOpenNotes: () => void;
  /** "Edit name": open Fan insights and focus its Nickname field (ticket 142). */
  onEditName: () => void;
  /** Fan insights, at every width, through its toggle. */
  insightsOpen: boolean;
  onToggleInsights: () => void;
}

export function ChatHeader({
  accountId, fanId, chat, name, username, onBack,
  findOpen, onToggleFind, refreshing, onRefresh, onOpenNotes, onEditName,
  insightsOpen, onToggleInsights,
}: ChatHeaderProps) {
  const accountLabel = useAccountLabel(accountId);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [avatarOpen, setAvatarOpen] = useState(false);
  // Holds the avatar button and its menu (`display: contents`, so the row's
  // layout is untouched), so a press on the avatar toggles the menu.
  const avatarRef = useRef<HTMLDivElement | null>(null);
  const avatarMenuId = useId();
  useMenuDismiss(avatarRef, avatarOpen, useCallback(() => setAvatarOpen(false), []));
  const [galleryOpen, setGalleryOpen] = useState(false);
  // The Fan's OF user from the cache only, as the Thread reads it: no request
  // of the header's own. It gives the presence line and the verified badge
  // (OF's `isVerified`, on the cached user or the chat row, as the Clone reads
  // it, messages.js:1458-1462).
  const profile = useCachedOFUser<Seen & Pick<OFUserMini, "isVerified">>(accountId, fanId);
  const presence = presenceOf(chat, profile);
  const typing = useFanTyping(accountId, fanId);
  const verified = !!(chat.withUser.isVerified || profile?.isVerified);
  // The pencil's slot, kept in the name row and the overlay alike (ticket 142).
  const editNameSlot = cn(MP.chatHeader.editName, verified ? MP.chatHeader.editNameAfterBadge : MP.chatHeader.editNameSlot, "flex-none");
  const mute = useChatMute(accountId, fanId, chat);
  const muteLabel = mute.muted ? "Unmute notifications" : "Mute notifications";

  return (
    <header className="bg-[var(--inf-pane,var(--color-panel))]">
      <div className={cn(MP.chatHeader.bar, "relative grid content-center items-center border-[var(--inf-rule,var(--color-border))]")}>
        {/* Line 1, a box-less group whose children sit in the bar's grid: back,
            the name (in the Avatar menu button) and the right group. */}
        <div data-chat-header-line="1" className="contents">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className={cn(MP.chatHeader.backButton, "col-start-1 row-start-1 row-end-3 grid place-items-center text-fg-dim hover:text-fg hover:bg-bg-elev-1")}
              title="Back to chat list"
              aria-label="Back"
            >
              <ArrowLeft aria-hidden className={MP.chatHeader.back} />
            </button>
          )}
          <div ref={avatarRef} className="contents">
            {/* The name and badge over the presence line, one button over the
                name's column and the rest of line 1 (a subgrid, so the
                presence line alone sizes the name's column). Line 2's icons
                sit over its lower right cell. */}
            <button
              type="button"
              onClick={() => setAvatarOpen((v) => !v)}
              aria-expanded={avatarOpen}
              aria-controls={avatarOpen ? avatarMenuId : undefined}
              className="col-start-2 col-end-4 row-start-1 row-end-3 grid grid-cols-subgrid grid-rows-subgrid min-w-0 text-left"
              title="Avatar menu"
            >
              <span className={cn(MP.chatHeader.nameRow, "col-start-1 col-end-3 row-start-1 flex items-center min-w-0")}>
                <span className={cn(MP.chatHeader.name, "min-w-0 truncate")} title={`@${username || chat.withUser.id} · ${accountLabel}`}>
                  {name}
                </span>
                {verified && (
                  <BadgeCheck role="img" aria-label="Verified" className={cn(MP.chatHeader.verified, "flex-none text-fg-dim")}>
                    <title>Verified</title>
                  </BadgeCheck>
                )}
                <span aria-hidden className={editNameSlot} />
              </span>
              <span className={cn(MP.chatHeader.status, "col-start-1 row-start-2 flex items-center min-w-0 whitespace-nowrap text-[var(--inf-presence-text,var(--color-fg-dim))]")}>
                <span aria-hidden className={cn(MP.chatHeader.statusDot, "flex-none", presence.online ? "bg-[var(--inf-presence-online,var(--color-ok))]" : "bg-[var(--inf-offline,var(--color-fg-dim))]")} />
                {/* Infloww's "is typing..." (04 M3) stands in for the presence. */}
                <span className="min-w-0 truncate">{typing ? "is typing…" : presence.text}</span>
              </span>
            </button>
            {avatarOpen && <FanAvatarMenu id={avatarMenuId} accountId={accountId} fanId={fanId} />}
          </div>
          {/* "Edit name" (ticket 142), over the name row: an invisible copy of
              the name and badge, then the pencil in the name row's slot. Only
              the pencil takes the pointer. */}
          <div className={cn(MP.chatHeader.nameRow, "col-start-2 col-end-4 row-start-1 flex items-center min-w-0 pointer-events-none")}>
            <span aria-hidden data-name={name} className={cn(MP.chatHeader.name, "invisible min-w-0 truncate before:content-[attr(data-name)]")} />
            {verified && <span aria-hidden className={cn(MP.chatHeader.verified, "flex-none")} />}
            <span className={cn(editNameSlot, "relative")}>
              <button
                type="button"
                onClick={onEditName}
                className={cn(MP.chatHeader.editNameTarget, "absolute grid place-items-center pointer-events-auto text-fg-dim hover:text-fg")}
                title="Edit name"
                aria-label="Edit name"
              >
                <Pencil aria-hidden className={MP.chatHeader.editName} />
              </button>
            </span>
          </div>
          {/* The right group (spec H9 to H11, H15): "Open in new tab" and
              refresh (both from md up), the Fan insights toggle at every
              width, and the kebab last, outside line 2 (ticket 140). From md up it is
              centred on the Region; below md it ends line 1 and line 2 runs
              under it. */}
          <div className={cn(MP.chatHeader.right, "col-start-4 row-start-1 md:row-end-3 justify-self-end flex flex-none items-center")}>
            <OpenInNewTabButton accountId={accountId} fanId={fanId} name={name} />
            <button
              type="button"
              onClick={() => onRefresh()}
              className={cn(ICON_BUTTON, "hidden md:grid", RIGHT_ICON_COLOUR)}
              title="Refresh chat, fan info & re-cache"
              aria-label="Refresh"
            >
              <RotateCw aria-hidden className={cn(MP.chatHeader.iconButtonIcon, refreshing && "animate-spin")} />
            </button>
            {/* Fan insights toggle, at every width: below lg the panel is a
             *  slide-over, at lg+ the in-flow column. Phone keeps its 40px target. */}
            <button
              type="button"
              onClick={onToggleInsights}
              className={cn(MP.ours.ChatHeader.rightIcon, "grid place-items-center", RIGHT_ICON_COLOUR)}
              title="Fan insights"
              aria-label="Fan insights"
              aria-expanded={insightsOpen}
            >
              <Info aria-hidden className={MP.chatHeader.iconButtonIcon} />
            </button>
            <button
              type="button"
              onClick={() => setActionsOpen((v) => !v)}
              className={cn(MP.ours.ChatHeader.rightIcon, MP.chatHeader.kebab, "grid place-items-center", RIGHT_ICON_COLOUR)}
              title="More actions"
              aria-label="More actions"
            >
              <EllipsisVertical aria-hidden className={MP.chatHeader.kebabIcon} />
            </button>
          </div>
        </div>
        {/* Line 2 (spec H6, H7), after the presence line: star, mute, notes,
            pin, then "Gallery" and "Find", a divider before each; below md it
            runs under the right group too. */}
        <div
          data-chat-header-line="2"
          className={cn(
            MP.chatHeader.tools,
            "col-start-3 col-end-5 md:col-end-4 row-start-2 relative flex items-center whitespace-nowrap",
          )}
        >
          <Divider />
          <NotWiredIcon label="Priority" icon={Star} why="priority" />
          <Divider />
          <button
            type="button"
            onClick={() => { void mute.toggle().catch(() => {}); }}
            disabled={mute.pending}
            className={cn(
              LINE_ICON,
              "flex-none disabled:opacity-50",
              mute.muted ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg",
            )}
            title={muteLabel}
            aria-label={muteLabel}
          >
            {/* Infloww's plain bell; struck through while muted. */}
            {mute.muted
              ? <BellOff aria-hidden className={MP.chatHeader.lineIcon} />
              : <Bell aria-hidden className={MP.chatHeader.lineIcon} />}
          </button>
          <Divider />
          <button
            type="button"
            onClick={onOpenNotes}
            className={cn(LINE_ICON, "flex-none text-fg-dim hover:text-fg")}
            title="Notes"
            aria-label="Notes"
          >
            <FileText aria-hidden className={MP.chatHeader.lineIcon} />
          </button>
          <Divider />
          <NotWiredIcon label="Pinned chat" icon={Pin} why="pin" />
          <Divider />
          <button
            type="button"
            onClick={() => setGalleryOpen(true)}
            aria-haspopup="dialog"
            className={cn(LABEL_BUTTON, "flex-none text-fg-dim hover:text-fg")}
            title="Chat gallery"
          >
            <ImageIcon aria-hidden className={MP.chatHeader.labelIcon} />
            <span className={MP.chatHeader.labelText}>Gallery</span>
          </button>
          <Divider />
          <button
            type="button"
            onClick={onToggleFind}
            aria-expanded={findOpen}
            className={cn(
              LABEL_BUTTON,
              "flex-none",
              findOpen ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg",
            )}
            title="Search this conversation"
          >
            <Search aria-hidden className={MP.chatHeader.labelIcon} />
            <span className={MP.chatHeader.labelText}>Find</span>
          </button>
        </div>
        {actionsOpen && (
          <ChatActionsMenu
            accountId={accountId}
            fanId={fanId}
            chat={chat}
            onClosed={() => setActionsOpen(false)}
            muted={mute.muted}
            mutePending={mute.pending}
            onToggleMute={mute.toggle}
          />
        )}
        {galleryOpen && (
          <ChatGallery accountId={accountId} fanId={fanId} onClose={() => setGalleryOpen(false)} />
        )}
      </div>
    </header>
  );
}

/** The presence line's facts (spec, Implementation Decisions, Presence):
 *  online by ticket 73's rule (`isFanOnline`), else the newest known
 *  `lastSeen` in the app's time-ago wording, else "Offline". `profile` is the
 *  Fan's cached OF user. */
function presenceOf(chat: OFChatItem, profile: Seen | undefined) {
  if (isFanOnline(chat, profile)) return { online: true, text: "Available now" };
  const ago = fmtAgo(newestSeen(chat, profile));
  return { online: false, text: ago ? `Last seen ${ago}` : "Offline" };
}

/** The mute / unmute call's mutation key: `[CHAT_MUTE, accountId, fanId]`, so
 *  a view can follow a mute that succeeded (the react-query mutation cache). */
export const CHAT_MUTE = "chat-mute";

/** This chat's one mute state and call (spec, Implementation Decisions, Mute),
 *  shared by the mute icon and the Kebab menu's mute row. It starts from the
 *  conversation's `isMutedNotifications`, follows it when the row changes, and
 *  takes the requested state when the relay call succeeds. `toggle` rejects
 *  with the relay's error, which the Kebab menu shows on its status line. */
function useChatMute(accountId: string, fanId: FanId, chat: OFChatItem) {
  const [muted, setMuted] = useState(!!chat.isMutedNotifications);
  useEffect(() => { setMuted(!!chat.isMutedNotifications); }, [chat.isMutedNotifications]);
  const call = useMutation({
    mutationKey: [CHAT_MUTE, accountId, String(fanId)],
    mutationFn: (next: boolean) =>
      next
        ? relay.post(`/api/of/v2/chats/${fanId}/mute`, undefined, { accountId })
        : relay.delete(`/api/of/v2/chats/${fanId}/mute`, { accountId }),
    onSuccess: (_data, next) => setMuted(next),
  });
  const toggle = async () => { await call.mutateAsync(!muted); };
  return { muted, pending: call.isPending, toggle };
}

/** A Not wired icon (spec, Not wired rendering; `NotWired`): `aria-disabled`,
 *  no state, because no relay route sets Priority or pins a chat (spec F3); a
 *  click shows its excuse under it. */
function NotWiredIcon({ label, icon: Icon, why }: { label: string; icon: LucideIcon; why: NotWiredKey }) {
  return (
    <NotWiredButton why={why} label={label} className={cn(LINE_ICON, "text-fg-dim")}>
      <Icon aria-hidden className={MP.chatHeader.lineIcon} />
    </NotWiredButton>
  );
}
