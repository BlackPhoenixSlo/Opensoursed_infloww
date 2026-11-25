"use client";


import { useEffect, useMemo, type RefObject } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { gifSearch, gifTrending, relay, type OFChatItem, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultUploadResp } from "@/lib/relay";
import { mirrorQuery, rowsOf } from "@/lib/ofMirrorData";
import { chatPath, usersListPath, withChatUsers, USER_LISTS } from "@/lib/ofMirrorDataQueries";
import type { UserList } from "@/lib/ofMirrorDataLists";
import { handleOf, nameOf, stamp } from "@/lib/ofMirrorDom";
import { afterChatWrite } from "@/lib/ofMirrorKeys";
import { collectSchedule, renderCalendar, tagsRoute, tagViewOf, type TagView, uploadFailed } from "@/lib/ofMirrorPost";
import { type bindComposer, GIF_ALONE } from "@/lib/ofMirrorComposer";
import { hasFormatting, ofHtml, setOfHtml } from "@/lib/ofMirrorFormat";
import { hasOfFormatting } from "@/lib/ofRichText";
import { CHAT_VAULT } from "@/lib/ofMirrorRow";
import { viewOf } from "@/lib/ofMirrorVault";
import { GREY, message, minuteAhead, note, NOTE_STYLE, SELECT_MODEL, textOf, TOO_SOON } from "@/lib/ofMirrorWrites";
import { useAgencyZone } from "@/lib/ofMirrorFeedsShared";
import { ofPrice } from "@/lib/ofMirrorPostCard";
import {
  bindChatTags,
  bindPrice,
  bindTools,
  bindVault,
  EDITOR,
  EMPTY_MESSAGE,
  flight,
  FORM_TAGS,
  load,
  SEND,
  setEditor,
  SUMMARY,
  UPLOADING,
  vaultPickKey,
  type ChatContext,
  type ChatDialog,
  type ChatDraft,
  type ChatHandlers,
} from "@/lib/ofMirrorChatShared";
import { bindMass, FORMAT_PARAM, MASS_FANS, MASS_TAG, massViewOf, tickMassList, USERS_LIST_MAX } from "@/lib/ofMirrorMass";
import { MASS_SEND } from "@/lib/ofMirrorPick";

export {
  loadVaultPick,
  vaultPickKey,
} from "@/lib/ofMirrorChatShared";

export const DRAFT_EVENT = "oi-chat-draft";

export interface ChatMessageBody {
  text: string;
  price: number;
  media_files: Array<number | Record<string, unknown>>;
  scheduled_date?: string;
  reply_to_message_id?: number;
  giphy_id?: string;
  tagged_users?: number[];
  rf_guest?: number[];
  rf_partner?: number[];
  previews?: number[];
  locked_text?: boolean;
}

export const NO_CHAT = "Open a chat from the list to send";
export const NOT_LOADED = "This chat has not loaded yet";
export const NO_SCHEDULED_GIF = "A scheduled message can't carry a GIF";
export const NO_SCHEDULED_FORMS = "A scheduled message can only tag creators";
const TAG_PAGE = "messages/chat/state-tag-people";
const CHAT_PAGE = "/of-manager/messages/chat";
const MESSAGES = "/of-manager/messages";

const MUTE_BTN = "button[at-attr='mute_chat']";
const MENU_ITEM = ".of-state-menu .v-list-item";
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ISO = /^\d{4}-\d{2}-\d{2}T/;

export const chatDraftKey = (accountId: string, chat: string) => `oi:chat:${accountId}:${chat}`;
export const loadChatDraft = (storage: Storage, accountId: string, chat: string): ChatDraft =>
  load<ChatDraft>(storage, chatDraftKey(accountId, chat), { text: "", media_files: [], thumbs: [] });

export interface PickedScript {
  text: string;
  displayText?: string;
  price: number;
  lockedText: boolean;
  media: { id: number }[];
  previews: number[];
  taggedUsers: number[];
  tags?: ChatDraft["tags"];
  gifId?: string | null;
  gifUrl?: string | null;
}

