"use client";


import { type TaggedFriendUser, type GiphyItem, type VaultUploadResp } from "@/lib/relay";
import { toggleTile } from "@/lib/ofMirrorDom";
import type { UserList } from "@/lib/ofMirrorDataLists";
import { loadVaultPick, vaultPickKey, type VaultPick } from "@/lib/ofMirrorPick";
import { bindAddMedia, bindTags, bindVaultSearch, bindVaultTools, mediaTaker, tagHref, type TagView } from "@/lib/ofMirrorPost";
import { bindComposer, GIF_ALONE, isMobile } from "@/lib/ofMirrorComposer";
import { markTypeTabs, TYPES, vaultHref, type VaultView } from "@/lib/ofMirrorVault";
import { note } from "@/lib/ofMirrorWrites";
import { MIN_PRICE, PRICE_NOTE } from "@/lib/sendGuards";
export { load, loadVaultPick, vaultPickKey } from "@/lib/ofMirrorPick";

export interface ChatDraft {
  text: string;
  price?: number;
  scheduled_date?: string;
  media_files: Array<number | Record<string, unknown>>;
  thumbs: string[];
  reply_to?: string;
  reply_text?: string;
  html?: string;
  giphy_id?: string;
  giphy_thumb?: string;
  tags?: ChatTag[];
  audio?: number;
  previews?: number[];
  locked_text?: boolean;
  upload_failed?: Record<string, string>;
}

export interface ChatTag {
  id: number;
  type: string;
  name: string;
}

export const EMPTY_MESSAGE = "Write a message or add media";
export const NO_DATE = "Pick a date or Save for Later";
export const UPLOADING = "Wait for the upload to finish";
// The Relay's edit body (PUT …/queue/{id}) has no GIF.
export const NO_EDIT_GIF = "An edited message can't carry a GIF";
export const FORM_TAGS = ["guest", "link", "document"];

export const EDITOR = "[contenteditable][aria-label='Textbox field']";
export const SEND = "button[at-attr='send_btn']";
const PRICE_INPUT = ".modal.show input[at-attr='input']";
const PRICE_SAVE = ".modal.show .modal-footer button";
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
const VAULT_TABS = ".modal.show .b-tabs__nav__link";
export const SUMMARY = "oi-chat-summary";

export const VAULT_PICK_MAX = 40;

export function readPrice(value: string): number | null {
  const s = value.trim().replace(/^\$\s*/, "");
  if (!s) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(s)) return null;
  const n = Number(s);
  return n === 0 || n >= MIN_PRICE ? n : null;
}

export interface ChatHandlers {
  send(path: string, body: object): Promise<unknown>;
  put?(path: string, body: object): Promise<unknown>;
  upload(file: File): Promise<VaultUploadResp>;
  gifs?(query: string): Promise<GiphyItem[]>;
  toggleTag?(body: { entity_id: number; entity_type: string }): Promise<unknown>;
  inviteGuest?(name: string): Promise<unknown>;
  mute(on: boolean): Promise<unknown>;
  hide(): Promise<unknown>;
  confirm(text: string): boolean;
  navigate(href: string): void;
}

export type MassView = "send" | "exclude" | "users";

export interface ChatContext {
  handlers: ChatHandlers | null;
  storage: Storage | null;
  accountId: string | null;
  chat: string | null;
  fan?: { name: string; muted?: boolean; tipsEnabled?: boolean };
  tagItems?: TaggedFriendUser[];
  tagView?: TagView;
  mobile?: boolean;
  lists?: UserList[];
  listsError?: string;
  massFormat?: boolean;
  massView?: MassView;
  fans?: UserList[];
  vaultView?: Partial<VaultView>;
  zone?: string;
}

export const flight: { count: number; refresh?: () => void } = { count: 0 };

export function setEditor(doc: Document, editor: HTMLElement, text: string) {
  editor.replaceChildren(
    ...text.split("\n").map((line) => {
      const p = doc.createElement("p");
      p.append(line || doc.createElement("br"));
      return p;
    }),
  );
}

interface ToolsOf {
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  refresh(): void;
  ready(anchor: Element): ChatHandlers | null;
  writer: ChatHandlers | null;
  none: string;
  accountId: string | null;
  key: string;
  tipsEnabled?: boolean;
  mobile?: boolean;
}

