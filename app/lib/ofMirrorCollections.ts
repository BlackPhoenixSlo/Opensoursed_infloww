"use client";

/**
 * Collections writes (OF Manager > Collections) through the relay, with a single model selected:
 * - The header's + opens OF's "Create new list" dialog (its b-modal__custom-list markup, as the Vault's "Create new
 *   category"; OF's own was not captured) on collections/index and every collections/user-lists page: Save sends
 *   POST /api/of/v2/lists {name}. On Post Labels it is "Create new label" (POST /api/of/v2/labels {name}); on
 *   Bookmarks (a bookmark folder, no relay route) the generator disables it.
 * - The open list's More (collections/user-lists/list?list=<id>, and its Posts tab) opens OF's list menu, its items picked by the list's
 *   own flags as OF does: Rename list (canUpdate; the dialog, PATCH /lists/<id> {name}), Add users (canAddUsers; the
 *   dialog takes @usernames, each looked up with GET /users/<username>, then one POST /lists/users {"<id>": [userIds]}),
 *   Clear list (canManageUsers; confirmed, DELETE /lists/<id>/users) and Delete list (canDelete; confirmed,
 *   DELETE /lists/<id>, then back to Collections).
 * - A user card's Lists button (at-attr add_to_list: the open list's users, on Collections and a list page, or Fans)
 *   opens a menu: "Remove from <the open list>" (DELETE /lists/<id>/users/<userId>) and "Add to <list>" for each other
 *   list that takes users (POST /lists/<other>/users/<userId>).
 * - A user card's name pencil, Discount, Restrict and Add notes (left enabled by the generator; on Collections, a list
 *   page and Fans) are the chat header's tools for that fan (ofMirrorChatTools' fanTools: Rename user, OF's
 *   PERSONAL_OFFER dialog, Restrict / Unrestrict, the notes dialog), the fan read first with GET /users/list?ids=<fan>;
 *   the card then says Unrestrict and Edit notes where they apply, and a write shows OF's toast.
 * - Search users (Collections and a list page: the open list's users) opens a search field under the users column's
 *   header; Enter is the page's ?query= (ofMirrorData sends it as OF's own `query` on GET /lists/<id>/users), an empty
 *   one or Escape drops it. The field stays open while the page searches.
 * The menus are OF's v-menu list markup (as on the State pages), hung under their control. A success shows a grey note
 * and refreshes the model's mirror queries; a failure the red "Could not save: …" (in the dialog, under its field).
 * A More or Lists button with nothing to do (no list, or OF's flags allow nothing) is disabled with NOT_YET. All models:
 * the +, a card's tools and Search users show "Select a model to save changes".
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { LIST_TABS, mirrorQuery, rowsOf, USER_LISTS, usersListPath } from "@/lib/ofMirrorData";
import { afterChatWrite } from "@/lib/ofMirrorKeys";
import { message, note, NOT_YET, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { floatLabel } from "@/lib/ofMirrorSettings";
import { canRename, chatToolWrites, fanTools, field, type FanState, type FanToolsContext, type ToolsMe } from "@/lib/ofMirrorChatTools";
import { wasSubscriber } from "@/lib/fanDiscount";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";

export const CREATE_LIST = "button[aria-label='Create new list']";
export const LIST_MORE = "[at-attr='list_dropdown'] > button";
export const ADD_TO_LIST = "[data-oi-user] button[at-attr='add_to_list']";
/** A user card's chat tools, as the sweep marks them (cardToolOf). */
export const CARD_TOOL = "[data-oi-user] [data-oi-card-tool]";
/**
 * A card's button as one of the chat header's tools (the generator leaves the same ones enabled): the name pencil,
 * Restrict, and the Discount and Add notes tabs. A clone loses the template's data-oi-* marks, so the sweep marks them.
 */
