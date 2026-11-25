"use client";


import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { openGroupTab } from "@/lib/groupChannel";
import { useMassExclude } from "@/hooks/useMassExclude";
import { useCan } from "@/hooks/useCan";
import { relay } from "@/lib/relay";
import { flipCachedReadState } from "@/hooks/useAccountStateEvents";
import { relayNow } from "@/lib/ageClock";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";

import { CHAT_EXTRA_ROW, ExtraMenuRow } from "./ExtraMenuRow";
import { MENU_BOX, MenuStatusLine, useMenuStatus } from "./MenuParts";
import { GROUP_CHAT_DETAIL } from "./MessagesProExtras";
import { ScheduledForChat } from "./ScheduledForChat";


interface Props {
  id: string;
  accountId: string;
  fanId: FanId;
}

export function ChatHeaderExtras({ id, accountId, fanId }: Props) {
  const qc = useQueryClient();
  const { status, flash } = useMenuStatus();
  const canMarkUnread = useCan(accountId, "mark_unread");

  const markUnread = useMutation({
    mutationFn: () =>
      relay.delete(`/api/of/v2/chats/${fanId}/mark-as-read`, { accountId }),
    onSuccess: () => {
      flipCachedReadState(qc, accountId, { fanId, unread: true, at: relayNow() }, { own: true });
      flash(true, "Marked unread");
    },
    onError: (e: Error) => flash(false, e.message),
  });

  const dmExclude = useMassExclude(accountId, fanId);

  return (
    <div id={id} role="menu" aria-label="Inflowwww extras" className={cn(MENU_BOX, MP.ours.ChatHeaderExtras.box)}>
      <ScheduledForChat accountId={accountId} fanId={fanId} />
      <GroupChatRow accountId={accountId} fanId={fanId} />
      {canMarkUnread && (
        <ExtraMenuRow name="Mark as unread" className={CHAT_EXTRA_ROW} disabled={markUnread.isPending} onClick={() => markUnread.mutate()}>
          Mark as unread
        </ExtraMenuRow>
      )}
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

function GroupChatRow({ accountId, fanId }: { accountId: string; fanId: FanId }) {
  const [flash, setFlash] = useState<null | "added" | "opened" | "focused">(null);
  const onClick = async () => {
    const res = await openGroupTab(accountId, fanId);
    if (res.kind === "self") return;
    setFlash(
      res.kind === "opened" ? "opened"
        : res.kind === "focused" ? "focused"
        : "added",
    );
    if (
      (res.kind === "broadcast" || res.kind === "focused") &&
      typeof window !== "undefined" &&
      /^\/chat\//.test(window.location.pathname)
    ) {
      // 80ms lets the broadcast reach the group tab before this window dies
      window.setTimeout(() => { try { window.close(); } catch { } }, 80);
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