export function applyScript(storage: Storage, accountId: string, chat: string, t: PickedScript, doc: Document | null): void {
  const d = loadChatDraft(storage, accountId, chat);
  const priced = t.price > 0;
  const next: ChatDraft = {
    ...d,
    text: t.text,
    html: t.displayText && hasOfFormatting(t.displayText) ? t.displayText.trim() : undefined,
    price: priced ? t.price : undefined,
    media_files: t.media.map((m) => m.id),
    // Blank on purpose: nothing draws a chat draft's thumbs, and a script's media only has raw CDN urls.
    thumbs: t.media.map(() => ""),
    audio: undefined,
    previews: priced && t.previews.length ? t.previews : undefined,
    locked_text: priced && t.lockedText ? true : undefined,
    tags: t.tags?.length ? t.tags : t.taggedUsers.length ? t.taggedUsers.map((id) => ({ id, type: "user", name: "" })) : undefined,
    giphy_id: t.gifId ?? undefined,
    giphy_thumb: t.gifId ? (t.gifUrl ?? undefined) : undefined,
  };
  storage.setItem(chatDraftKey(accountId, chat), JSON.stringify(next));
  doc?.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: { text: true } }));
}

export function collectMessage(text: string, draft: ChatDraft, now: Date = new Date()): ChatMessageBody | string {
  const t = text.trim();
  if (!t && !draft.media_files.length && !draft.giphy_id) return EMPTY_MESSAGE;
  const body: ChatMessageBody = { text: t, price: draft.price ?? 0, media_files: [...draft.media_files] };
  if (body.price > 0) {
    const free = (draft.previews ?? []).filter((id) => draft.media_files.includes(id));
    if (free.length) body.previews = free;
    if (draft.locked_text) body.locked_text = true;
  }
  const tags = draft.tags ?? [];
  const of = (...types: string[]) => tags.filter((x) => types.includes(x.type)).map((x) => x.id);
  const users = tags.filter((x) => !FORM_TAGS.includes(x.type)).map((x) => x.id);
  const [guests, partners] = [of("guest"), of("link", "document")];
  if (users.length) body.tagged_users = users;
  if (draft.scheduled_date) {
    if (draft.giphy_id) return NO_SCHEDULED_GIF;
    if (guests.length || partners.length) return NO_SCHEDULED_FORMS;
    if (!minuteAhead(new Date(draft.scheduled_date), now)) return TOO_SOON;
    body.scheduled_date = draft.scheduled_date;
    return body;
  }
  if (draft.reply_to && /^\d+$/.test(draft.reply_to)) body.reply_to_message_id = Number(draft.reply_to);
  // OF: a GIF goes alone, bar a voice note.
  if (draft.giphy_id && (draft.media_files.length > (draft.audio ?? 0) || tags.length || body.price)) return GIF_ALONE;
  if (draft.giphy_id) body.giphy_id = draft.giphy_id;
  if (guests.length) body.rf_guest = guests;
  if (partners.length) body.rf_partner = partners;
  return body;
}

export const sendPath = (chat: string, body: ChatMessageBody) =>
  `/api/of/v2/chats/${encodeURIComponent(chat)}/messages${body.scheduled_date ? "/scheduled" : ""}`;

