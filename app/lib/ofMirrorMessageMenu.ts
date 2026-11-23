"use client";

/**
 * A chat message's ⋮ menu and the pinned page's ⋮ (Unpin all) on the OF mirror, as OF's own web app has them (the message
 * item's ItemActions, chunk 13560; the pinned header's PinnedAction, chunk 42549; ledger `.scratch/omf-messages-full/
 * ledger.md`). The menu is OF's dropdown (`v-menu__content m-dropdown-list`, the chat menu's own markup) under the ⋮;
 * its items, in OF's order and on OF's conditions:
 * - Copy message text (a text that is not locked): the clipboard, OF's toast.
 * - Like / Unlike (the fan's message, the fan neither restricted nor blocked): POST / DELETE /messages/{id}/like.
 * - Reply: the composer answers it (the line under the editor names it; Send carries OF's replyToMessageId).
 * - Bookmark / Unbookmark: POST / DELETE /messages/{id}/bookmark {chat_group_id: queueId} (OF's /posts/{id}/bookmarks).
 * - Add to collection (bookmarked): OF's bookmark collections are not in OF Manager: disabled.
 * - Pin / Unpin (canBePinned): POST / DELETE /messages/{id}/pin/user/{fan}; the header's pin and the pinned page follow.
 * - Hide (the fan's message): PUT /messages/{id}/hide {withUserId}; it leaves the thread.
 * - Report (the fan's message, canReport; ticket 42, D22): opens the chat's onlyfans.com page in a new tab
 *   (ofMirrorHandoffs reportHandoffUrl, measured), titled "opens onlyfans.com", nothing through the Relay: OF's report
 *   form sends captcha data and per-reason fields the mirror cannot fill (ledger). With no chat: disabled (NOT_YET).
 * - Forward and Add a tag (the Creator's message): New message has no forward body and the release-form picker is the
 *   composer's: disabled.
 * - Unsend (the Creator's message while OF's cancelSeconds last; the item counts them down): asks, then DELETE
 *   /messages/{id} {withUserId} (Messages Pro's useUnsendMessage: the bubble goes at once, back on an error).
 * Infloww's own bubble extras (ticket 33, not OF's): Countdown, Copy as draft and Unsend PPV (ofMirrorBubbleExtras), bound
 * only with OFM_NEW_WRITES_ENABLED on (ofMirrorNewWrites, UI-only: Unsend PPV is the menu's Unsend request); off, none
 * is bound or drawn (main).
 * OF has no Delete and no Edit for a sent message (ledger). The pinned page's ⋮: Unpin all messages (asks first;
 * DELETE /chats/{id}/messages/pin), off while there is no pin. Errors show in place; with no model nothing is sent.
 * The chat's State pages (menu, price, schedule, tag people, vault) draw the same thread: each ⋮ there is the same menu
 * (Wired; the State page's dialog or menu backdrop lies over the thread, so no mouse reaches it there, as on OF).
 */