const cardToolOf = (b: Element) =>
  b.matches("[at-attr='name_edit']") ? "rename"
  : b.matches("[at-attr='restrict']") ? "restrict"
  : !b.matches(".b-tabs__nav__link") ? null
  : ({ Discount: "discount", "Add notes": "notes", "Edit notes": "notes" } as Record<string, string>)[b.textContent?.trim() ?? ""] ?? null;
export const USERS_SEARCH = "button[aria-label='Search users']";
export const USERS_SEARCH_ID = "oi-users-search";
const INDEX = "collections/index";
const LIST = "collections/user-lists/list";
const FANS = "collections/user-lists/subscribers/active";
/** Pages whose users column is the open list's users (its Search users is that list's `query`). */
const membersPage = (page: string) => page === INDEX || page === LIST;
/** The dialog's root (OF's modal wrapper). */
export const DIALOG = "[data-oi-dialog]";

/** A user list as GET /lists sends it (OF's own flags decide its menu). */
export interface CollectionList {
  id: number | string;
  name?: string;
  canUpdate?: boolean;
  canDelete?: boolean;
  canAddUsers?: boolean;
  canManageUsers?: boolean;
}

export interface CollectionsHandlers {
  createList(name: string): Promise<unknown>;
  createLabel(name: string): Promise<unknown>;
  renameList(id: string, name: string): Promise<unknown>;
  /** Look the usernames up, add them all in one bulk call; resolves to how many were added. */
  addUsers(id: string, usernames: string[]): Promise<number>;
  clearList(id: string): Promise<unknown>;
  deleteList(id: string): Promise<unknown>;
  addUser(listId: string, userId: string): Promise<unknown>;
  removeUser(listId: string, userId: string): Promise<unknown>;
  /** The shown cards' fans (one GET /users/list?ids=…), to label their tools. */
  cardFans(userIds: string[]): Promise<Record<string, FanState>>;
  /** A user card's fan as the chat tools take it: the fan read again, the Creator, its writes. */
  cardContext(userId: string): Promise<FanToolsContext>;
  navigate(href: string): void;
}

/** Pages whose header + makes a user list (OF: any path but bookmarks and post labels). */
export const listsPage = (page: string) => page === INDEX || page.startsWith("collections/user-lists/");
/** Post Labels, whose + makes a post label. */
export const labelsPage = (page: string) => page.startsWith("collections/post-labels/");
/** Pages with an open list (`?list`, else the first): its users' cards, and (the list page and its Posts tab) its More. */
export const openListPage = (page: string) => page === INDEX || LIST_TABS.includes(page);

/** "@a, b  @c" -> ["a", "b", "c"]: usernames without "@", once each. */
export const usernames = (text: string) => [...new Set(text.split(/[\s,]+/).map((s) => s.replace(/^@/, "")).filter(Boolean))];

const users = (n: number) => `${n} ${n === 1 ? "user" : "users"}`;

/** OF's "Create new category" dialog (the Vault's b-modal__custom-list, captured on vault/state-add-list), as markup. */
const DIALOG_HTML = `<div style="position: absolute; z-index: 1040;" data-oi-dialog="" data-oi-wired=""><div role="dialog" class="modal fade show b-modal__custom-list" style="display: block;" aria-modal="true"><div class="modal-dialog modal-md modal-dialog-centered"><div tabindex="-1" class="modal-content"><header class="modal-header"><h4 class="modal-title"></h4></header><div class="modal-body m-footer-inside-body"><form><div class="modal-body"><div class="g-input__wrapper no-padding"><div data-v-5684fe78="" class="g-input__wrapper input-text-field m-reset-bottom-gap m-empty"><div data-v-5684fe78="" class=""><div data-v-5684fe78="" class="v-input form-control g-input mb-0 theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 0px;"><span class="notranslate">​</span></legend></fieldset><div class="v-text-field__slot"><label class="v-label theme--light" style="left: 0px; right: auto; position: absolute;"></label><input at-attr="input" autocomplete="off" required="required" type="text"></div></div><div class="v-text-field__details"><div class="v-messages theme--light"><div class="v-messages__wrapper"></div></div><div class="v-counter theme--light"></div></div></div></div></div></div></div></div><div class="modal-footer"><a class="g-btn m-flat m-btn-gaps m-reset-width" role="button" href="#"> Cancel </a><button type="submit" disabled="disabled" class="g-btn m-flat m-btn-gaps m-reset-width"> Save </button></div></form></div></div></div></div><div class="modal-backdrop show"></div></div>`;

