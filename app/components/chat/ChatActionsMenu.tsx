"use client";


import { useCallback, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useCan } from "@/hooks/useCan";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { relay, type OFChatItem } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { ofUserFullKey, useOFUser, type OFUser } from "@/hooks/useOFUser";
import { ChatHeaderExtras } from "./ChatHeaderExtras";
import { MENU_BOX, MENU_ITEM, MenuStatusLine, NotWiredMenuRow, useMenuStatus } from "./MenuParts";
import { MessageStatsRows } from "./MessageStatsLink";
import { useMenuDismiss } from "./useMenuDismiss";
import { ifConfirm } from "@/components/ui/ifConfirm";

interface Props {
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
  onClosed: () => void;
  muted: boolean;
  mutePending: boolean;
  onToggleMute: () => Promise<void>;
}

export function ChatActionsMenu({
  accountId, fanId, chat, onClosed, muted, mutePending, onToggleMute,
}: Props) {
  const qc = useQueryClient();
  const canDelete = useActionAllowed("delete-chat");
  const canBlock = useActionAllowed("block-fan");
  const platformRestrict = useCan(accountId, "restrict");
  const platformBlock = useCan(accountId, "block");
  const { status, flash } = useMenuStatus();
  const ref = useRef<HTMLDivElement | null>(null);
  const [extrasOpen, setExtrasOpen] = useState(false);
  const extrasId = useId();

  useMenuDismiss(ref, true, onClosed, useCallback(() => {
    if (extrasOpen) setExtrasOpen(false);
    else onClosed();
  }, [extrasOpen, onClosed]));

  // Not durable: the thread re-surfaces on the fan's next inbound, so a dead thread clears without risking a missed real message.
  const hideChat = useMutation({
    mutationFn: () =>
      relay.post(`/api/of/v2/chats/${fanId}/hide`, undefined, { accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      qc.invalidateQueries({ queryKey: ["roster-counts"] });
      flash(true, "Chat hidden — returns on their next message");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  // Not reversible: clears the chat's messages on the Creator's side, so it asks first.
  const deleteChat = useMutation({
    mutationFn: () => relay.delete(`/api/of/v2/chats/${fanId}`, { accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chats"] });
      qc.invalidateQueries({ queryKey: ["roster-counts"] });
      qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] });
      flash(true, "Conversation deleted");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  const restrictQ = useQuery({
    queryKey: ["automation-restrict", accountId, fanId],
    queryFn: () =>
      relay.get<{ restricted: boolean; reason: string | null }>(
        `/api/of/v2/automation-restrict/${fanId}`, { accountId }),
    staleTime: 30_000,
  });
  const restrictReason = restrictQ.data?.reason ?? null;
  // 'of_restricted': restricted ON OnlyFans, stronger than the automation skip_list (OF stops delivering, automations hard-skip, unread excludes).
  const ofRestrictSkip = restrictReason === "of_restricted";

  // Posts ?ack=false so the fan is sent nothing and the chat isn't marked read (a message to a fan can't be unsent); relay hides the chat LAST (restrict, then hide).
  const ofUser = useOFUser(accountId, fanId);
  const isRestricted =
    !!ofUser.data?.isRestricted || !!chat.withUser?.isRestricted || ofRestrictSkip;

  const toggleOfRestrict = useMutation({
    mutationFn: async () => {
      if (isRestricted) {
        await relay.delete(`/api/of/v2/users/${fanId}/restrict`, { accountId });
        return null;
      }
      return relay.post<{ hidden?: boolean }>(
        `/api/of/v2/users/${fanId}/restrict?ack=false`, undefined, { accountId });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
      qc.invalidateQueries({ queryKey: ["chats"] });
      qc.invalidateQueries({ queryKey: ["roster-counts"] });
      qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] });
      qc.invalidateQueries({ queryKey: ["automation-restrict"] });
      qc.invalidateQueries({ queryKey: ["of-restricted-list", accountId] });
      if (isRestricted) {
        flash(true, "OnlyFans restrict lifted");
      } else {
        const parts = ["restricted on OnlyFans"];
        if (data?.hidden) parts.push("chat hidden");
        flash(true, parts.join(" · "));
      }
    },
    onError: (e: Error) => flash(false, e.message),
  });

  // State is OF's isBlocked: the full user's when present, else the chat row's withUser.isBlocked.
  const blocked = typeof ofUser.data?.isBlocked === "boolean"
    ? ofUser.data.isBlocked
    : !!chat.withUser?.isBlocked;
  const toggleBlock = useMutation({
    mutationFn: () =>
      blocked
        ? relay.delete(`/api/of/v2/users/${fanId}/block`, { accountId })
        : relay.post(`/api/of/v2/users/${fanId}/block`, undefined, { accountId }),
    onSuccess: () => {
      const key = ofUserFullKey(accountId, fanId);
      qc.setQueryData<OFUser>(key, (old) => (old ? { ...old, isBlocked: !blocked } : old));
      qc.invalidateQueries({ queryKey: key, exact: true });
      flash(true, blocked ? "Unblocked on OnlyFans" : "Blocked on OnlyFans");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  async function copy(text: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      flash(true, `${what[0].toUpperCase()}${what.slice(1)} copied`);
    } catch {
      flash(false, `Could not copy the ${what}`);
    }
  }
  const username = chat.withUser?.username || ofUser.data?.username || "";

  return (
    <div
      ref={ref}
      className={cn(MP.ours.ChatActionsMenu.place, "absolute top-full")}
    >
      <div role="menu" aria-label="More actions" className={cn(MENU_BOX, MP.ours.ChatActionsMenu.box)}>
        {/* Not gated on OF's canRestrict: thin creator rows often omit it. */}
        {canBlock && platformRestrict && (
          <Item
            label={isRestricted ? "Lift restrict" : "Restrict"}
            disabled={toggleOfRestrict.isPending}
            onClick={async () => {
              const ask = isRestricted
                ? "Lift the OnlyFans restrict on this Fan?"
                : "Restrict this Fan on OnlyFans? The chat is hidden, and the Fan is sent nothing.";
              if (await ifConfirm(ask, { danger: !isRestricted })) toggleOfRestrict.mutate();
            }}
            icon={isRestricted ? "🔓" : "🛑"}
          />
        )}
        {canBlock && platformBlock && (
          <Item
            label={blocked ? "Unblock" : "Block"}
            disabled={toggleBlock.isPending}
            onClick={async () => {
              const ask = blocked ? "Unblock this Fan on OnlyFans?" : "Block this Fan on OnlyFans?";
              if (await ifConfirm(ask, { danger: !blocked })) toggleBlock.mutate();
            }}
            icon={blocked ? "✅" : "🚫"}
          />
        )}
        {/* Not wired: the relay has no report route. */}
        <NotWiredMenuRow why="report">
          <span className={cn(MP.ours.ChatActionsMenu.rowIcon, "text-center")}>🚩</span>
          <span>Report</span>
        </NotWiredMenuRow>
        <Item
          label="Hide chats"
          disabled={hideChat.isPending}
          onClick={() => hideChat.mutate()}
          icon="🙈"
        />
        {canDelete && (
          <Item
            label="Delete conversation"
            disabled={deleteChat.isPending}
            onClick={async () => {
              if (await ifConfirm("Delete conversation? This clears the messages on OnlyFans and cannot be undone.", { danger: true })) {
                deleteChat.mutate();
              }
            }}
            icon="🗑"
          />
        )}
        <Item
          label={muted ? "Unmute notifications" : "Mute notifications"}
          disabled={mutePending}
          onClick={() => {
            const wasMuted = muted;
            onToggleMute().then(
              () => flash(true, wasMuted ? "Notifications unmuted" : "Notifications muted"),
              (e: Error) => flash(false, e.message),
            );
          }}
          icon={muted ? "🔔" : "🔕"}
        />
        <div role="separator" className={cn(MP.menu.divider, "bg-border")} />
        <Item
          label="Copy chat link"
          onClick={() => void copy(
            `${location.origin}/messages-pro/${encodeURIComponent(accountId)}/${encodeURIComponent(String(fanId))}`,
            "chat link",
          )}
          icon="🔗"
        />
        <Item
          label="Copy profile link"
          disabled={!username}
          onClick={() => void copy(`https://onlyfans.com/${username}`, "profile link")}
          icon="👤"
        />
        <Item
          label="Copy username"
          disabled={!username}
          onClick={() => void copy(username, "username")}
          icon="@"
        />
        <div role="separator" className={cn(MP.menu.divider, "bg-border")} />
        <MessageStatsRows />
        <div role="separator" className={cn(MP.menu.divider, "bg-border")} />
        <button
          type="button"
          onClick={() => setExtrasOpen((v) => !v)}
          aria-expanded={extrasOpen}
          aria-controls={extrasOpen ? extrasId : undefined}
          title={EXTRAS_OVERFLOW_LABEL}
          aria-label={EXTRAS_OVERFLOW_LABEL}
          className={MENU_ITEM}
        >
          {EXTRAS_OVERFLOW_LABEL} ▸
        </button>
        <MenuStatusLine status={status} />
      </div>
      {extrasOpen && (
        <ChatHeaderExtras
          id={extrasId}
          accountId={accountId}
          fanId={fanId}
        />
      )}
    </div>
  );
}

function Item({
  label, onClick, disabled, icon,
}: { label: string; onClick: () => void; disabled?: boolean; icon?: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(MENU_ITEM, "disabled:opacity-50")}
    >
      <span className={cn(MP.ours.ChatActionsMenu.rowIcon, "text-center")}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}
