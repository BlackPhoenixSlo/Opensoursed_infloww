"use client";

/**
 * ChatHeaderExtras — the Chat header's Extras overflow (ADR-0003;
 * docs/spec/phase-03-chat-header-message-list.md, H12, H13, F10, F11;
 * ticket 92). It holds the Inflowwww extras that used to crowd the header
 * row or the Kebab menu: the Scheduled row (`ScheduledForChat`), Group chat,
 * Mark as unread and the two MASS toggles. Each row
 * carries its extra's tooltip from the catalogue (`extraTitle`, the old
 * tooltip, if any, on the second line) and does what it did before, with the
 * same call and cache refresh.
 *
 * Ticket 140 (docs/spec/messages-pro-look-and-feel/phase-03-chat-header.md):
 * the "+" trigger is gone. The Kebab menu's last row, "Inflowwww extras ▸",
 * opens this menu as its submenu; the Kebab menu (`ChatActionsMenu`) owns its
 * open state and its dismissal (`useMenuDismiss`) and mounts it only while
 * it is open, so this module renders the menu's box only. It stays open after a row's action, so
 * the row's result shows on its status line, as the Kebab menu's does.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { openGroupTab } from "@/lib/groupChannel";
import { useMassExclude } from "@/hooks/useMassExclude";
import { relay, type OFChatItem } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";

import { CHAT_EXTRA_ROW, ExtraMenuRow } from "./ExtraMenuRow";
import { MENU_BOX, MenuStatusLine, useMenuStatus } from "./MenuParts";
import { GROUP_CHAT_DETAIL } from "./MessagesProExtras";
import { ScheduledForChat } from "./ScheduledForChat";


interface Props {
  /** The box's id, which the Kebab row names in `aria-controls`. */
  id: string;
  accountId: string;
  fanId: FanId;
}

export function ChatHeaderExtras({ id, accountId, fanId }: Props) {
  const qc = useQueryClient();
  const { status, flash } = useMenuStatus();

  // Moved from the Kebab menu unchanged: DELETE mark-as-read, then patch the
  // chats cache so the row's blue dot returns in the list immediately.
  const markUnread = useMutation({
    mutationFn: () =>
      relay.delete(`/api/of/v2/chats/${fanId}/mark-as-read`, { accountId }),
    onSuccess: () => {
      type Page = { rows: OFChatItem[]; hasMore: boolean };
      type Infinite = { pages: Page[]; pageParams: unknown[] };
      qc.getQueryCache().findAll({ queryKey: ["chats"] }).forEach((q) => {
        const data = q.state.data as Infinite | undefined;
        if (!data?.pages) return;
        const newPages: Page[] = data.pages.map((p) => ({
          ...p,
          rows: p.rows.map((c) =>
            (c.__accountId ?? "") === accountId && c.withUser.id === fanId
              ? { ...c, hasUnread: true, unreadMessagesCount: Math.max(1, c.unreadMessagesCount ?? 1) }
              : c,
          ),
        }));
        qc.setQueryData(q.queryKey, { ...data, pages: newPages });
      });
      flash(true, "Marked unread");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  // Mass-exclude toggle, moved from the Kebab menu: per-fan opt-out from every
  // mass send, priced or not (MASSdmEXCLUDE; MASSppvEXCLUDE merged into it).
  const dmExclude = useMassExclude(accountId, fanId);

  return (
    <div id={id} role="menu" aria-label="Inflowwww extras" className={cn(MENU_BOX, MP.ours.ChatHeaderExtras.box)}>
      <ScheduledForChat accountId={accountId} fanId={fanId} />
      <GroupChatRow accountId={accountId} fanId={fanId} />
      <ExtraMenuRow name="Mark as unread" className={CHAT_EXTRA_ROW} disabled={markUnread.isPending} onClick={() => markUnread.mutate()}>
        Mark as unread
      </ExtraMenuRow>
      <ExtraMenuRow
        name="Mass exclude"
        className={CHAT_EXTRA_ROW}
        disabled={dmExclude.toggle.isPending || dmExclude.isLoading}
        onClick={() =>
          dmExclude.toggle.mutate(!dmExclude.isOn, {
            onSuccess: (data, next) =>
              flash(true,
                (next ? "Added to MASSdmEXCLUDE" : "Mass sends allowed") +
                (data?.of_synced === false ? " (OF sync pending)" : "")),
            onError: (e: Error) => flash(false, e.message),
          })
        }
      >
        {dmExclude.isOn ? "Remove from MASSdmEXCLUDE" : "Add to MASSdmEXCLUDE"}
      </ExtraMenuRow>
      <MenuStatusLine status={status} />
    </div>
  );
}

/** Group chat, moved from the header's "👥 group" button. Routes via the
 *  BroadcastChannel coord layer so clicks NEVER navigate the source tab —
 *  including the case where the source IS a popout
 *  (`/messages-pro/<acct>/<fan>`). If a /group tab is alive AND has room, the
 *  click pushes a slot into it. If the current group tab is full (8 slots), a
 *  fresh group tab is spawned with this one fan as its first slot. */
function GroupChatRow({ accountId, fanId }: { accountId: string; fanId: FanId }) {
  const [flash, setFlash] = useState<null | "added" | "opened" | "focused">(null);
  const onClick = async () => {
    const res = await openGroupTab(accountId, fanId);
    // "self" means the caller is already inside /group. Don't flash —
    // there's no state change to announce, and "added" was misleading.
    if (res.kind === "self") return;
    setFlash(
      res.kind === "opened" ? "opened"
        : res.kind === "focused" ? "focused"
        : "added",
    );
    // Popout self-close: when this surface is the standalone /chat
    // popout AND the click resolved into the live group tab (no new tab
    // spawned), close the popout so the user lands on whatever tab takes
    // focus next — ideally the group tab via the broadcast-focus message we
    // just sent. The 80ms delay lets that broadcast reach the group tab
    // before this window dies.
    if (
      (res.kind === "broadcast" || res.kind === "focused") &&
      typeof window !== "undefined" &&
      /^\/chat\//.test(window.location.pathname)
    ) {
      window.setTimeout(() => { try { window.close(); } catch { /* policy denial */ } }, 80);
    }
    window.setTimeout(() => setFlash(null), 1400);
  };
  return (
    <ExtraMenuRow
      name="Group chat"
      detail={GROUP_CHAT_DETAIL}
      onClick={() => { void onClick(); }}
      className={cn(CHAT_EXTRA_ROW,
        flash === "added" ? "text-ok" : flash === "opened" ? "text-[var(--inf-accent-text,var(--color-accent))]" : flash === "focused" && "text-fg-dim")}
    >
      {flash === "added" ? "✓ added"
        : flash === "opened" ? "↗ opened"
        : flash === "focused" ? "↗ in group"
        : "Group chat"}
    </ExtraMenuRow>
  );
}