/** The dialog: `title`, a field labelled `label` (holding `value`, at most `max` characters, or no counter). */
interface Dialog {
  title: string;
  label: string;
  value?: string;
  max?: number;
  placeholder?: string;
  /** Save: the trimmed text; resolves to the success note's text (shown by `anchor`), throws to keep the dialog open. */
  save(text: string): Promise<string>;
  anchor: Element;
}

/** A card's tool's label (its b-tabs__nav__text, OF's spaces around it), set only when it changes (the sweep's observer). */
const setLabel = (el: Element | null, text: string) => {
  const t = el?.querySelector(".b-tabs__nav__text");
  if (t && t.textContent?.trim() !== text) t.textContent = ` ${text} `;
};
const setShown = (el: HTMLElement | null, on: boolean) => {
  if (el && (el.style.display === "none") === on) el.style.display = on ? "" : "none";
};

/** A card's tools as the chat header draws them for `fan`: the pencil, notes and Restrict where OF offers them, labelled. */
function dressCard(card: HTMLElement, fan: FanState) {
  const tool = (name: string) => card.querySelector<HTMLElement>(`[data-oi-card-tool='${name}']`);
  setShown(tool("rename"), canRename(fan));
  const notes = tool("notes");
  setShown(notes, wasSubscriber(fan));
  setLabel(notes, fan.notice ? "Edit notes" : "Add notes");
  const restrict = tool("restrict");
  setShown(restrict, !fan.isBlocked && (!!fan.canRestrict || !!fan.isRestricted));
  setLabel(restrict, fan.isRestricted ? "Unrestrict" : "Restrict");
}

/**
 * Wire the collections controls of the mirrored page `page` in `doc`. `lists`: the model's lists (null: not here yet);
 * `list`: the open list's id (?list=, else the first); `query`: the page's Search users (?query=). `handlers` null: all
 * models. Returns an unbind.
 */