const shownMonth = (doc: Document): Date | null => {
  const [name, year] = (doc.querySelector(SHOWN)?.textContent ?? "").trim().split(/\s+/);
  const m = MONTHS.indexOf(name);
  return m >= 0 && /^\d{4}$/.test(year ?? "") ? new Date(+year, m, 1) : null;
};
const clock12 = (d: Date) => `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;

export function bindChat(doc: Document, page: string, ctx: ChatContext): () => void {
  const { handlers, chat } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const send = doc.querySelector<HTMLButtonElement>(SEND);
  if (!editor || !send) return () => {};
  const keep = handlers && ctx.storage && ctx.accountId && chat ? { storage: ctx.storage, key: chatDraftKey(ctx.accountId, chat), accountId: ctx.accountId, chat } : null;
  const draftOf = (): ChatDraft => (keep ? loadChatDraft(keep.storage, keep.accountId, keep.chat) : { text: "", media_files: [], thumbs: [] });
  if (page !== CHAT_VAULT && ctx.storage && ctx.accountId) ctx.storage.removeItem(vaultPickKey(ctx.accountId, CHAT_VAULT, chat));
  const back = chat ? `${CHAT_PAGE}?chat=${encodeURIComponent(chat)}` : CHAT_PAGE;
  send.setAttribute("data-oi-wired", "");
  editor.setAttribute("data-oi-wired", "");

  const summary = () => {
    const { price, scheduled_date: at, media_files: media, reply_to: reply, reply_text: quoted, giphy_id: gif, tags = [] } = draftOf();
    const parts = [
      ...(reply ? [`Replying to “${(quoted ?? "").slice(0, 60)}${(quoted ?? "").length > 60 ? "…" : ""}”`] : []),
      ...(price ? [`Price: ${ofPrice(price)}`] : []),
      ...(at ? [`Scheduled for ${stamp(new Date(at))}`] : []),
      ...(media.length ? [`${media.length} media`] : []),
      ...(gif ? ["GIF"] : []),
      ...(tags.length ? [`Tagged: ${tags.map((t) => t.name || `#${t.id}`).join(", ")}`] : []),
    ];
    const old = doc.getElementById(SUMMARY);
    if (!parts.length) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = SUMMARY;
    el.style.cssText = NOTE_STYLE;
    el.style.color = GREY;
    const clear = doc.createElement("a");
    clear.href = "#";
    clear.textContent = "Clear";
    clear.setAttribute("data-oi-wired", "");
    clear.setAttribute("data-oi-clear", "");
    el.replaceChildren(`${parts.join(" · ")} · `, clear);
    if (!old) (editor.closest(".g-input__wrapper") ?? editor).after(el);
  };
  const sync = () => {
    const text = textOf(editor);
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const d = draftOf();
    send.disabled = (!text.trim() && !d.media_files.length && !d.giphy_id) || flight.count > 0;
    composer?.sync();
  };
  let composer: ReturnType<typeof bindComposer> | null = null;
  const update = (patch: Partial<ChatDraft>) => {
    if (keep) keep.storage.setItem(keep.key, JSON.stringify({ ...draftOf(), ...patch }));
    summary();
    sync();
  };

  const saved = draftOf();
  if (saved.html) setOfHtml(editor, saved.html);
  else setEditor(doc, editor, saved.text);
  sync();
  summary();

  const bell = doc.querySelector<HTMLButtonElement>(MUTE_BTN);
  const muted = ctx.fan?.muted;
  if (bell && muted !== undefined) bell.setAttribute("aria-label", muted ? "Unmute notifications" : "Mute notifications");
  bell?.setAttribute("data-oi-wired", "");

  const ready = (anchor: Element): ChatHandlers | null => {
    if (!handlers) return note(doc, anchor, SELECT_MODEL), null;
    if (!chat) return note(doc, anchor, NO_CHAT), null;
    return handlers;
  };
  const toggleMute = (anchor: Element, then?: string) => {
    const h = ready(anchor);
    if (!h) return;
    if (muted === undefined) return note(doc, anchor, NOT_LOADED);
    h.mute(!muted).then(
      () => (then ? h.navigate(then) : note(doc, anchor, muted ? "Unmuted" : "Muted", false, 2000)),
      (e) => note(doc, anchor, `Could not save: ${message(e)}`, true),
    );
  };

  const onInput = (ev: Event) => {
    if (!(ev.target as Element | null)?.closest?.(EDITOR)) return;
    sync();
    update({ text: textOf(editor), html: hasFormatting(editor) ? ofHtml(editor) : undefined });
  };

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest("[data-oi-clear]")) {
      ev.preventDefault();
      return update({ price: undefined, scheduled_date: undefined, media_files: [], thumbs: [], reply_to: undefined, reply_text: undefined, giphy_id: undefined, giphy_thumb: undefined, tags: undefined, audio: undefined, previews: undefined, locked_text: undefined, upload_failed: undefined });
    }
    if (bell && target.closest(MUTE_BTN) === bell) {
      ev.preventDefault();
      return toggleMute(bell);
    }
    if (target.closest(SEND) !== send) return;
    ev.preventDefault();
    const h = ready(send);
    if (!h) return;
    if (flight.count > 0) return note(doc, send, UPLOADING);
    if (send.disabled) return;
    const body = collectMessage(hasFormatting(editor) ? ofHtml(editor) : textOf(editor), draftOf());
    if (typeof body === "string") return note(doc, send, body, true);
    const failed = draftOf().upload_failed;
    if (failed && !h.confirm(uploadFailed(failed))) return;
    if (body.price > 0 && !h.confirm(`Send this message to ${ctx.fan?.name || "this fan"} for ${ofPrice(body.price)}?`)) return;
    send.disabled = true;
    doc.getElementById("oi-note")?.remove();
    h.send(sendPath(chat!, body), body).then(
      () => {
        if (keep) keep.storage.removeItem(keep.key);
        setEditor(doc, editor, "");
        sync();
        summary();
        note(doc, send, body.scheduled_date ? "Scheduled" : "Sent", false, 2000);
      },
      (e) => {
        sync();
        note(doc, send, `Could not send: ${message(e)}`, true);
      },
    );
  };

  const writer = chat ? handlers : null;
  const stay = (href: string) => `${href}${href.includes("?") ? "&" : "?"}chat=${encodeURIComponent(chat!)}`;
  const unbindDialog = Object.hasOwn(CHAT_DIALOGS, page) ? CHAT_DIALOGS[page](doc, ctx, { page, draftOf, update, back, ready, toggleMute, writer, stay }) : () => {};
  const refresh = () => {
    summary();
    sync();
  };
  const tools = bindTools(doc, editor, send, {
    draftOf,
    update,
    refresh,
    ready,
    writer,
    none: handlers ? NO_CHAT : SELECT_MODEL,
    accountId: ctx.accountId,
    key: keep?.key ?? `${ctx.accountId ?? ""}:${chat ?? ""}`,
    tipsEnabled: ctx.fan?.tipsEnabled,
    mobile: ctx.mobile,
  });
  composer = tools.composer;
  sync();
  const onDraft = (ev: Event) => {
    if ((ev as CustomEvent<{ text?: boolean } | null>).detail?.text) {
      const d = draftOf();
      if (d.html) setOfHtml(editor, d.html);
      else setEditor(doc, editor, d.text);
    }
    refresh();
    editor.focus();
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  doc.addEventListener(DRAFT_EVENT, onDraft);
  return () => {
    doc.removeEventListener(DRAFT_EVENT, onDraft);
    tools.unbind();
    unbindDialog();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
}

const bindSchedule: ChatDialog = (doc, _ctx, { draftOf, update, back, ready }) => {
  const timeTab = doc.querySelector<HTMLElement>(TIME_TAB);
  const next = doc.querySelector<HTMLButtonElement>(NEXT);
  if (!timeTab || !next) return () => {};
  const now = new Date();
  const saved = draftOf().scheduled_date;
  const at = saved ? new Date(saved) : null;
  const start = at && at.getTime() > now.getTime() ? at : null;
  renderCalendar(doc, start ?? now, start ?? now, now);
  timeTab.setAttribute("contenteditable", "true");
  timeTab.textContent = clock12(start ?? new Date(now.getTime() + 3_600_000));
  next.setAttribute("data-oi-wired", "");

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    const shown = shownMonth(doc);
    const cell = target.closest<HTMLElement>(`.${DAY}`);
    const day = Number(cell?.textContent?.trim());
    if (cell && shown && day && !cell.classList.contains(`${DAY}--disabled`)) {
      renderCalendar(doc, shown, new Date(shown.getFullYear(), shown.getMonth(), day), new Date());
    }
    const arrow = target.closest(".vdatetime-calendar__navigation--previous, .vdatetime-calendar__navigation--next");
    if (arrow && shown) {
      const today = new Date();
      const step = arrow.matches(".vdatetime-calendar__navigation--next") ? 1 : -1;
      const month = new Date(shown.getFullYear(), shown.getMonth() + step, 1);
      const sel = doc.querySelector(".vdatetime-popup")?.getAttribute("data-oi-selected");
      const picked = sel ? new Date(`${sel}T00:00:00`) : null;
      if (month >= new Date(today.getFullYear(), today.getMonth(), 1)) renderCalendar(doc, month, picked, today);
    }
    if (target.closest(NEXT) !== next) return;
    ev.preventDefault();
    const h = ready(next);
    if (!h) return;
    const moment = collectSchedule(doc);
    if (!ISO.test(moment)) return note(doc, next, moment, true);
    update({ scheduled_date: moment });
    h.navigate(back);
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
};

const bindHeaderMenu: ChatDialog = (doc, ctx, { ready, toggleMute }) => {
  const items = [...doc.querySelectorAll<HTMLElement>(MENU_ITEM)];
  const hide = items.find((i) => i.textContent?.trim() === "Hide chat");
  const mute = items.find((i) => /^(?:un)?mute notifications$/i.test(i.textContent?.trim() ?? ""));
  const label = (el: HTMLElement, text: string) => {
    const t = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent?.trim());
    if (t) t.textContent = ` ${text} `;
  };
  if (mute && ctx.fan?.muted !== undefined) label(mute, ctx.fan.muted ? "Unmute notifications" : "Mute notifications");
  for (const el of [hide, mute]) el?.setAttribute("data-oi-wired", "");
  const onClick = (ev: MouseEvent) => {
    const item = (ev.target as Element | null)?.closest?.(MENU_ITEM);
    if (!item || (item !== hide && item !== mute)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (item === mute) return toggleMute(item, ctx.chat ? `${CHAT_PAGE}?chat=${encodeURIComponent(ctx.chat)}` : CHAT_PAGE);
    const h = ready(item);
    if (!h) return;
    h.hide().then(
      () => h.navigate(MESSAGES),
      (e) => note(doc, item, `Could not hide: ${message(e)}`, true),
    );
  };
  // Capture: before the frame's own link handler, which would go back to the chat.
  doc.addEventListener("click", onClick, true);
  return () => doc.removeEventListener("click", onClick, true);
};

const CHAT_DIALOGS: Record<string, ChatDialog> = {
  [TAG_PAGE]: bindChatTags,
  "messages/chat/state-price": bindPrice,
  "messages/chat/state-schedule": bindSchedule,
  [CHAT_VAULT]: bindVault,
  "messages/chat/state-header-menu": bindHeaderMenu,
};
const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/(?:chat|send)(?:\/state-[^/]+)?)\.html$/.exec(src)?.[1] ?? "";

export function useOfChat(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const chat = params.get("chat");
  const vaultType = params.get("type");
  const vaultList = params.get("list");
  const vaultSlist = params.get("slist");
  const vaultField = params.get("field");
  const vaultSort = params.get("sort");
  const page = pageOf(src);
  const isChat = page.startsWith("messages/chat");
  const detail = useQuery(mirrorQuery<OFChatItem>(accountId, chat && chatPath(chat), isChat));
  const mass = page.startsWith("messages/send");
  const massView = mass ? massViewOf(params.get("list")) : undefined;
  const massTo = mass ? params.get("to") : null;
  const massFormat = mass && params.get(FORMAT_PARAM) === "1";
  const lists = useQuery(mirrorQuery(accountId, USER_LISTS, mass));
  const listRows = rowsOf<UserList>(lists.data);
  const chats = useQuery(mirrorQuery(accountId, MASS_FANS, massView === "users"));
  const fanIds = useMemo(() => [...new Set((rowsOf<OFChatItem>(chats.data) ?? []).flatMap((c) => (c?.withUser ? [String(c.withUser.id)] : [])))].sort(), [chats.data]);
  const partners = useQueries({
    queries: Array.from({ length: Math.ceil(fanIds.length / USERS_LIST_MAX) }, (_, i) => mirrorQuery(accountId, usersListPath(fanIds.slice(i * USERS_LIST_MAX, (i + 1) * USERS_LIST_MAX)), massView === "users")),
  });
  const partnersPending = partners.some((p) => p.isPending);
  const partnersKey = partners.map((p) => p.dataUpdatedAt).join();
  const fans = useMemo(() => {
    const items = rowsOf<OFChatItem>(chats.data);
    if (!items || partnersPending) return undefined;
    const byId = Object.assign({}, ...partners.map((p) => (p.data && typeof p.data === "object" && !Array.isArray(p.data) ? p.data : {})));
    return withChatUsers(items.filter((c) => c?.withUser), byId).map((c) => ({ id: c.withUser.id, name: nameOf(c.withUser), sub: `@${handleOf(c.withUser)}` }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chats.data, partnersPending, partnersKey]);
  const rowsError = massView === "users" ? chats.error : lists.error;
  const with_ = (detail.data as OFChatItem | undefined)?.withUser;
  const fanName = with_ ? nameOf(with_) : undefined;
  const muted = (detail.data as OFChatItem | undefined)?.isMutedNotifications;
  const tipsEnabled = (with_ as { tipsEnabled?: boolean } | undefined)?.tipsEnabled;
  const zone = useAgencyZone();
  const tagPage = page === TAG_PAGE || page === MASS_TAG;
  const tagView = tagViewOf(tagPage ? params : new URLSearchParams());
  const tagKey = JSON.stringify(tagView);
  const tags = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagView), tagPage));
  const tagItems = accountId && tagPage ? (tags.data?.items ?? rowsOf<TaggedFriendUser>(tags.data)) : undefined;

  useEffect(() => {
    if (!massTo || !accountId) return;
    tickMassList(window.sessionStorage, accountId, massTo);
    router.replace(MASS_SEND);
  }, [massTo, accountId, router]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    const refresh = () => Promise.all([afterChatWrite(qc, accountId), qc.invalidateQueries({ queryKey: ["messages", accountId] })]);
    const enc = chat ? encodeURIComponent(chat) : "";
    const handlers: ChatHandlers | null = accountId
      ? {
          send: (path, body) => relay.post(path, body, { accountId }).then((r) => (refresh(), r)),
          put: (path, body) => relay.put(path, body, { accountId }).then((r) => (refresh(), r)),
          upload: (file) => relay.uploadFile<VaultUploadResp>("/api/of/v2/upload", file, "file", { accountId }),
          gifs: (query) => (query ? gifSearch(query, 24, 0, { accountId }) : gifTrending(24, 0, { accountId })).then((r) => r.data ?? []),
          toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
          inviteGuest: (name) => relay.post("/api/of/v2/guests", { name }, { accountId }),
          mute: (on) =>
            (on ? relay.post(`/api/of/v2/chats/${enc}/mute`, undefined, { accountId }) : relay.delete(`/api/of/v2/chats/${enc}/mute`, { accountId })).then((r) => {
              // Set from the answer: a refetch right after can still read OF's old state.
              qc.setQueryData<OFChatItem>(mirrorQuery(accountId, chatPath(chat!), true).queryKey, (d) => (d ? { ...d, isMutedNotifications: on } : d));
              void qc.invalidateQueries({ queryKey: ["chats"] });
              return r;
            }),
          hide: () => relay.post(`/api/of/v2/chats/${enc}/hide`, undefined, { accountId }).then((r) => (refresh(), r)),
          confirm: (text) => window.confirm(text),
          navigate: (href) => router.push(href),
        }
      : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      const ctx: ChatContext = {
        handlers,
        storage: window.sessionStorage,
        accountId,
        chat,
        fan: fanName !== undefined || muted !== undefined ? { name: fanName ?? "", muted, tipsEnabled } : undefined,
        tagItems,
        tagView: JSON.parse(tagKey) as TagView,
        lists: accountId ? listRows : undefined,
        listsError: rowsError ? message(rowsError) : undefined,
        massView,
        massFormat,
        fans: accountId ? fans : undefined,
        vaultView: viewOf({ get: (k) => ({ type: vaultType, list: vaultList, slist: vaultSlist, field: vaultField, sort: vaultSort })[k] ?? null }),
        zone,
      };
      unbind = mass ? bindMass(doc, ctx, page) : bindChat(doc, page, ctx);
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, mass, accountId, chat, fanName, muted, tipsEnabled, listRows, rowsError, massView, massFormat, fans, vaultType, vaultList, vaultSlist, vaultField, vaultSort, qc, router, zone, tagItems, tagKey]);
}