import { useEffect, useRef, type RefObject } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type OFMessage } from "@/lib/relay";
import { mirrorQuery } from "@/lib/ofMirrorData";
import { chatPath, usersListPath } from "@/lib/ofMirrorDataQueries";
import { chatDraftKey, DRAFT_EVENT, loadChatDraft } from "@/lib/ofMirrorChat";
import { dialog, dialogError, FLAT, type FanState } from "@/lib/ofMirrorChatTools";
import { toast } from "@/lib/ofMirrorPost";
import { countdown, plainText, type ThreadMessage } from "@/lib/ofMirrorThread";
import { message, modalButton, note, NOT_YET, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { bindBubbleExtras, type UnsendAction } from "@/lib/ofMirrorBubbleExtras";
import { asHandoff, HANDOFF_TITLE, reportHandoffUrl } from "@/lib/ofMirrorHandoffs";
import { fanIdFromParam } from "@/lib/fanId";
import { useUnsendMessage } from "@/hooks/useUnsendMessage";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";
import { useChatPinned } from "@/hooks/useChatPinned";

export type MessageAction = "copy" | "like" | "reply" | "bookmark" | "collection" | "pin" | "hide" | "report" | "forward" | "tag" | "unsend";
export interface MessageItem {
  key: MessageAction;
  label: string;
  /** Not in OF Manager (NOT_YET as its tooltip). */
  off?: boolean;
  /** ticket 42: a hand-off, OF's page it opens in a new tab (ofMirrorHandoffs). */
  href?: string;
}

/** OF's message as the menu reads it. */
export type MenuMessage = ThreadMessage & {
  isAddedToBookmarks?: boolean;
  canReport?: boolean;
  isMediaReady?: boolean;
  queueId?: number | string | null;
  canBePinned?: boolean;
  /** The seconds OF still lets the Creator unsend it (as read). */
  cancelSeconds?: number | null;
};

/**
 * OF's ItemActions for message `m` (13560, in its order): `mine` the Creator's own, `limited` the fan restricted or
 * blocked, `left` the seconds the unsend window still has, `chat` the open chat's fan (Report's hand-off, ticket 42).
 */
export function messageItems(m: MenuMessage, o: { mine: boolean; limited: boolean; left: number; chat: string | null }): MessageItem[] {
  const items: MessageItem[] = [];
  if (plainText(m.text) && !m.lockedText) items.push({ key: "copy", label: "Copy message text" });
  if (!o.mine && !o.limited) items.push({ key: "like", label: m.isLiked ? "Unlike" : "Like" });
  items.push({ key: "reply", label: "Reply" });
  items.push({ key: "bookmark", label: m.isAddedToBookmarks ? "Unbookmark" : "Bookmark" });
  if (m.isAddedToBookmarks) items.push({ key: "collection", label: "Add to collection", off: true });
  if (m.canBePinned) items.push({ key: "pin", label: m.isPinned ? "Unpin" : "Pin" });
  if (!o.mine) items.push({ key: "hide", label: "Hide" });
  if (!o.mine && !!m.canReport) items.push(o.chat ? { key: "report", label: "Report", href: reportHandoffUrl("message", { fanId: o.chat }) } : { key: "report", label: "Report", off: true });
  if (o.mine && !m.isTip && m.isMediaReady !== false) items.push({ key: "forward", label: "Forward", off: true });
  if (o.mine && (m.media?.length ?? 0) > 0 && !m.giphyId) items.push({ key: "tag", label: "Add a tag", off: true });
  if (o.mine && o.left > 0) items.push({ key: "unsend", label: `Unsend ${countdown(o.left)}` });
  return items;
}

/** What the menu sends for the open chat (each refreshes what it changed). */
export interface MessageWrites {
  like(id: string, on: boolean): Promise<unknown>;
  pin(id: string, on: boolean): Promise<unknown>;
  bookmark(id: string, chatGroupId: number | null, on: boolean): Promise<unknown>;
  hide(id: string): Promise<unknown>;
  unsend(m: OFMessage): Promise<unknown>;
  unpinAll(): Promise<unknown>;
}

export interface MessageMenuContext {
  chat: string | null;
  /** The thread's messages (the chat page's, or the pinned page's pins), by id. */
  message(id: string): MenuMessage | undefined;
  /** The seconds message `id` may still be unsent (OF's cancelSeconds, less the time since it was read). */
  left(m: MenuMessage): number;
  /** The fan is restricted or blocked (no Like). */
  limited: boolean;
  /** The pinned page's count of pins (its Unpin all is off at 0). */
  pins?: number;
  /** null: All models with no model (nothing is sent). */
  writes: MessageWrites | null;
  storage: Storage | null;
  accountId: string | null;
  copy(text: string): Promise<void>;
  /** OFM_NEW_WRITES_ENABLED (useOfmNewWrites): on, the own bubbles' extras are bound (ofMirrorBubbleExtras); off, not
   *  at all (ticket 33; switch-off == main). */
  newWrites: boolean;
}

const MENU_BTN = "button[data-oi-msg-menu]";
const PINNED_BTN = "button[data-oi-pinned-menu]";
// A message's ⋮ as the State pages over the chat draw it: the generator tags (and enables) only the chat and pinned pages'.
const BUBBLE_BTN = ".b-chat__message button.m-size-sm.m-btn-vertical-dots";
const MENU_ID = "oi-msg-menu";
const CONFIRM_ID = "oi-msg-confirm";
export const COPIED_TEXT = "Copied to clipboard";

/** OF's dropdown (the chat menu's markup) with `items`, under `btn`, kept in the window. */
function dropdown(doc: Document, btn: HTMLElement, items: MessageItem[], alignRight: boolean): HTMLElement {
  doc.getElementById(MENU_ID)?.remove();
  const menu = doc.createElement("div");
  menu.id = MENU_ID;
  menu.setAttribute("role", "menu");
  menu.className = "v-menu__content theme--light menuable__content__active m-dropdown-list";
  menu.setAttribute("data-oi-wired", "");
  menu.style.cssText = "position:fixed;z-index:60;min-width:200px;max-width:256px;overflow:auto;background:var(--bg-color,#fff)";
  menu.dataset.oiAlign = alignRight ? "right" : "left";
  const list = doc.createElement("div");
  list.className = "v-list m-dropdown-v-list v-sheet theme--light shown";
  for (const it of items) {
    const el = it.href ? asHandoff(doc.createElement("a"), it.href) : doc.createElement("div");  // ticket 42: a hand-off is OF's link
    if (it.href) el.title = HANDOFF_TITLE;
    el.setAttribute("role", "menuitem");
    el.tabIndex = it.off ? -1 : 0;
    el.className = `v-list-item v-list-item--link theme--light m-with-rectangle-hover m-tb-sm${it.off ? " v-list-item--disabled" : ""}${it.key === "unsend" || it.key === "hide" || it.key === "report" ? " m-danger" : ""}`;
    el.dataset.oiMsgAction = it.key;
    if (it.off) {
      el.setAttribute("aria-disabled", "true");
      el.title = NOT_YET;
    }
    el.textContent = ` ${it.label} `;
    list.append(el);
  }
  menu.append(list);
  doc.body.append(menu);
  btn.setAttribute("aria-expanded", "true");
  place(menu, btn);
  return menu;
}

/** Put `menu` under its button (over it near the window's bottom), as OF's popper does; false once the button is out of view. */
function place(menu: HTMLElement, btn: HTMLElement): boolean {
  const win = btn.ownerDocument.defaultView;
  const r = btn.getBoundingClientRect();
  if (!btn.isConnected || (win && (r.bottom < 0 || r.top > win.innerHeight))) return false;
  const vw = win?.innerWidth ?? 0;
  const vh = win?.innerHeight ?? 0;
  // Never taller than the window (scrolls inside), never past its edges (8px), as at 390px.
  if (vh) menu.style.maxHeight = `${vh - 16}px`;
  const { height: h, width: w } = menu.getBoundingClientRect();
  const top = win && r.bottom + h > vh && r.top - h > 0 ? r.top - h : r.bottom;
  menu.style.top = `${Math.round(vh ? Math.max(8, Math.min(top, vh - h - 8)) : top)}px`;
  const room = Math.max(8, vw - w - 8);
  if (menu.dataset.oiAlign === "right") menu.style.right = `${Math.round(vw ? Math.max(8, Math.min(vw - r.right, room)) : 0)}px`;
  else menu.style.left = `${Math.round(vw ? Math.max(8, Math.min(r.left, room)) : r.left)}px`;
  return true;
}

/** Wire the thread's message menus (and the pinned page's ⋮) in `doc`. Returns an unbind. */
export function bindMessageMenu(doc: Document, ctx: MessageMenuContext): () => void {
  const { writes } = ctx;
  // The generator tags (and enables) only the chat and pinned pages' ⋮; a State page over the chat gets the same here,
  // its Not-yet title kept until its Live proof (decisions D1). The thread's draws clone this template, tag and all
  // (applyThread's menuTagged).
  for (const b of doc.querySelectorAll<HTMLButtonElement>(`${BUBBLE_BTN}:not([data-oi-msg-menu])`)) {
    b.setAttribute("data-oi-msg-menu", "");
    b.disabled = false;
  }
  for (const b of doc.querySelectorAll(`${MENU_BTN}, ${PINNED_BTN}`)) b.setAttribute("data-oi-wired", "");
  const pinnedBtn = doc.querySelector<HTMLButtonElement>(PINNED_BTN);
  if (pinnedBtn && ctx.pins !== undefined) pinnedBtn.disabled = ctx.pins === 0;
  let open: { btn: HTMLElement; id: string | null; timer?: number } | null = null;

  const close = () => {
    if (!open) return;
    doc.defaultView?.clearInterval(open.timer);
    open.btn.setAttribute("aria-expanded", "false");
    doc.getElementById(MENU_ID)?.remove();
    open = null;
  };
  const ready = (anchor: Element): MessageWrites | null => {
    if (!writes) return note(doc, anchor, SELECT_MODEL), null;
    return writes;
  };
  const confirm = (title: string, text: string, yes: string, go: (fail: (e: unknown) => void, done: () => void) => void, opener: Element): { close(): void } => {
    const m = dialog(doc, CONFIRM_ID, title, (body) => {
      const p = doc.createElement("p");
      p.textContent = text;
      body.append(p);
    }, [], opener);
    const btn: HTMLButtonElement = modalButton(doc, {
      text: yes,
      className: FLAT,
      onClick: () => {
        btn.disabled = true;
        go((e) => ((btn.disabled = false), dialogError(m.modal, `Could not ${yes.toLowerCase()}: ${message(e)}`)), () => m.close());
      },
    });
    m.modal.querySelector("footer")!.append(modalButton(doc, { text: "Cancel", className: FLAT, onClick: () => m.close() }), btn);
    return m;
  };

  const send = () => doc.querySelector("button[at-attr='send_btn']") ?? doc.body;
  const node = (id: string) => doc.querySelector(`[data-oi-msg="${CSS.escape(id)}"]`);
  // A failed write's red note, under its message's node once drawn: an unsend's undo draws the bubble again only on
  // the next redraw (useUnsendMessage restores the thread), so the note waits for it (draw) up to 2s, then the anchor.
  let pending: { id: string; text: string; anchor: Element; until: number } | null = null;
  const placePending = () => {
    if (!pending) return;
    const b = node(pending.id);
    if (!b && Date.now() < pending.until) return;
    const p = pending;
    pending = null;
    note(doc, b ?? (p.anchor.isConnected ? p.anchor : send()), p.text, true);
  };
  let pendingTimer: number | undefined;

  /** `live`: the opener still bound (Unsend PPV's extras); false by the time Unsend is clicked, nothing is sent. */
  const act = (key: MessageAction, m: MenuMessage, anchor: HTMLElement, live: () => boolean = () => true): { close(): void } | null | void => {
    const id = String(m.id);
    if (key === "copy") {
      return void ctx.copy(plainText(m.text)).then(
        () => toast(doc, COPIED_TEXT),
        () => note(doc, anchor, "Could not copy the text", true),
      );
    }
    if (key === "reply") {
      if (!ctx.storage || !ctx.accountId || !ctx.chat) return note(doc, anchor, SELECT_MODEL);
      const k = chatDraftKey(ctx.accountId, ctx.chat);
      ctx.storage.setItem(k, JSON.stringify({ ...loadChatDraft(ctx.storage, ctx.accountId, ctx.chat), reply_to: id, reply_text: plainText(m.text) || "Media" }));
      return void doc.dispatchEvent(new Event(DRAFT_EVENT));
    }
    const w = ready(anchor);
    if (!w) return null;
    // Under the message's node as drawn (the write's patch redrew the thread; useOfData keeps it there on the undo's).
    const failed = (what: string) => (e: unknown) => {
      pending = { id, text: `Could not ${what}: ${message(e)}`, anchor, until: Date.now() + 2000 };
      placePending();
      if (pending) pendingTimer = doc.defaultView?.setTimeout(placePending, 2050);
    };
    if (key === "like") return void w.like(id, !m.isLiked).catch(failed(m.isLiked ? "unlike" : "like"));
    if (key === "pin") return void w.pin(id, !m.isPinned).catch(failed(m.isPinned ? "unpin" : "pin"));
    if (key === "bookmark") {
      const group = m.queueId != null && /^\d+$/.test(String(m.queueId)) ? Number(m.queueId) : null;
      return void w.bookmark(id, group, !m.isAddedToBookmarks).catch(failed(m.isAddedToBookmarks ? "unbookmark" : "bookmark"));
    }
    if (key === "hide") return void w.hide(id).catch(failed("hide the message"));
    if (key === "unsend") {
      // The dialog closes either way (ticket 33): "Unsent" by Send, or the red note under the bubble that stays.
      return confirm("Unsend message", "Unsend this message? It is removed from the chat for both of you.", "Unsend", (_inDialog, done) => {
        if (!live()) return void done();   // its opener was unbound (the switch went off) while the dialog stood open
        // The window may have closed while the dialog stood open: no request then, the note says why.
        if (ctx.left(ctx.message(id) ?? m) <= 0) return void (done(), note(doc, anchor.isConnected ? anchor : send(), "The unsend window has closed", true));
        // useUnsendMessage answers null when it sent nothing (no fan, an invalid id) and throws unless OF said success.
        void w.unsend(m).then(
          (r) => {
            done();
            if (r != null) note(doc, send(), "Unsent");
            else failed("unsend")(new Error("nothing was sent"));
          },
          (e) => (done(), failed("unsend")(e)),
        );
      }, anchor);
    }
  };

  // The thread's redraws (records of its own draw dropped): the ⋮ drawn since the bind and a waiting red note.
  const redraws = doc.defaultView ? new doc.defaultView.MutationObserver(() => draw()) : null;
  const draw = () => {
    // The thread's ⋮ drawn since the bind (its redraws clone the tagged template) are Wired as the bind's.
    for (const b of doc.querySelectorAll(`${MENU_BTN}:not([data-oi-wired])`)) b.setAttribute("data-oi-wired", "");
    placePending();
    redraws?.takeRecords();
  };
  draw();
  redraws?.observe(doc.querySelector(".b-chat__messages-wrapper") ?? doc.body, { childList: true, subtree: true });
  const unsendFromExtras: UnsendAction = (m, anchor, live) => act("unsend", m, anchor, live) ?? null;
  const unbindExtras = ctx.newWrites ? bindBubbleExtras(doc, { ...ctx, unsend: unsendFromExtras }) : undefined;

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const item = t.closest<HTMLElement>(`#${MENU_ID} [data-oi-msg-action]`);
    // ticket 42: a hand-off's click is the browser's (a new tab); the menu closes after it.
    if (item?.matches("a[href]")) return void doc.defaultView?.setTimeout(close, 0);
    if (item) {
      ev.preventDefault();
      ev.stopPropagation();
      if (item.getAttribute("aria-disabled") === "true" || !open) return;
      const key = item.dataset.oiMsgAction as MessageAction | "unpin-all";
      const at = open;
      close();
      if (key === "unpin-all") {
        const w = ready(at.btn);
        if (!w) return;
        return confirm("Unpin all messages", "Unpin every pinned message in this chat?", "Unpin all", (fail, done) => void w.unpinAll().then(done, fail), at.btn);
      }
      const m = at.id ? ctx.message(at.id) : undefined;
      if (!m) return note(doc, at.btn, "This message has not loaded yet");
      return act(key, m, at.btn.closest<HTMLElement>("[data-oi-msg]") ?? at.btn);
    }
    const pinned = t.closest<HTMLButtonElement>(PINNED_BTN);
    const btn = pinned ?? t.closest<HTMLButtonElement>(MENU_BTN);
    if (btn) {
      ev.preventDefault();
      ev.stopPropagation();
      if (open?.btn === btn) return close();
      close();
      if (pinned) {
        if (pinned.disabled) return;
        dropdown(doc, pinned, [{ key: "unpin-all" as MessageAction, label: "Unpin all messages" }], true);
        open = { btn: pinned, id: null };
        return;
      }
      const host = btn.closest<HTMLElement>("[data-oi-msg]");
      const id = host?.dataset.oiMsg ?? null;
      const m = id ? ctx.message(id) : undefined;
      if (!host || !m) return note(doc, btn, "This message has not loaded yet");
      const mine = host.classList.contains("m-from-me");
      dropdown(doc, btn, messageItems(m, { mine, limited: ctx.limited, left: ctx.left(m), chat: ctx.chat }), mine);
      // Unsend's countdown, as OF's item ticks (only while this menu is open).
      const timer = mine && ctx.left(m) > 0 ? doc.defaultView?.setInterval(() => {
        const el = doc.querySelector<HTMLElement>(`#${MENU_ID} [data-oi-msg-action='unsend']`);
        const left = ctx.left(ctx.message(id!) ?? m);
        if (el && left > 0) el.textContent = ` Unsend ${countdown(left)} `;
        else el?.remove();
      }, 1000) : undefined;
      open = { btn, id, timer };
      return;
    }
    // Anywhere else: the menu closes, as OF's.
    if (open && !t.closest(`#${MENU_ID}`)) close();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") return close();
    // A focused item: Enter or Space picks it, as a click.
    const item = (ev.key === "Enter" || ev.key === " ") && (ev.target as Element | null)?.closest?.<HTMLElement>(`#${MENU_ID} [data-oi-msg-action]`);
    if (!item) return;
    ev.preventDefault();
    item.click();
  };
  // A scroll moves the menu with its button (OF's popper); it closes once the button leaves the view.
  const onScroll = (ev: Event) => {
    const menu = doc.getElementById(MENU_ID);
    if (!open || !menu || (ev.target as Element | null)?.closest?.(`#${MENU_ID}`)) return;
    if (!place(menu, open.btn)) close();
  };
  doc.addEventListener("click", onClick, true);
  doc.addEventListener("keydown", onKey);
  doc.addEventListener("scroll", onScroll, true);
  return () => {
    close();
    unbindExtras?.();
    doc.defaultView?.clearTimeout(pendingTimer);
    redraws?.disconnect();
    doc.removeEventListener("click", onClick, true);
    doc.removeEventListener("keydown", onKey);
    doc.removeEventListener("scroll", onScroll, true);
  };
}