export function bindCollections(
  doc: Document,
  page: string,
  ctx: { lists: CollectionList[] | null; list: string | null; query?: string | null },
  handlers: CollectionsHandlers | null,
): () => void {
  const current = openListPage(page) ? ctx.lists?.find((l) => String(l.id) === ctx.list) : undefined;
  const id = current ? String(current.id) : "";
  const name = current?.name ?? "";
  const others = current || page === FANS ? (ctx.lists ?? []).filter((l) => l.canAddUsers && String(l.id) !== id) : [];
  const canRemove = !!(current?.canManageUsers || current?.canAddUsers);
  const hasMenu = LIST_TABS.includes(page) && !!(current?.canUpdate || current?.canAddUsers || current?.canManageUsers || current?.canDelete);
  const plus = listsPage(page) || labelsPage(page);
  const cardsWired = canRemove || others.length > 0;
  const searchable = membersPage(page);
  const win = doc.defaultView;
  const marked: Element[] = [];
  const mark = (el: Element | null) => {
    if (!el || el.hasAttribute("data-oi-wired")) return;
    el.setAttribute("data-oi-wired", "");
    marked.push(el);
  };
  if (plus) mark(doc.querySelector(CREATE_LIST));
  if (hasMenu) mark(doc.querySelector(LIST_MORE));

  // The controls with nothing to do here: disabled with NOT_YET (cards come and go with the data: swept on each change).
  const off = (el: Element, on: boolean) => {
    if (on && !el.hasAttribute("disabled")) {
      el.setAttribute("disabled", "disabled");
      el.setAttribute("title", NOT_YET);
      el.setAttribute("data-oi-off", "");
    } else if (!on && el.hasAttribute("data-oi-off")) {
      for (const a of ["disabled", "title", "data-oi-off"]) el.removeAttribute(a);
    }
  };
  // The shown cards' fans, their tools labelled from them. Read on every sweep: cardFans is a cached query, so this is
  // a request only once it is stale (a card's write invalidates it, its dialog closing sweeps again).
  let fans: Record<string, FanState> = {};
  let reads = 0;
  const cards = () => [...doc.querySelectorAll<HTMLElement>("[data-oi-user]")];
  const dress = () => {
    for (const c of cards()) if (fans[c.dataset.oiUser!]) dressCard(c, fans[c.dataset.oiUser!]);
  };
  const readFans = () => {
    const ids = [...new Set(cards().map((c) => c.dataset.oiUser!).filter(Boolean))];
    if (!handlers || !ids.length) return;
    const n = ++reads;
    handlers.cardFans(ids).then(
      (out) => {
        if (n !== reads) return; // a later read answers for the cards now shown
        fans = out && !Array.isArray(out) ? out : {}; // OF answers [] when it resolves none
        dress();
      },
      () => {}, // the tools still work: a click reads its fan again
    );
  };
  const sweep = () => {
    for (const el of doc.querySelectorAll(CREATE_LIST)) off(el, !plus && !el.hasAttribute("title"));
    for (const el of doc.querySelectorAll(LIST_MORE)) off(el, !hasMenu);
    for (const el of doc.querySelectorAll("button[at-attr='add_to_list']")) off(el, !cardsWired);
    if (cardsWired) doc.querySelectorAll(ADD_TO_LIST).forEach(mark);
    for (const b of doc.querySelectorAll<HTMLElement>("[data-oi-user] button:not([data-oi-card-tool])")) {
      const t = cardToolOf(b);
      if (t) b.dataset.oiCardTool = t;
    }
    doc.querySelectorAll(CARD_TOOL).forEach(mark);
    if (searchable) mark(doc.querySelector(USERS_SEARCH));
    readFans();
    dress();
  };
  sweep();
  const Observer = win?.MutationObserver ?? (typeof MutationObserver === "undefined" ? undefined : MutationObserver);
  const observer = Observer ? new Observer(sweep) : null;
  observer?.observe(doc.body, { childList: true, subtree: true });

  let open: { menu: HTMLElement; opener: HTMLElement; undo(): void } | null = null;
  const close = () => {
    open?.menu.remove();
    open?.undo();
    open = null;
  };
  let dialog: { root: HTMLElement; anchor: Element; onKey(ev: KeyboardEvent): void } | null = null;
  const closeDialog = () => {
    if (!dialog) return;
    dialog.root.remove();
    dialog.anchor.setAttribute("aria-expanded", "false");
    doc.removeEventListener("keydown", dialog.onKey, true);
    dialog = null;
  };

  /** Hang a menu (OF's v-menu list markup) under `opener`, at its host's right edge or (left) its left edge. */
  const show = (opener: HTMLElement, host: HTMLElement, side: "left" | "right", fill: (list: HTMLElement) => void) => {
    close();
    const menu = doc.createElement("div");
    menu.setAttribute("role", "menu");
    menu.className = `of-state-menu v-menu__content theme--light menuable__content__active${side === "right" ? " m-dropdown-list" : ""}`;
    menu.setAttribute("data-oi-menu", "");
    menu.setAttribute("data-oi-wired", "");
    // OF's own menu width; the State pages' rule hangs it under the host, here from the host's `side` edge.
    menu.style.cssText = "min-width:220px;max-width:256px;width:max-content";
    menu.style.setProperty(side === "right" ? "left" : "right", "auto", "important");
    // --bg-color is transparent inside some hosts (the list kebab): take the page's own background.
    const bg = doc.defaultView?.getComputedStyle(doc.body).backgroundColor;
    if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") menu.style.background = bg;
    const scoped = [...host.attributes].find((a) => a.name.startsWith("data-v-"));
    if (scoped) menu.setAttribute(scoped.name, "");
    const list = doc.createElement("div");
    list.className = "v-list m-dropdown-v-list v-sheet theme--light";
    menu.append(list);
    fill(list);
    const wrapper = host.classList.contains("b-dropdown-wrapper");
    const position = host.style.position;
    if (wrapper) host.classList.add("m-show-dropdown");
    else host.style.position = "relative";
    // A sticky page header paints under the tabs after it: lift it while its menu is open.
    const header = host.closest<HTMLElement>(".g-page__header");
    const z = header?.style.zIndex ?? "";
    if (header) header.style.zIndex = "20";
    opener.setAttribute("aria-expanded", "true");
    host.append(menu);
    open = {
      menu,
      opener,
      undo: () => {
        if (wrapper) host.classList.remove("m-show-dropdown");
        else host.style.position = position;
        if (header) header.style.zIndex = z;
        opener.setAttribute("aria-expanded", "false");
      },
    };
  };

  const item = (list: HTMLElement, label: string, run: () => void, danger = false) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.setAttribute("data-oi-wired", "");
    b.className = `v-list-item v-list-item--link theme--light m-with-rectangle-hover m-tb-sm${danger ? " m-danger" : ""}`;
    b.textContent = label;
    b.addEventListener("click", (ev) => {
      ev.preventDefault();
      run();
    });
    list.append(b);
  };

  /** Open OF's dialog for `d`: Save (or Enter) sends; Cancel, Escape or the backdrop close it. */
  const ask = (d: Dialog) => {
    close();
    closeDialog();
    const box = doc.createElement("div");
    box.innerHTML = DIALOG_HTML;
    const root = box.firstElementChild as HTMLElement;
    const q = <T extends Element>(sel: string) => root.querySelector<T>(sel)!;
    q(".modal-title").textContent = ` ${d.title} `;
    q(".v-label").textContent = d.label;
    const input = q<HTMLInputElement>("input");
    const save = q<HTMLButtonElement>("button[type=submit]");
    const counter = q<HTMLElement>(".v-counter");
    const messages = q<HTMLElement>(".v-messages__wrapper");
    const field = q<HTMLElement>(".v-input");
    const wrap = q<HTMLElement>(".input-text-field");
    if (d.placeholder) input.placeholder = d.placeholder;
    if (d.max) input.maxLength = d.max;
    else counter.remove();
    const initial = d.value ?? "";
    input.value = initial;
    const update = () => {
      const filled = !!input.value || doc.activeElement === input;
      floatLabel(input, filled);
      wrap.classList.toggle("m-empty", !input.value);
      if (d.max) counter.textContent = `${input.value.length} / ${d.max}`;
      const text = input.value.trim();
      save.disabled = !text || text === initial.trim();
    };
    const fail = (text: string | null) => {
      messages.replaceChildren();
      field.classList.toggle("error--text", !!text);
      field.classList.toggle("v-input--has-state", !!text);
      if (!text) return;
      const m = doc.createElement("div");
      m.className = "v-messages__message";
      m.textContent = text;
      messages.append(m);
      messages.parentElement!.classList.add("error--text");
    };
    input.addEventListener("input", () => {
      fail(null);
      update();
    });
    input.addEventListener("focus", () => field.classList.add("v-input--is-focused", "primary--text"));
    input.addEventListener("blur", () => {
      field.classList.remove("v-input--is-focused", "primary--text");
      update();
    });
    q<HTMLElement>(".modal-footer a").addEventListener("click", (ev) => {
      ev.preventDefault();
      closeDialog();
    });
    const modal = q<HTMLElement>(".modal");
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) closeDialog();
    });
    q<HTMLFormElement>("form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const text = input.value.trim();
      if (!text || save.disabled) return;
      save.disabled = true;
      d.save(text).then(
        (ok) => {
          closeDialog();
          note(doc, d.anchor, ok, false, 2000);
        },
        (e) => {
          fail(`Could not save: ${message(e)}`);
          update();
        },
      );
    });
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") closeDialog();
    };
    doc.addEventListener("keydown", onKey, true);
    doc.body.append(root);
    // Its opener shows it open (as a menu's does), until it closes.
    d.anchor.setAttribute("aria-expanded", "true");
    dialog = { root, anchor: d.anchor, onKey };
    input.focus();
    update();
  };

  /** Send `write`; on success close the menu and note `ok` by `anchor`, on failure the red note. */
  const run = (write: Promise<unknown>, anchor: Element, ok: string) =>
    write.then(
      () => {
        close();
        note(doc, anchor, ok, false, 2000);
      },
      (e) => note(doc, anchor, `Could not save: ${message(e)}`, true),
    );

  const onPlus = (opener: HTMLElement, h: CollectionsHandlers) =>
    labelsPage(page)
      ? ask({ title: "Create new label", label: "Label name", max: 64, anchor: opener, save: (t) => h.createLabel(t).then(() => "Label created") })
      : ask({ title: "Create new list", label: "List name", max: 64, anchor: opener, save: (t) => h.createList(t).then(() => "List created") });

  const onMore = (opener: HTMLElement, h: CollectionsHandlers) =>
    show(opener, opener.closest<HTMLElement>(".b-dropdown-wrapper") ?? opener.parentElement!, "right", (list) => {
      if (current!.canUpdate)
        item(list, "Rename list", () =>
          ask({ title: "Rename list", label: "List name", value: name, max: 64, anchor: opener, save: (t) => h.renameList(id, t).then(() => "Saved") }),
        );
      if (current!.canAddUsers)
        item(list, "Add users", () =>
          ask({
            title: "Add users",
            label: "Usernames",
            placeholder: "@username, @username",
            anchor: opener,
            save: async (t) => `Added ${users(await h.addUsers(id, usernames(t)))}`,
          }),
        );
      if ((current!.canUpdate || current!.canAddUsers) && (current!.canManageUsers || current!.canDelete)) {
        const hr = doc.createElement("hr");
        hr.className = "v-divider theme--light";
        hr.setAttribute("role", "separator");
        list.append(hr);
      }
      if (current!.canManageUsers)
        item(
          list,
          "Clear list",
          () => {
            close();
            if (win?.confirm(`Remove every user from "${name}"? The list stays.`)) run(h.clearList(id), opener, "List cleared");
          },
          true,
        );
      if (current!.canDelete)
        item(
          list,
          "Delete list",
          () => {
            close();
            if (!win?.confirm(`Delete the list "${name}"? This cannot be undone.`)) return;
            h.deleteList(id).then(
              () => h.navigate("/of-manager/collections"),
              (e) => note(doc, opener, `Could not delete: ${message(e)}`, true),
            );
          },
          true,
        );
    });

  const onCard = (opener: HTMLElement, h: CollectionsHandlers) => {
    const uid = opener.closest<HTMLElement>("[data-oi-user]")!.dataset.oiUser!;
    show(opener, opener.closest<HTMLElement>(".b-list-titles") ?? opener.parentElement!, "left", (list) => {
      if (canRemove) item(list, `Remove from ${name}`, () => run(h.removeUser(id, uid), opener, "Removed"), true);
      for (const l of others) item(list, `Add to ${l.name ?? l.id}`, () => run(h.addUser(String(l.id), uid), opener, `Added to ${l.name ?? l.id}`));
    });
  };

  /** A card's tool: its fan read again, then the chat header's tool for it (its write invalidating the fans, the next sweep labels the cards again). */
  const onCardTool = (opener: HTMLElement, h: CollectionsHandlers) => {
    const uid = opener.closest<HTMLElement>("[data-oi-user]")!.dataset.oiUser!;
    const tool = opener.dataset.oiCardTool;
    opener.setAttribute("aria-busy", "true");
    h.cardContext(uid).then(
      (c) => {
        opener.removeAttribute("aria-busy");
        if (c.fan) {
          fans = { ...fans, [uid]: c.fan };
          dress();
        }
        const t = fanTools(doc, c, null);
        if (tool === "rename") t.rename(opener);
        else if (tool === "notes") t.editNotes(opener);
        else if (tool === "discount") t.discount(opener);
        else if (tool === "restrict") t.restrict(opener);
      },
      (e) => {
        opener.removeAttribute("aria-busy");
        note(doc, opener, `Could not load this user: ${message(e)}`, true);
      },
    );
  };

  // ---- Search users: a field under the users column's header; Enter searches (?query=), empty or Escape stops.
  const searchHref = (q: string) => {
    const params = new URLSearchParams();
    if (id) params.set("list", id);
    if (q) params.set("query", q);
    const s = params.toString();
    return `/of-manager/${page === INDEX ? "collections" : LIST}${s ? `?${s}` : ""}`;
  };
  const closeSearch = () => {
    doc.getElementById(USERS_SEARCH_ID)?.remove();
    doc.querySelector(USERS_SEARCH)?.setAttribute("aria-expanded", "false");
  };
  const openSearch = (opener: HTMLElement, h: CollectionsHandlers, focus: boolean) => {
    const header = opener.closest(".b-content-filter");
    if (!header || doc.getElementById(USERS_SEARCH_ID)) return;
    const { row, input } = field(doc, "Search users", ctx.query ?? "");
    row.id = USERS_SEARCH_ID;
    row.setAttribute("data-oi-wired", "");
    row.style.cssText = "padding:0 0 12px";
    input.setAttribute("data-oi-wired", "");
    input.setAttribute("enterkeyhint", "search");
    input.addEventListener("keydown", (ev) => {
      const e = ev as KeyboardEvent;
      if (e.key !== "Enter" && e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      const q = e.key === "Enter" ? input.value.trim() : "";
      if (!q) closeSearch();
      if (q !== (ctx.query ?? "")) h.navigate(searchHref(q));
    });
    header.after(row);
    opener.setAttribute("aria-expanded", "true");
    if (focus) input.focus();
  };
  const searchBtn = searchable ? doc.querySelector<HTMLElement>(USERS_SEARCH) : null;
  if (searchBtn && handlers && ctx.query) openSearch(searchBtn, handlers, false);

  // Capture phase: ahead of bindWrites' click fallback, so a card's Lists button is marked before the fallback looks.
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (open && !open.menu.contains(t) && !open.opener.contains(t)) close();
    if (t.closest("[data-oi-menu]") || t.closest(DIALOG) || t.closest(`#${USERS_SEARCH_ID}`)) return; // their own handlers
    const tool = t.closest<HTMLElement>(CARD_TOOL);
    const search = searchable ? t.closest<HTMLElement>(USERS_SEARCH) : null;
    if (tool || search) {
      const el = (tool ?? search)!;
      mark(el);
      ev.preventDefault();
      ev.stopPropagation();
      if (!handlers) return note(doc, el, SELECT_MODEL);
      if (tool) return onCardTool(tool, handlers);
      if (!doc.getElementById(USERS_SEARCH_ID)) return openSearch(el, handlers, true);
      closeSearch();
      if (ctx.query) handlers.navigate(searchHref(""));
      return;
    }
    const create = plus ? t.closest<HTMLElement>(CREATE_LIST) : null;
    const more = hasMenu ? t.closest<HTMLElement>(LIST_MORE) : null;
    const card = cardsWired ? t.closest<HTMLElement>(ADD_TO_LIST) : null;
    const opener = create ?? more ?? card;
    if (!opener) return;
    mark(opener);
    ev.preventDefault();
    if (!handlers) return note(doc, opener, SELECT_MODEL);
    if (open?.opener === opener) return close();
    if (create) onPlus(create, handlers);
    else if (more) onMore(more, handlers);
    else onCard(opener, handlers);
  };

  doc.addEventListener("click", onClick, true);
  return () => {
    doc.removeEventListener("click", onClick, true);
    observer?.disconnect();
    close();
    closeDialog();
    closeSearch();
    for (const el of marked) el.removeAttribute("data-oi-wired");
    for (const el of doc.querySelectorAll("[data-oi-off]")) off(el, false);
  };
}

