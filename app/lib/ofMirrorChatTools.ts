"use client";


import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, type OFChatItem, type OFUserMini } from "@/lib/relay";
import { mirrorQuery } from "@/lib/ofMirrorData";
import { chatPath, usersListPath } from "@/lib/ofMirrorDataQueries";
import { setAvatar } from "@/lib/ofMirrorDom";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { afterChatWrite } from "@/lib/ofMirrorKeys";
import { frameNavigate, takeCarried, toast } from "@/lib/ofMirrorPost";
import { setIconName } from "@/lib/ofMirrorThread";
import { ELSEWHERE } from "@/lib/ofMirrorTooltip";
import { asHandoff, HANDOFF_TITLE, reportHandoffUrl } from "@/lib/ofMirrorHandoffs";
import { message, modalButton, note, NOT_YET, openModal, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { proxyImage } from "@/lib/mediaUrl";
import {
  DISCOUNT_PERIODS, discountPercents, discountShown, discountSummary, MIN_DISCOUNT, months, offListDiscount, putFanDiscount, wasSubscriber,
} from "@/lib/fanDiscount";

export interface ListState {
  id: string | number;
  type?: string;
  name?: string;
  hasUser?: boolean;
  canAddUser?: boolean;
  cannotAddUserReason?: string | null;
}

export interface FanState extends OFUserMini {
  displayName?: string | null;
  notice?: string | null;
  listsStates?: ListState[];
  isRestricted?: boolean;
  isBlocked?: boolean;
  canRestrict?: boolean;
  canTrialSend?: boolean;
  subscribedOn?: boolean | null;
  subscribedBy?: boolean | null;
  subscribedOnExpire?: string | boolean | null;
  subscribedOnExpiredNow?: boolean | null;
  subscribedByExpire?: string | boolean | null;
  subscribedIsExpiredNow?: boolean | null;
  isActive?: boolean;
  isDeleted?: boolean;
  subscribedOnData?: { discountPercent?: number | null; discountPeriod?: number | null } | null;
}

// OF's automatic lists are never "added" by the Creator, so they do not light the star.
const AUTO_LISTS = new Set(["fans", "following", "rebill_on", "rebill_off", "tagged", "recent", "purchased"]);

export function addedLists(fan: FanState | undefined): ListState[] {
  const seen = new Set<string>();
  return (fan?.listsStates ?? []).filter((l) => {
    const key = String(l.id);
    if (!l.hasUser || AUTO_LISTS.has(l.type ?? "") || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export const canRename = (f: FanState) =>
  !f.isBlocked && !!(f.subscribedOn || f.subscribedBy || f.subscribedOnExpire || f.subscribedOnExpiredNow || f.subscribedByExpire || f.subscribedIsExpiredNow);

export interface ToolsMe {
  subscribePrice?: number | null;
  isPerformer?: boolean | null;
}

export interface ChatToolWrites {
  rename(name: string): Promise<unknown>;
  note(text: string): Promise<unknown>;
  list(listId: string, on: boolean): Promise<unknown>;
  discount(discount: number, period: number): Promise<unknown>;
  restrict(on: boolean): Promise<unknown>;
  block(on: boolean): Promise<unknown>;
}

export interface ChatToolsContext {
  chat: string | null;
  fan?: FanState;
  info?: Pick<OFChatItem, "isMutedNotifications"> & { hasPurchasedFeed?: boolean };
  me?: ToolsMe;
  writes: ChatToolWrites | null;
  back: string;
  navigate(href: string, toast?: string): void;
  copy(text: string): Promise<void>;
  img(url: string): string;
}

const TOOL = "[data-oi-tool]";
const MENU_ITEM = ".of-state-menu [data-oi-menu]";
const MENU = ".of-state-menu";
const HEADER_MORE = ".b-chat__header .b-dropdown-wrapper > button.m-btn-vertical-dots:not(.m-size-sm):not([data-oi-pinned-menu])";
const NOTES_ID = "oi-chat-notes";
const RENAME_ID = "oi-chat-rename";
const LISTS_ID = "oi-chat-lists";
const DISCOUNT_ID = "oi-chat-discount";
const BLOCK_ID = "oi-chat-block";
export const FLAT = "g-btn m-flat m-btn-gaps m-reset-width";
export const COPIED = "Link copied to clipboard";
export const SAVED = "Saved";
export const NOT_LOADED_FAN = "This user has not loaded yet";

export function field(doc: Document, label: string, value: string, multi = false): { row: HTMLElement; input: HTMLInputElement | HTMLTextAreaElement } {
  const row = doc.createElement("div");
  row.className = "g-input__wrapper input-text-field m-reset-bottom-gap";
  row.innerHTML =
    '<div class="v-input form-control g-input mb-0 theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width:0px"><span class="notranslate">​</span></legend></fieldset><div class="v-text-field__slot"><label class="v-label v-label--active theme--light" style="left:0px;right:auto;position:absolute"></label></div></div></div></div>';
  const input = doc.createElement(multi ? "textarea" : "input") as HTMLInputElement | HTMLTextAreaElement;
  input.setAttribute("at-attr", "input");
  input.setAttribute("autocomplete", "off");
  if (!multi) (input as HTMLInputElement).type = "text";
  else (input as HTMLTextAreaElement).rows = 4;
  input.value = value;
  input.style.cssText = "width:100%";
  row.querySelector(".v-label")!.textContent = label;
  row.querySelector(".v-text-field__slot")!.append(input);
  return { row, input };
}

export function choice(doc: Document, type: "checkbox" | "radio", name: string, label: string, checked: boolean, disabled = false): { row: HTMLLabelElement; box: HTMLInputElement } {
  const row = doc.createElement("label");
  row.className = "b-rows-lists__item g-pointer-cursor";
  row.style.cssText = "display:flex;align-items:center;gap:12px;padding:10px 0;font-size:15px";
  const box = doc.createElement("input");
  box.type = type;
  box.name = name;
  box.checked = checked;
  box.disabled = disabled;
  row.append(box, label);
  if (disabled) row.title = NOT_YET;
  return { row, box };
}

function select(doc: Document, label: string, options: { value: number; text: string }[], value: number): { row: HTMLElement; input: HTMLSelectElement } {
  const row = doc.createElement("div");
  row.className = "g-input__wrapper";
  row.style.cssText = "margin-bottom:16px";
  const title = doc.createElement("div");
  title.className = "g-input__label g-sm-text g-gray-text";
  title.textContent = label;
  const input = doc.createElement("select");
  input.className = "form-control g-input";
  input.style.cssText = "width:100%;height:44px";
  for (const o of options) {
    const el = doc.createElement("option");
    el.value = String(o.value);
    el.textContent = o.text;
    input.append(el);
  }
  input.value = String(value);
  row.append(title, input);
  return { row, input };
}

export const dialog: typeof openModal = (...a) => {
  const m = openModal(...a);
  m.modal.setAttribute("data-oi-wired", "");
  return m;
};

export function dialogError(modal: HTMLElement, text: string) {
  const doc = modal.ownerDocument;
  const body = modal.querySelector(".modal-body")!;
  let line = body.querySelector<HTMLElement>("[data-oi-error]");
  if (!line) {
    line = doc.createElement("div");
    line.dataset.oiError = "";
    line.setAttribute("role", "alert");
    line.style.cssText = "padding:8px 0 0;font-size:13px;color:#ff4545";
    body.append(line);
  }
  line.textContent = text;
}

export type FanToolsContext = Pick<ChatToolsContext, "chat" | "fan" | "me" | "writes">;
export function fanTools(doc: Document, ctx: FanToolsContext, menu: Pick<ChatToolsContext, "back" | "navigate"> | null) {
  const { fan, writes } = ctx;
  const closeMenu = () => {
    for (const el of doc.querySelectorAll<HTMLElement>(`${MENU}, .of-state-backdrop`)) el.style.display = "none";
  };
  const done = (text?: string) => {
    if (menu) menu.navigate(menu.back, text);
    else if (text) toast(doc, text);
  };
  const ready = (anchor: Element): ChatToolWrites | null => {
    if (!writes) return note(doc, anchor, SELECT_MODEL), null;
    if (!fan || !ctx.chat) return note(doc, anchor, NOT_LOADED_FAN), null;
    return writes;
  };
  const fail = dialogError;
  const cancel = (close: () => void) => ({ text: "Cancel", className: FLAT, onClick: () => (close(), done()) });

  const textDialog = (id: string, title: string, fieldLabel: string, value: string, multi: boolean, save: (v: string) => Promise<unknown>, opener: Element) => {
    let input: HTMLInputElement | HTMLTextAreaElement | null = null;
    const m = dialog(doc, id, title, (body) => {
      const f = field(doc, fieldLabel, value, multi);
      input = f.input;
      body.append(f.row);
    }, [], opener);
    const close = () => m.close();
    const foot = m.modal.querySelector("footer")!;
    const saveBtn = modalButton(doc, {
      text: "Save",
      className: FLAT,
      onClick: () => {
        saveBtn.disabled = true;
        save(input!.value.trim()).then(
          () => (close(), done(SAVED)),
          (e) => ((saveBtn.disabled = false), fail(m.modal, `Could not save: ${message(e)}`)),
        );
      },
    });
    foot.append(modalButton(doc, cancel(close)), saveBtn);
    if (menu) m.modal.addEventListener("click", (ev) => (ev.target as Element).matches(".modal-backdrop") && done());
    (input as HTMLElement | null)?.focus();
  };

  const rename = (opener: Element) => {
    const w = ready(opener);
    if (!w) return;
    textDialog(RENAME_ID, "Rename user", "Display name", fan!.displayName ?? "", false, (v) => w.rename(v), opener);
  };
  const editNotes = (opener: Element) => {
    const w = ready(opener);
    if (!w) return;
    textDialog(NOTES_ID, fan!.notice ? "Edit notes" : "Add notes", "Notes", fan!.notice ?? "", true, (v) => w.note(v), opener);
  };

  const lists = (opener: Element) => {
    const w = ready(opener);
    if (!w) return;
    const rows = (fan!.listsStates ?? []).filter((l) => l.hasUser || l.canAddUser);
    const m = dialog(doc, LISTS_ID, "Add to / remove from lists", (body) => {
      if (!rows.length) {
        const empty = doc.createElement("div");
        empty.className = "empty-message";
        empty.textContent = "Nothing found";
        body.append(empty);
      }
      for (const l of rows) {
        const fixed = AUTO_LISTS.has(l.type ?? "");
        const { row, box } = choice(doc, "checkbox", "oi-list", l.name ?? String(l.id), !!l.hasUser, fixed);
        row.dataset.oiList = String(l.id);
        if (fixed) row.title = "OnlyFans keeps this list";
        box.addEventListener("change", () => {
          const on = box.checked;
          box.disabled = true;
          w.list(String(l.id), on).then(
            () => (box.disabled = false),
            (e) => {
              box.checked = !on;
              box.disabled = false;
              fail(m.modal, `Could not ${on ? "add to" : "remove from"} ${l.name ?? "the list"}: ${message(e)}`);
            },
          );
        });
        body.append(row);
      }
    }, [], opener);
    m.modal.querySelector("footer")!.append(modalButton(doc, { text: "Close", className: FLAT, onClick: () => (m.close(), done()) }));
  };

  const discount = (opener: Element) => {
    const w = ready(opener);
    if (!w) return;
    const price = ctx.me?.subscribePrice ?? 0;
    const current = fan!.subscribedOnData?.discountPercent ?? 0;
    const pct = discountPercents(price);
    let percentSel!: HTMLSelectElement, periodSel!: HTMLSelectElement, help: HTMLElement;
    // `let`: the select handlers can run while the dialog is built, before Apply exists.
    // eslint-disable-next-line prefer-const
    let apply: HTMLButtonElement | undefined;
    const m = dialog(doc, DISCOUNT_ID, "Give user a discount", (body) => {
      const tabs = doc.createElement("div");
      tabs.className = "b-tabs__nav m-nv m-mb-14";
      tabs.style.cssText = "display:flex;gap:16px;margin-bottom:16px";
      const tab = (text: string, on: boolean) => {
        const b = doc.createElement("button");
        b.type = "button";
        b.className = `b-tabs__nav__link${on ? " m-current" : ""}`;
        b.textContent = text;
        if (!on) {
          b.disabled = true;
          b.title = NOT_YET;
        }
        return b;
      };
      tabs.append(tab("Discount", true), tab("Free trial", false));
      const offList = offListDiscount(current, pct);
      const p = select(doc, "Discount", [...(offList ? [{ value: current, text: `${current}% discount (current)` }] : []), ...pct.map((v) => ({ value: v, text: `${v}% discount` }))], current || MIN_DISCOUNT);
      if (offList) p.input.options[0].disabled = true;
      const d = select(doc, "For", DISCOUNT_PERIODS.map((n) => ({ value: n, text: months(n) })), Math.max(1, fan!.subscribedOnData?.discountPeriod ?? 1));
      percentSel = p.input;
      periodSel = d.input;
      help = doc.createElement("p");
      help.className = "g-input__help m-last m-text";
      const sync = () => {
        help.textContent = discountSummary(price, Number(percentSel.value), Number(periodSel.value));
        if (apply) apply.disabled = !pct.includes(Number(percentSel.value));
      };
      percentSel.addEventListener("change", sync);
      periodSel.addEventListener("change", sync);
      sync();
      body.append(tabs, p.row, d.row, help);
    }, [], opener);
    const send = (dPct: number, period: number, btn: HTMLButtonElement) => {
      btn.disabled = true;
      w.discount(dPct, period).then(
        () => (m.close(), done(dPct ? "Discount applied" : "Discount cleared")),
        (e) => ((btn.disabled = false), fail(m.modal, `Could not save the discount: ${message(e)}`)),
      );
    };
    const clear: HTMLButtonElement = modalButton(doc, { text: "Clear", className: FLAT, onClick: () => send(0, 1, clear) });
    clear.disabled = !current;
    apply = modalButton(doc, { text: "Apply", className: FLAT, onClick: () => send(Number(percentSel.value), Number(periodSel.value), apply!) });
    apply.disabled = !pct.includes(Number(percentSel.value));
    m.modal.querySelector("footer")!.append(modalButton(doc, cancel(() => m.close())), clear, apply);
  };

  const restrict = (el: HTMLElement) => {
    const w = ready(el);
    if (!w) return;
    const on = !fan!.isRestricted;
    // The Relay's restrict also sends the fan "." and hides the chat unless told not to; OF's does neither.
    w.restrict(on).then(
      () => done(on ? "User restricted" : "User unrestricted"),
      (e) => note(doc, el, `Could not ${on ? "restrict" : "unrestrict"}: ${message(e)}`, true),
    );
  };
  const block = (el: HTMLElement) => {
    const w = ready(el);
    if (!w) return;
    const go = (on: boolean, after: () => void, failed: (e: unknown) => void) =>
      w.block(on).then(() => (after(), done(on ? "User blocked" : "User unblocked")), failed);
    if (fan!.isBlocked) return void go(false, () => {}, (e) => note(doc, el, `Could not unblock: ${message(e)}`, true));
    const m = dialog(doc, BLOCK_ID, "Block user", (body) => {
      const p = doc.createElement("p");
      p.textContent = `Block @${fan!.username ?? fan!.id}? They will not be able to message you or see your profile.`;
      body.append(p);
    }, [], el);
    const yes: HTMLButtonElement = modalButton(doc, {
      text: "Block",
      className: FLAT,
      onClick: () => {
        yes.disabled = true;
        go(true, () => m.close(), (e) => ((yes.disabled = false), fail(m.modal, `Could not block: ${message(e)}`)));
      },
    });
    m.modal.querySelector("footer")!.append(modalButton(doc, cancel(() => m.close())), yes);
  };

  return { closeMenu, done, rename, editNotes, lists, discount, restrict, block };
}

export function bindChatTools(doc: Document, page: string, ctx: ChatToolsContext): () => void {
  const { fan, writes } = ctx;
  const onMenu = page === "messages/chat/state-header-menu";
  takeCarried(doc);

  const tool = (name: string) => doc.querySelector<HTMLButtonElement>(`${TOOL}[data-oi-tool='${name}']`);
  const pencil = tool("rename");
  const star = tool("lists");
  const notes = tool("notes");
  for (const el of [pencil, star, notes]) el?.setAttribute("data-oi-wired", "");
  doc.querySelector(HEADER_MORE)?.setAttribute("data-oi-wired", "");
  if (fan) {
    if (pencil) pencil.style.display = canRename(fan) ? "" : "none";
    if (star) {
      const on = addedLists(fan).length > 0;
      star.classList.toggle("m-active", on);
      star.classList.toggle("m-gray", !on);
      setIconName(star.querySelector("svg"), on ? "icon-star-on" : "icon-star-default");
      star.setAttribute("aria-label", on ? "Open lists" : "Add to lists");
    }
    if (notes) {
      notes.style.display = wasSubscriber(fan) ? "" : "none";
      notes.setAttribute("aria-label", fan.notice ? "Edit notes" : "Add notes");
    }
  }
  const bell = doc.querySelector<HTMLButtonElement>("button[at-attr='mute_chat']");
  if (bell && ctx.info?.isMutedNotifications !== undefined) {
    const muted = !!ctx.info.isMutedNotifications;
    setIconName(bell.querySelector("svg"), muted ? "icon-notification-off" : "icon-notification");
    bell.classList.toggle("m-gray", muted);
  }

  const items = [...doc.querySelectorAll<HTMLElement>(MENU_ITEM)];
  const item = (key: string) => items.find((i) => i.dataset.oiMenu === key);
  const label = (el: HTMLElement | undefined, text: string) => {
    const t = el && [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent?.trim());
    if (t) t.textContent = ` ${text} `;
  };
  for (const el of items) el.setAttribute("data-oi-wired", "");
  const reportItem = onMenu ? item("report") : null;
  if (reportItem && ctx.chat) {
    reportItem.querySelector("a.of-state-link")?.remove();
    const a = asHandoff(reportItem, reportHandoffUrl("chat", { fanId: ctx.chat }));
    a.title = HANDOFF_TITLE;
    a.classList.remove("v-list-item--disabled");
  } else if (reportItem) {
    for (const attr of ["href", "target", "rel"]) reportItem.removeAttribute(attr);
    reportItem.querySelector("a.of-state-link")?.remove();
    reportItem.classList.add("v-list-item--disabled");
    reportItem.setAttribute("aria-disabled", "true");
    reportItem.title = NOT_YET;
  }
  if (onMenu && fan) {
    const show = (key: string, on: boolean) => {
      const el = item(key);
      if (el) el.style.display = on ? "" : "none";
    };
    show("rename", canRename(fan));
    show("discount", discountShown(fan, ctx.me?.subscribePrice));
    show("comments", ctx.me?.isPerformer !== false && wasSubscriber(fan));
    show("restrict", !fan.isBlocked && (!!fan.canRestrict || !!fan.isRestricted));
    label(item("restrict"), fan.isRestricted ? `Unrestrict @${fan.username ?? fan.id}` : "Restrict");
    label(item("block"), fan.isBlocked ? "Unblock" : "Block");
    const comments = item("comments");
    if (ctx.info?.hasPurchasedFeed && comments && !doc.querySelector("[data-oi-menu='purchases']")) {
      const p = comments.cloneNode(true) as HTMLElement;
      p.dataset.oiMenu = "purchases";
      p.querySelector("a.of-state-link")?.remove();
      p.classList.add("v-list-item--disabled");
      p.setAttribute("aria-disabled", "true");
      p.title = ELSEWHERE.fanPurchases;
      p.style.display = "";
      label(p, "Purchases");
      comments.after(p);
    }
    const own = doc.querySelector<HTMLAnchorElement>(`${MENU} a.m-user-data-item`);
    if (own) {
      own.setAttribute("data-oi-wired", "");
      const handle = own.querySelector(".g-user-username");
      if (handle) handle.textContent = ` @${fan.username ?? fan.id} `;
      setAvatar(own.querySelector(".g-avatar"), fan, ctx.img);
      if (fan.username) {
        own.href = `https://onlyfans.com/${encodeURIComponent(fan.username)}`;
        own.target = "_blank";
        own.rel = "noopener noreferrer";
      }
    }
  }

  const { closeMenu, done, rename, editNotes, lists, discount, restrict, block } = fanTools(doc, ctx, onMenu ? ctx : null);

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    const btn = t.closest<HTMLElement>(TOOL);
    if (btn) {
      ev.preventDefault();
      ev.stopPropagation();
      const name = btn.dataset.oiTool;
      if (name === "rename") rename(btn);
      else if (name === "lists") lists(btn);
      else if (name === "notes") editNotes(btn);
      return;
    }
    const el = t.closest<HTMLElement>(MENU_ITEM);
    const key = el?.dataset.oiMenu;
    if (!el || !key || key === "hide" || key === "mute" || (key === "report" && el.matches("a[href]"))) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (key === "purchases" || key === "report") return;
    if (key === "copy") {
      if (!fan?.username) return note(doc, el, NOT_LOADED_FAN);
      return void ctx.copy(`https://onlyfans.com/${fan.username}`).then(
        () => done(COPIED),
        () => note(doc, el, "Could not copy the link", true),
      );
    }
    if (key === "comments") {
      if (!ctx.chat) return note(doc, el, NOT_LOADED_FAN);
      return ctx.navigate(`/of-manager/notifications/commented?related_user=${encodeURIComponent(ctx.chat)}`);
    }
    if (key === "restrict") return restrict(el);
    if (key === "block") {
      if (!fan?.isBlocked && writes && fan) closeMenu();
      return block(el);
    }
    if (writes && fan) closeMenu();
    if (key === "rename") rename(el);
    else if (key === "lists") lists(el);
    else if (key === "discount") discount(el);
  };
  doc.addEventListener("click", onClick, true);
  return () => doc.removeEventListener("click", onClick, true);
}

export function chatToolWrites(accountId: string, fan: string, qc: QueryClient): ChatToolWrites {
  const f = encodeURIComponent(fan);
  const refresh = <T,>(r: T) => {
    void afterChatWrite(qc, accountId);
    return r;
  };
  const opts = { accountId };
  return {
    rename: (name) => relay.put(`/api/of/v2/subscriptions/${f}/custom-name`, { name }, opts).then(refresh),
    note: (text) => relay.put(`/api/of/v2/subscriptions/${f}/note`, { note: text }, opts).then(refresh),
    list: (id, on) => (on ? relay.post(`/api/of/v2/lists/${encodeURIComponent(id)}/users/${f}`, undefined, opts) : relay.delete(`/api/of/v2/lists/${encodeURIComponent(id)}/users/${f}`, opts)).then(refresh),
    discount: (discount, period) => putFanDiscount(accountId, fan, discount, period).then(refresh),
    restrict: (on) => (on ? relay.post(`/api/of/v2/users/${f}/restrict?ack=false&hide=false`, undefined, opts) : relay.delete(`/api/of/v2/users/${f}/restrict?unhide=false`, opts)).then(refresh),
    block: (on) => (on ? relay.post(`/api/of/v2/users/${f}/block`, undefined, opts) : relay.delete(`/api/of/v2/users/${f}/block`, opts)).then(refresh),
  };
}

const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/chat(?:\/state-[a-z-]+)?)\.html$/.exec(src)?.[1] ?? "";

export function useOfChatTools(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const page = pageOf(src);
  const chat = page ? params.get("chat") : null;
  const users = useQuery(mirrorQuery<Record<string, FanState>>(accountId, chat && usersListPath([chat]), !!page));
  const detail = useQuery(mirrorQuery<OFChatItem>(accountId, chat && chatPath(chat), !!page));
  const me = useQuery(ofMeQuery(page ? accountId : null)).data as ToolsMe | undefined;
  const fan = chat ? (users.data as Record<string, FanState> | undefined)?.[chat] : undefined;
  const info = detail.data as (OFChatItem & { hasPurchasedFeed?: boolean }) | undefined;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    const writes = accountId && chat ? chatToolWrites(accountId, chat, qc) : null;
    const back = chat ? `/of-manager/messages/chat?chat=${encodeURIComponent(chat)}` : "/of-manager/messages/chat";
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      unbind = bindChatTools(doc, page, {
        chat,
        fan,
        info,
        me,
        writes,
        back,
        navigate: frameNavigate(frameRef, (href) => router.push(href)),
        copy: (text) => frame.contentWindow?.navigator.clipboard?.writeText(text) ?? Promise.reject(new Error("no clipboard")),
        img: (u) => proxyImage(u, accountId),
      });
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, accountId, chat, fan, info, me, qc, router]);
}