export function bindTools(doc: Document, editor: HTMLElement, send: HTMLButtonElement, t: ToolsOf): { composer: ReturnType<typeof bindComposer>; unbind(): void } {
  const { draftOf, update, refresh } = t;
  flight.refresh = refresh;
  // Uploads in flight outlive a bind (a State page round trip loads a new frame document).
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };
  const media = { handlers: t.writer, accountId: t.accountId };
  // Every attached audio file is a voice note: OF allows one, and a GIF beside it.
  const audioDone = (file: File) => {
    if (/^audio\//i.test(file.type)) update({ audio: (draftOf().audio ?? 0) + 1 });
  };
  const unbindAddMedia = bindAddMedia(doc, media, draftOf, update, uploading, t.none, undefined, audioDone);
  const taker = mediaTaker(doc, send, media, draftOf, update, uploading, audioDone);
  const take = (files: File[]) => {
    const gif = !!draftOf().giphy_id;
    // With a GIF set only a voice note may join it (OF's rule).
    const ok = gif ? files.filter((f) => /^audio\//i.test(f.type)) : files;
    if (ok.length < files.length) note(doc, send, GIF_ALONE, true);
    if (ok.length) taker(ok);
  };
  const composer = bindComposer(doc, {
    editor,
    draftOf,
    update,
    ready: t.ready,
    blocked: () => (t.writer ? null : t.none),
    take,
    key: t.key,
    tipsEnabled: t.tipsEnabled,
    mobile: t.mobile ?? isMobile(doc.defaultView?.navigator.userAgent ?? ""),
  });
  return {
    composer,
    unbind: () => {
      if (flight.refresh === refresh) flight.refresh = undefined;
      unbindAddMedia();
      composer.unbind();
    },
  };
}

interface DialogTools {
  page: string;
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  back: string;
  ready(anchor: Element): ChatHandlers | null;
  toggleMute(anchor: Element, then?: string): void;
  writer: ChatHandlers | null;
  stay(href: string): string;
}
export type ChatDialog = (doc: Document, ctx: ChatContext, tools: DialogTools) => () => void;

export const bindPrice: ChatDialog = (doc, _ctx, { draftOf, update, back, ready }) => {
  const input = doc.querySelector<HTMLInputElement>(PRICE_INPUT);
  const save = doc.querySelector<HTMLButtonElement>(PRICE_SAVE);
  if (!input || !save) return () => {};
  for (const el of [input, save]) el.setAttribute("data-oi-wired", "");
  const price = draftOf().price;
  if (price) input.value = String(price);
  const sync = () => (save.disabled = readPrice(input.value) === null);
  sync();
  const onInput = (ev: Event) => {
    if (ev.target === input) sync();
  };
  const onClick = (ev: MouseEvent) => {
    if (!(ev.target as Element | null)?.closest?.(PRICE_SAVE)) return;
    ev.preventDefault();
    const h = ready(save);
    if (!h) return;
    const p = readPrice(input.value);
    if (p === null) return note(doc, save, PRICE_NOTE, true);
    update({ price: p || undefined });
    h.navigate(back);
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
};

const VAULT_BAR = "[data-oi-vault-bar]";
const VAULT_ADD = "[data-oi-vault-add]";
const VAULT_CLEAR = "[data-oi-vault-clear]";
function vaultBar(doc: Document, count: number) {
  const grid = doc.querySelector(".modal.show .b-photos")?.closest(".g-sides-gaps") ?? null;
  let bar = doc.querySelector<HTMLElement>(VAULT_BAR);
  if (!count || !grid) return bar?.remove();
  if (!bar) {
    const v = 'data-v-1b24e6ba=""';
    bar = doc.createElement("div");
    bar.setAttribute("data-v-1b24e6ba", "");
    bar.setAttribute("data-oi-vault-bar", "");
    bar.className = "b-placeholder-item-selected m-absolute-position ml-0 mr-0";
    bar.innerHTML =
      `<div ${v} class="b-wrapper-selected"><div ${v} class="b-row-selected"><div ${v} class="b-row-selected__body">` +
      `<button ${v} type="button" at-attr="unselect" aria-label="Clear" data-oi-vault-clear="" data-oi-wired="" class="g-btn m-with-round-hover m-light m-icon m-icon-only m-white m-sm-size">` +
      `<span ${v} class="g-btn m-rounded m-reset-width m-btn-remove m-sm-icon-size m-light m-colored-btn m-mall-auto"><svg class="g-icon" aria-hidden="true"><use href="#icon-close" xlink:href="#icon-close"></use></svg></span></button>` +
      `<div ${v} class="b-row-selected__text g-text-ellipsis"></div></div>` +
      `<div ${v} class="b-row-selected__controls"><button ${v} type="button" data-oi-vault-add="" data-oi-wired="" class="g-btn m-reset-width m-rounded m-sm"> Add </button></div></div></div>`;
    grid.append(bar);
  }
  bar.querySelector(".b-row-selected__text")!.textContent = ` ${count} / ${VAULT_PICK_MAX} Selected `;
}

export const bindVault: ChatDialog = (doc, ctx, { page, draftOf, update, back, ready, writer, stay }) => {
  const view = ctx.vaultView ?? {};
  const tabs = [...doc.querySelectorAll<HTMLElement>(VAULT_TABS)];
  markTypeTabs(tabs, view.type ?? null);
  const store = ctx.storage && ctx.accountId ? { storage: ctx.storage, key: vaultPickKey(ctx.accountId, page, ctx.chat) } : null;
  const pickOf = (): VaultPick => (store ? loadVaultPick(store.storage, store.key) : { ids: [], thumbs: [] });
  const keep = (pick: VaultPick) => {
    if (store) store.storage.setItem(store.key, JSON.stringify(pick));
    vaultBar(doc, pick.ids.length);
  };
  vaultBar(doc, pickOf().ids.length);
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    const tab = target?.closest?.(VAULT_TABS);
    if (tab) {
      ev.preventDefault();
      const type = TYPES[tabs.indexOf(tab as HTMLElement)] ?? null;
      const h = type === (view.type ?? null) ? null : ready(tab);
      if (!h) return;
      return h.navigate(stay(vaultHref({ list: view.list, type }, `/of-manager/${page}`)));
    }
    const add = target?.closest?.(VAULT_ADD);
    if (add) {
      ev.preventDefault();
      const h = ready(add);
      if (!h) return;
      const { ids, thumbs } = pickOf();
      const d = draftOf();
      const fresh = ids.map((id, i) => [id, thumbs[i] ?? ""] as const).filter(([id]) => !d.media_files.includes(id));
      update({ media_files: [...d.media_files, ...fresh.map(([id]) => id)], thumbs: [...d.thumbs, ...fresh.map(([, t]) => t)] });
      keep({ ids: [], thumbs: [] });
      return h.navigate(back);
    }
    if (target?.closest?.(VAULT_CLEAR)) {
      ev.preventDefault();
      doc.querySelectorAll(`${VAULT_TILE}.selected`).forEach((t) => toggleTile(t, false));
      return keep({ ids: [], thumbs: [] });
    }
    const tile = target?.closest?.(VAULT_TILE);
    if (!tile) return;
    const footer = doc.querySelector(".modal-footer a") ?? tile;
    if (!ready(footer)) return;
    const id = Number(tile.getAttribute("data-oi-media"));
    if (!id) return;
    const { ids, thumbs } = pickOf();
    const at = ids.indexOf(id);
    if (at < 0 && draftOf().giphy_id) return note(doc, footer, GIF_ALONE, true);
    if (at < 0 && ids.length >= VAULT_PICK_MAX) return;
    if (at < 0) keep({ ids: [...ids, id], thumbs: [...thumbs, tile.querySelector(".b-photos__item__img")?.getAttribute("src") ?? ""] });
    else keep({ ids: ids.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
    toggleTile(tile, at < 0);
  };
  doc.addEventListener("click", onClick);
  const unbindSearch = bindVaultSearch(doc);
  const unbindTools = bindVaultTools(doc, { vaultView: view, handlers: writer }, page, stay);
  return () => {
    doc.removeEventListener("click", onClick);
    unbindSearch();
    unbindTools();
  };
};

export const bindChatTags: ChatDialog = (doc, ctx, { page, draftOf, update, writer: h, stay }) => {
  const picks = () => draftOf().tags ?? [];
  return bindTags(
    doc,
    { handlers: h && { navigate: h.navigate, toggleTag: h.toggleTag, inviteGuest: h.inviteGuest }, tagItems: ctx.tagItems, tagView: ctx.tagView, storage: null, accountId: null },
    () => {},
    page,
    {
      ids: () => picks().map((t) => t.id),
      toggle: (pick, on) => {
        const others = picks().filter((t) => t.id !== pick.id || t.type !== pick.type);
        update({ tags: on ? [...others, pick] : others });
      },
      href: (view) => stay(tagHref(view, page)),
    },
  );
};
