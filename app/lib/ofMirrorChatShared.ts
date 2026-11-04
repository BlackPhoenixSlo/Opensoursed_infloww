"use client";

/**
 * What a chat's composer (ofMirrorChat) and New message (ofMirrorMass) share: the Chat draft and its tag, the handlers
 * and context a binder gets, the vault pick, the composer's tools (bindTools: Add media, recordings, drops and
 * ofMirrorComposer's tools), the price, vault and tag dialogs, and the editor's helpers. Imports neither half.
 */

import { type TaggedFriendUser, type GiphyItem, type VaultUploadResp } from "@/lib/relay";
import { toggleTile } from "@/lib/ofMirrorDom";
import type { UserList } from "@/lib/ofMirrorDataLists";
import { loadVaultPick, vaultPickKey, type VaultPick } from "@/lib/ofMirrorPick";
import { bindAddMedia, bindTags, bindVaultSearch, bindVaultTools, mediaTaker, tagHref, type TagView } from "@/lib/ofMirrorPost";
import { bindComposer, GIF_ALONE, isMobile } from "@/lib/ofMirrorComposer";
import { markTypeTabs, TYPES, vaultHref, type VaultView } from "@/lib/ofMirrorVault";
import { note } from "@/lib/ofMirrorWrites";
import { MIN_PRICE, PRICE_NOTE } from "@/lib/sendGuards";
// Re-exported: cut into ofMirrorPick, so its importers still read them from here.
export { load, loadVaultPick, vaultPickKey } from "@/lib/ofMirrorPick";

/** The Chat draft (sessionStorage JSON): thumbs[i] is the picture of media_files[i] (vault ids, in click order). */
export interface ChatDraft {
  text: string;
  /** PPV price in dollars; absent: free. */
  price?: number;
  /** Local ISO with offset (localIso), at least a minute ahead when sent. */
  scheduled_date?: string;
  /** Vault ids (picked in the vault dialog) and Add media's upload claims (the Relay's `send_with`), in order. */
  media_files: Array<number | Record<string, unknown>>;
  thumbs: string[];
  /** A message's ⋮ Reply (ofMirrorMessageMenu): the message answered (OF's replyToMessageId) and its text for the line. */
  reply_to?: string;
  reply_text?: string;
  /** The editor's text as OF's markup (ofMirrorFormat), while it holds any formatting; Send sends it as the text. */
  html?: string;
  /** Add GIF's pick: Giphy's id (OF's `giphyId`) and the picture shown under the editor. */
  giphy_id?: string;
  giphy_thumb?: string;
  /** Tag other creators' picks, in click order: a creator ("user"), a guest, or a release form ("link", "document"). */
  tags?: ChatTag[];
  /** How many of media_files are voice notes (OF: one per message; GIF stays possible beside them). */
  audio?: number;
  /** A picked script's (applyScript) vault ids sent unlocked and its locked text, both only with a price. */
  previews?: number[];
  locked_text?: boolean;
}

/** A tag dialog pick: its row's id and type (OF's release-form entity type) and the name the line shows. */
export interface ChatTag {
  id: number;
  type: string;
  name: string;
}

export const EMPTY_MESSAGE = "Write a message or add media";
/** An edited queued message keeps a date or Save for later (without one it would go out at once: that is Message now). */
export const NO_DATE = "Pick a date or Save for Later";
export const UPLOADING = "Wait for the upload to finish";
/** The Relay's edit body (PUT …/queue/{id}) has no GIF. */
export const NO_EDIT_GIF = "An edited message can't carry a GIF";
/** A guest's and a release form's tag types (OF's rfGuest, rfPartner); any other is a creator (rfTag). */
export const FORM_TAGS = ["guest", "link", "document"];

export const EDITOR = "[contenteditable][aria-label='Textbox field']";
export const SEND = "button[at-attr='send_btn']";
const PRICE_INPUT = ".modal.show input[at-attr='input']";
const PRICE_SAVE = ".modal.show .modal-footer button";
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
const VAULT_TABS = ".modal.show .b-tabs__nav__link";
export const SUMMARY = "oi-chat-summary";

/** OF's most media one message takes: its vault dialog's "N / 40 Selected". */
export const VAULT_PICK_MAX = 40;

/** The price field's value in dollars: "" is free (0), else a number of at least MIN_PRICE (a leading "$" allowed); null otherwise. */
export function readPrice(value: string): number | null {
  const s = value.trim().replace(/^\$\s*/, "");
  if (!s) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(s)) return null;
  const n = Number(s);
  return n === 0 || n >= MIN_PRICE ? n : null;
}

export interface ChatHandlers {
  /** POST `path` with `body` for the selected Creator. */
  send(path: string, body: object): Promise<unknown>;
  /** PUT `path` with `body` for the selected Creator (an edited queued message). */
  put?(path: string, body: object): Promise<unknown>;
  /** POST /api/of/v2/upload (multipart, part `file`) for the selected Creator. */
  upload(file: File): Promise<VaultUploadResp>;
  /** Giphy's trending GIFs ("") or a search, through the Relay's OF Giphy proxy. */
  gifs?(query: string): Promise<GiphyItem[]>;
  /** The tag dialog's row More (PATCH /release-forms/toggle-show) and Invite new user (POST /guests). */
  toggleTag?(body: { entity_id: number; entity_type: string }): Promise<unknown>;
  inviteGuest?(name: string): Promise<unknown>;
  mute(on: boolean): Promise<unknown>;
  hide(): Promise<unknown>;
  confirm(text: string): boolean;
  navigate(href: string): void;
}

/** New message's left tabs (OF's /my/chats/send, ?list=exclude, ?list=users). */
export type MassView = "send" | "exclude" | "users";