/** The open chat's message writes for `accountId` (each patches what OF changed and refreshes the rest). */
export function messageWrites(accountId: string, chat: string, qc: QueryClient, unsend: (m: OFMessage) => Promise<unknown>): MessageWrites {
  const fanId = fanIdFromParam(chat);
  const opts = { accountId };
  const threadKey = ["messages", accountId, fanId] as const;
  const pinnedKey = ["chat-pinned", accountId, String(fanId ?? "")] as const;
  const patch = (id: string, change: Partial<MenuMessage> | null) => {
    for (const key of [threadKey, pinnedKey]) {
      qc.setQueryData<OFMessage[]>(key, (prev) => prev && (change ? prev.map((m) => (String(m.id) === id ? { ...m, ...change } : m)) : prev.filter((m) => String(m.id) !== id)));
    }
  };
  /** The write, its patch first and undone on an error. */
  const write = <T,>(id: string, change: Partial<MenuMessage> | null, undo: Partial<MenuMessage> | null, call: () => Promise<T>, after?: () => void) => {
    const before = [qc.getQueryData(threadKey), qc.getQueryData(pinnedKey)];
    patch(id, change);
    return call().then(
      (r) => (after?.(), r),
      (e) => {
        if (undo || !change) {
          qc.setQueryData(threadKey, before[0]);
          qc.setQueryData(pinnedKey, before[1]);
        }
        throw e;
      },
    );
  };
  const enc = encodeURIComponent(chat);
  const pinsChanged = () => {
    void qc.invalidateQueries({ queryKey: pinnedKey });
    void qc.invalidateQueries({ queryKey: mirrorQuery(accountId, chatPath(chat), true).queryKey }); // the header's pin
    void qc.invalidateQueries({ queryKey: ["chats"] }); // the Pinned tab
  };
  return {
    like: (id, on) => write(id, { isLiked: on }, { isLiked: !on }, () => (on ? relay.post(`/api/of/v2/messages/${id}/like`, undefined, opts) : relay.delete(`/api/of/v2/messages/${id}/like`, opts))),
    pin: (id, on) => write(id, { isPinned: on }, { isPinned: !on }, () => (on ? relay.post(`/api/of/v2/messages/${id}/pin/user/${enc}`, undefined, opts) : relay.delete(`/api/of/v2/messages/${id}/pin/user/${enc}`, opts)), pinsChanged),
    bookmark: (id, group, on) =>
      write(id, { isAddedToBookmarks: on }, { isAddedToBookmarks: !on }, () => {
        const body = group != null ? { chat_group_id: group } : undefined;
        return on ? relay.post(`/api/of/v2/messages/${id}/bookmark`, body, opts) : relay.delete(`/api/of/v2/messages/${id}/bookmark`, opts, body);
      }),
    hide: (id) => write(id, null, null, () => relay.put(`/api/of/v2/messages/${id}/hide`, { withUserId: fanId }, opts)),
    // On success the pinned page's cache drops it too, or its bubble and Unsend PPV stay for another DELETE (W30 W3);
    // useUnsendMessage keeps it to one DELETE per message in flight, across every caller.
    unsend: (m) =>
      unsend(m).then((r) => {
        if (r != null) {
          patch(String(m.id), null);
          void qc.invalidateQueries({ queryKey: pinnedKey });
        }
        void qc.invalidateQueries({ queryKey: ["chats"] });
        return r;
      }),
    unpinAll: () => relay.delete(`/api/of/v2/chats/${enc}/messages/pin`, opts).then((r) => (patchAllUnpinned(), pinsChanged(), r)),
  };
  function patchAllUnpinned() {
    qc.setQueryData<OFMessage[]>(pinnedKey, (prev) => (prev ? [] : prev));
    qc.setQueryData<OFMessage[]>(threadKey, (prev) => prev?.map((m) => (m.isPinned ? { ...m, isPinned: false } : m)));
  }
}

