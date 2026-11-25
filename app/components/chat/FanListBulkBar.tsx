"use client";


import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { useAllChatFolders } from "@/hooks/useChatFolders";
import { isUnreadChat } from "@/lib/chatUnread";
import { relay, type OFChatItem } from "@/lib/relay";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { MENU, MENU_ITEM, MENU_ROW, MenuStatusLine, useMenuStatus } from "./MenuParts";
import { useFanListMenu } from "./useFanListMenu";
import { ifConfirm } from "@/components/ui/ifConfirm";

const O = MP.ours.FanListBulkBar;
const BUTTON = cn(O.button, "border-border text-fg hover:bg-bg-elev-1 disabled:opacity-50");

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

export function FanListBulkBar({
  picked, shownCount, listsAccountId, onSelectAll, onPickOnly, onDone, markChatsRead,
}: {
  picked: OFChatItem[];
  shownCount: number;
  listsAccountId: string | null;
  onSelectAll: () => void;
  onPickOnly: (rows: OFChatItem[]) => void;
  onDone: () => void;
  /** FanList's per-chat mark-read loop: marks the
   *  unread rows, clears their badges, returns the rows that failed. */
  markChatsRead: (rows: OFChatItem[]) => Promise<OFChatItem[]>;
}) {
  const qc = useQueryClient();
  const { status, flash } = useMenuStatus();
  const [busy, setBusy] = useState(false);
  const canDelete = useActionAllowed("delete-chat");
  const count = picked.length;

  async function eachPick(call: (c: OFChatItem, accountId: string) => Promise<unknown>, of: OFChatItem[]) {
    const failed: OFChatItem[] = [];
    for (const c of of) {
      try {
        // a row with no Creator stamp is never sent
        if (!c.__accountId) throw new Error("row has no Creator");
        await call(c, c.__accountId);
      } catch (err) {
        failed.push(c);
        console.warn("[bulk] failed for", c.withUser.id, err);
      }
    }
    return failed;
  }

  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try { await work(); } finally { setBusy(false); }
  }

  const markRead = () => run(async () => {
    const targets = picked.filter(isUnreadChat);
    if (targets.length === 0) { flash(true, "Already read"); return; }
    const failed = await markChatsRead(targets);
    if (failed.length > 0) onPickOnly(failed);
    flash(failed.length === 0, failed.length === 0
      ? `Marked ${plural(targets.length, "chat")} as read`
      : `Marked ${targets.length - failed.length} of ${targets.length}; ${failed.length} failed, still selected`);
  });

  const addToList = (listId: string, name: string) => run(async () => {
    if (!listsAccountId) return;
    try {
      await relay.post("/api/of/v2/lists/users", { [listId]: picked.map((c) => c.withUser.id) }, { accountId: listsAccountId });
      qc.invalidateQueries({ queryKey: ["chat-folders", listsAccountId] });
      qc.invalidateQueries({ queryKey: ["fan-lists", listsAccountId] });
      qc.invalidateQueries({ queryKey: ["chats"] });
      flash(true, `Added ${plural(count, "Fan")} to "${name}"`);
    } catch (e) {
      flash(false, (e as Error).message || "Couldn't add to that list");
    }
  });

  const remove = () => run(async () => {
    if (!(await ifConfirm(
      `Delete ${plural(count, "selected conversation")}? This clears the messages on OnlyFans and cannot be undone.`,
      { danger: true },
    ))) return;
    const failed = await eachPick(async (c, accountId) => {
      await relay.delete(`/api/of/v2/chats/${c.withUser.id}`, { accountId });
      qc.invalidateQueries({ queryKey: ["messages", accountId, c.withUser.id] });
    }, picked);
    qc.invalidateQueries({ queryKey: ["chats"] });
    qc.invalidateQueries({ queryKey: ["roster-counts"] });
    onPickOnly(failed);
    flash(failed.length === 0, failed.length === 0
      ? `Deleted ${plural(count, "conversation")}`
      : `Deleted ${count - failed.length} of ${count}; ${failed.length} failed, still selected`);
  });

  return (
    <div role="toolbar" aria-label="Selected chats" className={cn(O.bar, "flex flex-wrap items-center border-border")}>
      <span className="mr-auto text-fg-dim">{count} selected</span>
      {count < shownCount
        ? <button type="button" className={BUTTON} onClick={onSelectAll}>Select all</button>
        : <button type="button" className={BUTTON} onClick={() => onPickOnly([])}>Clear selection</button>}
      <button type="button" className={BUTTON} disabled={busy || count === 0} onClick={() => void markRead()}>
        Mark as read
      </button>
      {listsAccountId && (
        <AddToLists accountId={listsAccountId} disabled={busy || count === 0} onPick={(id, name) => void addToList(id, name)} />
      )}
      {canDelete && (
        <button
          type="button"
          className={cn(BUTTON, "text-err")}
          disabled={busy || count === 0}
          onClick={() => void remove()}
        >
          Delete
        </button>
      )}
      <button type="button" className={BUTTON} onClick={onDone}>Done</button>
      {status && <div className="basis-full"><MenuStatusLine status={status} /></div>}
    </div>
  );
}

function AddToLists({ accountId, disabled, onPick }: {
  accountId: string;
  disabled: boolean;
  onPick: (listId: string, name: string) => void;
}) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const foldersQ = useAllChatFolders(accountId);
  const lists = (foldersQ.data ?? []).filter((f) => f.canAddUsers);
  return (
    <div ref={ref} className="relative">
      <button type="button" {...triggerProps} disabled={disabled} className={BUTTON}>Add to lists ▸</button>
      {open && (
        <section {...menuProps} aria-label="Add to lists" className={cn(MENU, O.menuPlace)}>
          {foldersQ.isLoading && <div className={cn(MENU_ROW, "text-fg-dim")}>Loading lists…</div>}
          {foldersQ.isError && <div className={cn(MENU_ROW, "text-err")}>Failed to load lists</div>}
          {foldersQ.isSuccess && lists.length === 0 && (
            <div className={cn(MENU_ROW, "text-fg-dim")}>No custom lists on this account yet.</div>
          )}
          {lists.map((f) => {
            const id = String(f.id);
            const name = f.name || `List #${id}`;
            return (
              <button key={id} type="button" className={MENU_ITEM} onClick={() => { setOpen(false); onPick(id, name); }}>
                {name}
              </button>
            );
          })}
        </section>
      )}
    </div>
  );
}