/** `handlers` null: All-Creators scope. `storage` or `accountId` null: no draft is kept. */
export interface ChatContext {
  handlers: ChatHandlers | null;
  storage: Storage | null;
  accountId: string | null;
  /** ?chat=: the open chat's fan id (null: the example chat). */
  chat: string | null;
  /** The open chat's partner name, mute state and whether they take tips, when the Relay has sent them. */
  fan?: { name: string; muted?: boolean; tipsEnabled?: boolean };
  /** The tag dialog's rows (the Relay's list; undefined while loading, after a failure, or All-Creators) and view. */
  tagItems?: TaggedFriendUser[];
  tagView?: TagView;
  /** A phone or tablet (OF hides Record video there); default: the browser's user agent. */
  mobile?: boolean;
  /** New message: the Creator's user lists (undefined while loading, after a failure, or All-Creators). */
  lists?: UserList[];
  /** New message: why the user lists could not be read (the Relay's text), else undefined. */
  listsError?: string;
  /** New message's left tab, OF's own ?list= (`exclude`, `users`); absent: Send to. */
  massView?: MassView;
  /** New message's Users tab: the Creator's recent chats' fans (undefined while loading or All-Creators). */
  fans?: UserList[];
  /** The vault dialog's view (its ?list= folder and ?type= tab); absent: all media. */
  vaultView?: Partial<VaultView>;
  /** The Agency's time zone (the top bar's): New message's schedule dialog and line show its wall clock. */
  zone?: string;
}

/** Add media's uploads in flight: they outlive a bind (a State page round trip loads a new frame document). */
export const flight: { count: number; refresh?: () => void } = { count: 0 };

/** OF's editor text into `editor`, one <p> per line (an empty line keeps OF's <br>). */
export function setEditor(doc: Document, editor: HTMLElement, text: string) {
  editor.replaceChildren(
    ...text.split("\n").map((line) => {
      const p = doc.createElement("p");
      p.append(line || doc.createElement("br"));
      return p;
    }),
  );
}

/** What a composer's tools work on: its draft (a chat's, or New message's seen as one) and who may write. */
interface ToolsOf {
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  /** Redraw the line under the editor and Send (an upload started or ended). */
  refresh(): void;
  ready(anchor: Element): ChatHandlers | null;
  /** The handlers a tool writes with (an upload), else null and `none` is the note. */
  writer: ChatHandlers | null;
  none: string;
  accountId: string | null;
  /** The draft a recording belongs to (ofMirrorComposer's key). */
  key: string;
  tipsEnabled?: boolean;
  mobile?: boolean;
}

/**
 * A composer's Add media (New post's upload), its recordings and drops (the same upload) and ofMirrorComposer's tools:
 * a chat's and New message's alike. Returns the composer (its `sync` re-applies OF's rules) and an unbind.
 */
export function bindTools(doc: Document, editor: HTMLElement, send: HTMLButtonElement, t: ToolsOf): { composer: ReturnType<typeof bindComposer>; unbind(): void } {
  const { draftOf, update, refresh } = t;
  flight.refresh = refresh;
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };
  const media = { handlers: t.writer, accountId: t.accountId };
  // Every attached audio file (a recording, a drop, an Add media pick) is a voice note: OF allows one, and a GIF beside it.
  const audioDone = (file: File) => {
    if (/^audio\//i.test(file.type)) update({ audio: (draftOf().audio ?? 0) + 1 });
  };
  const unbindAddMedia = bindAddMedia(doc, media, draftOf, update, uploading, t.none, undefined, audioDone);
  // A recording or dropped files: Add media's upload. With a GIF set only a voice note may join it (OF's rule).
  const taker = mediaTaker(doc, send, media, draftOf, update, uploading, audioDone);
  const take = (files: File[]) => {
    const gif = !!draftOf().giphy_id;
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
  /** The dialog's page (messages/chat/state-* or messages/send/state-*). */
  page: string;
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  /** The composer's page (its dialogs return there). */
  back: string;
  ready(anchor: Element): ChatHandlers | null;
  toggleMute(anchor: Element, then?: string): void;
  /** The handlers when a pick may be kept (a chat open, or New message with a model), else null. */
  writer: ChatHandlers | null;
  /** `href` (another view of the dialog) with the composer's own query (a chat's ?chat=). */
  stay(href: string): string;
}
export type ChatDialog = (doc: Document, ctx: ChatContext, tools: DialogTools) => () => void;

/** Message price: the field starts at the draft's price; Save is enabled while the value is valid and keeps it. */
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

/** OF's bar over a vault dialog's grid while tiles are ticked (its scoped CSS is the page's): Clear, the count and Add. */
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

/**
 * Add media from vault, as OF's: a real tile (ofMirrorData's `data-oi-media`) only ticks or unticks it (OF's bar shows the
 * count), Add attaches the ticked vault ids and pictures and goes back, and Close, the backdrop or the bar's Clear attach
 * nothing; a media type tab shows the view's type and a click opens the dialog on that type (the folder, chat and ticks
 * kept); Search media and the folder Search and Sort and media Sort are New post's.
 */
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
    const footer = doc.querySelector(".modal-footer a") ?? tile; // a note in the grid would take a tile's place
    if (!ready(footer)) return;
    const id = Number(tile.getAttribute("data-oi-media"));
    if (!id) return;
    const { ids, thumbs } = pickOf();
    const at = ids.indexOf(id);
    if (at < 0 && draftOf().giphy_id) return note(doc, footer, GIF_ALONE, true); // a GIF goes without vault media
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

/**
 * Tag other creators (state-tag-people): New post's tag dialog (its rows, search, sort, tabs, row More and Invite new
 * user), its picks the draft's `tags`; its views keep the chat.
 */
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