/** A message's cancelSeconds as last read, and when. */
export interface MessageRead {
  cs: number;
  at: number;
}
/** Stamp the messages whose cancelSeconds is new (a fresh read; a patched copy keeps its value, so its time too). */
export function stampReads(reads: Map<string, MessageRead>, messages: readonly MenuMessage[] | undefined, now = Date.now()): void {
  for (const m of messages ?? []) {
    const cs = m.cancelSeconds ?? 0;
    const was = reads.get(String(m.id));
    if (!was || was.cs !== cs) reads.set(String(m.id), { cs, at: now });
  }
}
/** The seconds `m` may still be unsent: its cancelSeconds less the time since that value was read. */
export function unsendLeft(reads: Map<string, MessageRead>, m: MenuMessage, now = Date.now()): number {
  const cs = m.cancelSeconds ?? 0;
  const r = reads.get(String(m.id));
  const at = r && r.cs === cs ? r.at : now;
  return Math.max(0, Math.floor(cs - (now - at) / 1000));
}

/** The chat page, its pinned page or a State page over it (menu, price, schedule, tags, vault): its mirror path, else "". */
const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/chat(?:\/pinned|\/state-[a-z-]+)?)\.html$/.exec(src)?.[1] ?? "";

/** The thread's message menus: bind on every frame load and data change. */
export function useOfMessageMenu(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const params = useSearchParams();
  const page = pageOf(src);
  const chat = page ? params.get("chat") : null;
  const fanId = chat ? fanIdFromParam(chat) : null;
  const isPinned = page === "messages/chat/pinned";
  const { unsendOne } = useUnsendMessage(accountId, fanId);
  const unsend = useRef(unsendOne);
  unsend.current = unsendOne;
  const users = useQuery(mirrorQuery<Record<string, FanState>>(accountId, chat && usersListPath([chat]), !!page));
  const fan = chat ? (users.data as Record<string, FanState> | undefined)?.[chat] : undefined;
  const limited = !!(fan?.isRestricted || fan?.isBlocked);
  // The pins (the pinned page's thread): their count turns Unpin all on or off.
  const pinned = useChatPinned(accountId, fanId, { enabled: isPinned });
  const pins = isPinned ? pinned.data?.length : undefined;
  const newWrites = useOfmNewWrites(!!page, accountId);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    const threadKey = ["messages", accountId, fanId];
    const pinnedKey = ["chat-pinned", accountId ?? "", String(fanId ?? "")];
    const key = isPinned ? pinnedKey : threadKey;
    const writes = accountId && chat ? messageWrites(accountId, chat, qc, (m) => unsend.current(m)) : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      unbind = bindMessageMenu(doc, {
        chat,
        message: (id) => (qc.getQueryData<MenuMessage[]>(key) ?? []).find((m) => String(m.id) === id),
        left: (m) => unsendLeft(reads, m),
        limited,
        pins,
        writes,
        storage: window.sessionStorage,
        accountId,
        copy: (text) => frame.contentWindow?.navigator.clipboard?.writeText(text) ?? Promise.reject(new Error("no clipboard")),
        newWrites,
      });
    };
    // When each message's cancelSeconds was read (an older page read later must not restart the newer ones' clocks).
    const reads = new Map<string, MessageRead>();
    const stamp = () => stampReads(reads, qc.getQueryData<MenuMessage[]>(key));
    stamp();
    const unsubscribe = qc.getQueryCache().subscribe((e) => {
      if (e.type === "updated" && JSON.stringify(e.query.queryKey) === JSON.stringify(key)) stamp();
    });
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      unsubscribe();
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, accountId, chat, fanId, isPinned, limited, pins, qc, newWrites]);
}