/** Every collections page: bind its writes on every frame load (writes only with a single model selected). */
export function useOfCollections(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const params = useSearchParams();
  const asked = params.get("list");
  const query = params.get("query");
  const qc = useQueryClient();
  const router = useRouter();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  // The same query (key and fetch) as useOfData's user lists: one request, one cache.
  const lists = useQuery(mirrorQuery(accountId, USER_LISTS, openListPage(page) || page === FANS));
  // The open list as useOfData picks it: ?list, else the first.
  const first = rowsOf<CollectionList>(lists.data)?.[0]?.id;
  const list = asked ?? (openListPage(page) && first != null ? String(first) : null);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page.startsWith("collections/")) return;
    const ctx = { accountId };
    // A write changes the lists and their users: every mirror query of this model is fetched again.
    // A list's users are also Messages' folder tabs (GET /chats?list_id=): Messages Pro's chat lists are fetched again too.
    const refresh = <T,>(p: Promise<T>) =>
      p.then((out) => (void afterChatWrite(qc, accountId), out));
    const handlers: CollectionsHandlers | null = accountId
      ? {
          createList: (name) => refresh(relay.post("/api/of/v2/lists", { name }, ctx)),
          createLabel: (name) => refresh(relay.post("/api/of/v2/labels", { name }, ctx)),
          renameList: (id, name) => refresh(relay.patch(`/api/of/v2/lists/${encodeURIComponent(id)}`, { name }, ctx)),
          addUsers: (id, names) =>
            refresh(
              (async () => {
                const found = await Promise.all(names.map((n) => relay.get<{ id?: number | string }>(`/api/of/v2/users/${encodeURIComponent(n)}`, ctx)));
                const ids = found.map((u, i) => {
                  if (u?.id == null) throw new Error(`@${names[i]} not found`);
                  return Number(u.id);
                });
                const out = await relay.post<Record<string, (number | string)[]>>("/api/of/v2/lists/users", { [id]: ids }, ctx);
                // OF's own check: every id sent comes back under the list's key.
                const now = (out?.[id] ?? []).map(Number);
                if (!ids.every((u) => now.includes(u))) throw new Error("OnlyFans did not add every user");
                return ids.length;
              })(),
            ),
          clearList: (id) => refresh(relay.delete(`/api/of/v2/lists/${encodeURIComponent(id)}/users`, ctx)),
          deleteList: (id) => refresh(relay.delete(`/api/of/v2/lists/${encodeURIComponent(id)}`, ctx)),
          addUser: (l, u) => refresh(relay.post(`/api/of/v2/lists/${encodeURIComponent(l)}/users/${encodeURIComponent(u)}`, undefined, ctx)),
          removeUser: (l, u) => refresh(relay.delete(`/api/of/v2/lists/${encodeURIComponent(l)}/users/${encodeURIComponent(u)}`, ctx)),
          // The chat header's reads: the fans (as useOfChatTools reads one, a write's refresh fetching them again) and the Creator.
          cardFans: (ids) => qc.fetchQuery(mirrorQuery<Record<string, FanState>>(accountId, usersListPath(ids), true)),
          cardContext: async (uid) => {
            const [users, me] = await Promise.all([
              qc.fetchQuery({ ...mirrorQuery<Record<string, FanState>>(accountId, usersListPath([uid]), true), staleTime: 0 }),
              qc.fetchQuery(ofMeQuery(accountId)) as Promise<ToolsMe>,
            ]);
            return {
              chat: uid,
              fan: users && !Array.isArray(users) ? users[uid] : undefined,
              me,
              writes: chatToolWrites(accountId, uid, qc),
            };
          },
          navigate: (href) => router.push(href),
        }
      : null;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindCollections(doc, page, { lists: accountId ? (rowsOf<CollectionList>(lists.data) ?? null) : null, list, query }, handlers) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, accountId, list, query, lists.data, qc, router]);
}
