"use client";


import {
  ArrowLeft, BadgeCheck, Bell, BellOff, EllipsisVertical, FileText, Image as ImageIcon, Info, Pencil, Pin, RotateCw, Search, Star,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { useAccountLabel } from "@/hooks/useAccounts";
import { useCan } from "@/hooks/useCan";
import { useCachedOFUser } from "@/hooks/useOFUser";
import { relay, type OFChatItem, type OFUserMini } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { useFanTyping } from "@/lib/fanTyping";
import { fmtAgo } from "@/lib/format";
import { MP } from "@/lib/messagesPro";

import { ChatActionsMenu } from "./ChatActionsMenu";
import { FanAvatarMenu } from "./AvatarMenu";
import { ChatGallery } from "./ChatGallery";
import { patchCachedChat } from "./useMarkChatRead";
import { ICON_BUTTON } from "./MenuParts";
import { OpenInNewTabButton } from "./FanTabs";
import { isFanOnline, newestSeen, type Seen } from "./isFanOnline";
import { NotWiredButton, type NotWiredKey } from "./NotWired";
import { useMenuDismiss } from "./useMenuDismiss";

const RIGHT_ICON_COLOUR = "text-fg-dim hover:text-fg hover:bg-bg-elev-1";

const LABEL_BUTTON = cn(MP.chatHeader.label, MP.chatHeader.lineTarget, "flex items-center whitespace-nowrap");

const LINE_ICON = cn(MP.chatHeader.lineTarget, "grid place-items-center");

function Divider() {
  return <span aria-hidden className={cn(MP.chatHeader.divider, "flex-none bg-border")} />;
}

export interface ChatHeaderProps {
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
  name: string;
  username?: string | null;
  onBack?: () => void;
  findOpen: boolean;
  onToggleFind: () => void;
  refreshing: boolean;
  onRefresh: () => void;
  onOpenNotes: () => void;
  onEditName: () => void;
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
  const avatarRef = useRef<HTMLDivElement | null>(null);
  const avatarMenuId = useId();
  useMenuDismiss(avatarRef, avatarOpen, useCallback(() => setAvatarOpen(false), []));
  const [galleryOpen, setGalleryOpen] = useState(false);
  const canGallery = useCan(accountId, "chat_media");
  const canFind = useCan(accountId, "chat_search");
  // The Fan's OF user from the cache only, as the Thread reads it: no request
  // of the header's own. It gives the presence line and the verified badge
  // (OF's `isVerified`, on the cached user or the chat row, as the Clone reads
  // it, messages.js:1458-1462).
  const profile = useCachedOFUser<Seen & Pick<OFUserMini, "isVerified">>(accountId, fanId);
  const presence = presenceOf(chat, profile);
  const typing = useFanTyping(accountId, fanId);
  const verified = !!(chat.withUser.isVerified || profile?.isVerified);
  const editNameSlot = cn(MP.chatHeader.editName, verified ? MP.chatHeader.editNameAfterBadge : MP.chatHeader.editNameSlot, "flex-none");
  const mute = useChatMute(accountId, fanId, chat);
  const muteLabel = mute.muted ? "Unmute notifications" : "Mute notifications";

  return (
    <header className="bg-[var(--inf-pane,var(--color-panel))]">
      <div className={cn(MP.chatHeader.bar, "relative grid content-center items-center border-[var(--inf-rule,var(--color-border))]")}>
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
                <span className="min-w-0 truncate">{typing ? "is typing…" : presence.text}</span>
              </span>
            </button>
            {avatarOpen && <FanAvatarMenu id={avatarMenuId} accountId={accountId} fanId={fanId} />}
          </div>
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
          {canGallery && (
            <>
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
            </>
          )}
          {canFind && (
            <>
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
            </>
          )}
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
        {galleryOpen && canGallery && (
          <ChatGallery accountId={accountId} fanId={fanId} onClose={() => setGalleryOpen(false)} />
        )}
      </div>
    </header>
  );
}

function presenceOf(chat: OFChatItem, profile: Seen | undefined) {
  if (isFanOnline(chat, profile)) return { online: true, text: "Available now" };
  const ago = fmtAgo(newestSeen(chat, profile));
  return { online: false, text: ago ? `Last seen ${ago}` : "Offline" };
}

export const CHAT_MUTE = "chat-mute";

function useChatMute(accountId: string, fanId: FanId, chat: OFChatItem) {
  const qc = useQueryClient();
  const [muted, setMuted] = useState(!!chat.isMutedNotifications);
  useEffect(() => { setMuted(!!chat.isMutedNotifications); }, [chat.isMutedNotifications]);
  const call = useMutation({
    mutationKey: [CHAT_MUTE, accountId, String(fanId)],
    mutationFn: (next: boolean) =>
      next
        ? relay.post(`/api/of/v2/chats/${fanId}/mute`, undefined, { accountId })
        : relay.delete(`/api/of/v2/chats/${fanId}/mute`, { accountId }),
    onSuccess: (_data, next) => {
      setMuted(next);
      patchCachedChat(qc, accountId, fanId, { isMutedNotifications: next });
    },
  });
  const toggle = async () => { await call.mutateAsync(!muted); };
  return { muted, pending: call.isPending, toggle };
}

// No relay route sets Priority or pins a chat.
function NotWiredIcon({ label, icon: Icon, why }: { label: string; icon: LucideIcon; why: NotWiredKey }) {
  return (
    <NotWiredButton why={why} label={label} className={cn(LINE_ICON, "text-fg-dim")}>
      <Icon aria-hidden className={MP.chatHeader.lineIcon} />
    </NotWiredButton>
  );
}
