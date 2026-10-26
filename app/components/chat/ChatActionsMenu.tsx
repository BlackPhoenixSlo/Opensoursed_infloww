"use client";

/**
 * ChatActionsMenu — overflow popover in the chat header.
 *
 * Hosts the /ui/ parity actions OF web has on every chat:
 *   • Mute / Unmute   → POST/DELETE /chats/{id}/mute, through the Chat
 *                       header's one mute state (`muted`, `onToggleMute`),
 *                       which its mute icon shares
 *   • Hide / Unhide   → POST/DELETE /chats/{id}/hide
 *
 * Closes on outside-click + Esc. Each action shows a transient status
 * line at the bottom (✓ done · err msg).
 *
 * Ticket 92: Mark as unread and the mass-exclude toggle (MASSdmEXCLUDE; the
 * MASSppvEXCLUDE one merged into it 2026-10-21) moved to the Chat header's
 * Extras overflow (`ChatHeaderExtras`).
 *
 * Ticket 93's "Restrict from automations" row went with the Legacy flag.
 *
 * Ticket 94: Restrict and Block are the first two rows and both ask
 * `window.confirm` first (declining makes no call). Restrict posts with
 * `?ack=false`, so the Fan is sent nothing. Block / Unblock →
 * POST/DELETE /users/{id}/block. A role denied "Block or restrict fans"
 * gets neither row.
 *
 * Ticket 95: "Add to list ▸" moved to the Avatar menu (`FanAvatarMenu`).
 *
 * Ticket 96: Restrict's rows are named "Restrict" / "Lift restrict" (spec
 * stories 18, 19). The rows read Restrict, Block, Report (Not wired: the relay has
 * no report route), Hide chats, Mute notifications, then a divider and "Copy
 * chat link", which writes this Fan's Deep link to the clipboard. The menu
 * takes the shared Chat header menu Geometry (`MENU`, `MENU_ITEM`) and
 * its place (`MP.ours.ChatActionsMenu`); phone rows keep their touch padding.
 *
 * W4 4.4: "Delete conversation" follows "Hide chats", asks `window.confirm`
 * first (declining makes no call), then DELETE /chats/{id}. A role denied
 * "Delete chats" does not get the row.
 *
 * Roadmap 4.12 (04-messages-pro.md M8): "Copy profile link" and "Copy
 * username" follow "Copy chat link". Report stays Not wired (M7: OF's report
 * form sends captcha data the relay cannot fill).
 *
 * Ticket 140 (docs/spec/messages-pro-look-and-feel/phase-03-chat-header.md,
 * Kebab menu order): after the copy rows, a divider and 📈's two rows
 * (`MessageStatsRows`); last, a divider and "Inflowwww extras ▸", which opens the Chat header Extras
 * overflow (`ChatHeaderExtras`) as a submenu beside this menu (after the
 * Avatar menu's "Add to lists ▸"). This menu owns both layers' open state and
 * their one dismissal (`useMenuDismiss`), whose element holds both boxes
 * (each a `MENU_BOX`), so
 * a pointer-down in the submenu is inside: one Escape closes one layer (the
 * submenu first), and an outside pointer-down closes both.
 */

import { useCallback, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { relay, type OFChatItem } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { ofUserFullKey, useOFUser } from "@/hooks/useOFUser";
import { ChatHeaderExtras } from "./ChatHeaderExtras";
import { MENU_BOX, MENU_ITEM, MenuStatusLine, NotWiredMenuRow, useMenuStatus } from "./MenuParts";
import { MessageStatsRows } from "./MessageStatsLink";
import { useMenuDismiss } from "./useMenuDismiss";

interface Props {
  accountId: string;
  fanId: FanId;
  chat: OFChatItem;
  onClosed: () => void;
  /** The Chat header's mute state, whether its call is in flight, and its
   *  toggle (rejects with the relay's error). */
  muted: boolean;
  mutePending: boolean;
  onToggleMute: () => Promise<void>;
}

export function ChatActionsMenu({
  accountId, fanId, chat, onClosed, muted, mutePending, onToggleMute,
}: Props) {
  const qc = useQueryClient();
  const canDelete = useActionAllowed("delete-chat");
  // Restrict and Block are both the "block-fan" Function permission.
  const canBlock = useActionAllowed("block-fan");
  const { status, flash } = useMenuStatus();
  // Holds the Kebab menu and its submenu, so a pointer-down in either is inside.
  const ref = useRef<HTMLDivElement | null>(null);
  const [extrasOpen, setExtrasOpen] = useState(false);
  const extrasId = useId();

  useMenuDismiss(ref, true, onClosed, useCallback(() => {
    if (extrasOpen) setExtrasOpen(false);
    else onClosed();
  }, [extrasOpen, onClosed]));

  // "Hide chat" — OF's native hide (POST /chats/{id}/hide). Deliberately NOT
  // durable: the thread re-surfaces on the fan's next inbound message. That
  // shelf life is the point — it clears a dead thread (typically a just-
  // restricted non-friend creator) out of the inbox WITHOUT risking a missed
  // real message. No unhide row needed: a hidden chat has no row to open this
  // menu from, and it un-hides itself on the next inbound (restrict-lift also
  // un-hides server-side).
  const hideChat = useMutation({
    mutationFn: () =>
      relay.post(`/api/of/v2/chats/${fanId}/hide`, undefined, { accountId }),
    onSuccess: () => {
      // The row is gone from OF's /chats feed (relay busts its cache) — refetch
      // the inbox + badges so it vanishes now rather than on the next poll.
      qc.invalidateQueries({ queryKey: ["chats"] });
      qc.invalidateQueries({ queryKey: ["roster-counts"] });
      flash(true, "Chat hidden — returns on their next message");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  // "Delete conversation" — OF's chat-list "x" (DELETE /chats/{id}): clears the
  // chat's messages on the Creator's side, not reversible, so it asks first.
  // The relay busts its chat-list cache; refetch the inbox, badges and thread.
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

  // The fan's automation skip_list row in OUR DB (not OF), read for its reason.
  const restrictQ = useQuery({
    queryKey: ["automation-restrict", accountId, fanId],
    queryFn: () =>
      relay.get<{ restricted: boolean; reason: string | null }>(
        `/api/of/v2/automation-restrict/${fanId}`, { accountId }),
    staleTime: 30_000,
  });
  const restrictReason = restrictQ.data?.reason ?? null;
  // 'of_restricted' = this user is restricted ON ONLYFANS via our UI — a
  // strictly stronger block (OF stops delivering their messages, automations
  // hard-skip, unread counts exclude). It counts as restricted below; lift it
  // via the OF-restrict row.
  const ofRestrictSkip = restrictReason === "of_restricted";

  // ── Native OnlyFans restrict — DISTINCT from the automation skip_list
  // above (which only stops OUR automations); this is OF's own shadow-restrict: the fan can still type, but OF stops
  // delivering their messages to us (isRestricted→true, canReceiveChatMessage
  // →false). The row posts `?ack=false`, so the relay does NOT send the fan
  // its "." or mark the chat read (a message to a fan cannot be unsent). The
  // relay still (1) restricts on OF, (2) writes the durable
  // `of_restricted` registry that keeps the creator OUT of the roster/inbox
  // unread counts and hard-skipped by every automation, and (3) hides the
  // chat on OF LAST (restrict → hide), so the dead thread leaves the
  // inbox entirely until the fan messages again. Live state comes off
  // the OF user object OR the relay's row stamp (covers the thin /chats rows).
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
      // Refetch the OF user so the label flips to its true post-toggle state;
      // refresh the inbox + badges + this thread too — the relay just changed
      // the count-exclusion registry and hid (or un-hid) the chat.
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

  // Block / Unblock on OnlyFans. Our OF user types carry no blocked field, so
  // the row's state is a session flag in the query cache (it survives the
  // menu closing; the cache is cleared on sign-out).
  const blockedKey = ["of-blocked", accountId, fanId];
  const blocked = useQuery({
    queryKey: blockedKey, queryFn: () => false, initialData: false, enabled: false, gcTime: Infinity,
  }).data;
  const toggleBlock = useMutation({
    mutationFn: () =>
      blocked
        ? relay.delete(`/api/of/v2/users/${fanId}/block`, { accountId })
        : relay.post(`/api/of/v2/users/${fanId}/block`, undefined, { accountId }),
    onSuccess: () => {
      qc.setQueryData(blockedKey, !blocked);
      qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
      flash(true, blocked ? "Unblocked on OnlyFans" : "Blocked on OnlyFans");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  // The copy rows. "Copy chat link" copies this Fan's Deep link (spec,
  // Contracts), the path a Messages Pro Deep link page reads.
  // Any failure (no clipboard outside a secure context, or a refused write)
  // shows one fixed message.
  async function copy(text: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("no clipboard");
      await navigator.clipboard.writeText(text);
      flash(true, `${what[0].toUpperCase()}${what.slice(1)} copied`);
    } catch {
      flash(false, `Could not copy the ${what}`);
    }
  }
  // "Copy profile link" / "Copy username" (04-messages-pro.md M8): the Fan's
  // OF profile, `https://onlyfans.com/<username>` as OF's own "Copy link to
  // profile" has it, and the bare username. Disabled until a username is known.
  const username = chat.withUser?.username || ofUser.data?.username || "";

  return (
    <div
      ref={ref}
      className={cn(MP.ours.ChatActionsMenu.place, "absolute top-full")}
    >
      <div role="menu" aria-label="More actions" className={cn(MENU_BOX, MP.ours.ChatActionsMenu.box)}>
        {/* Always offered (was gated on OF's canRestrict, which the thin
            creator rows often omit — the one chat type this action is FOR).
            OF itself rejects the rare user it truly can't restrict. */}
        {canBlock && (
          <>
            <Item
              label={isRestricted ? "Lift restrict" : "Restrict"}
              disabled={toggleOfRestrict.isPending}
              onClick={() => {
                const ask = isRestricted
                  ? "Lift the OnlyFans restrict on this Fan?"
                  : "Restrict this Fan on OnlyFans? The chat is hidden, and the Fan is sent nothing.";
                if (window.confirm(ask)) toggleOfRestrict.mutate();
              }}
              icon={isRestricted ? "🔓" : "🛑"}
            />
            <Item
              label={blocked ? "Unblock" : "Block"}
              disabled={toggleBlock.isPending}
              onClick={() => {
                const ask = blocked ? "Unblock this Fan on OnlyFans?" : "Block this Fan on OnlyFans?";
                if (window.confirm(ask)) toggleBlock.mutate();
              }}
              icon={blocked ? "✅" : "🚫"}
            />
          </>
        )}
        {/* Not wired: the relay has no report route. */}
        <NotWiredMenuRow why="report">
          <span className={cn(MP.ours.ChatActionsMenu.rowIcon, "text-center")}>🚩</span>
          <span>Report</span>
        </NotWiredMenuRow>
        {/* Until the Fan writes again; no confirm, and the Thread stays open. */}
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
            onClick={() => {
              if (window.confirm("Delete conversation? This clears the messages on OnlyFans and cannot be undone.")) {
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
