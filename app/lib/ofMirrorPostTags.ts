"use client";

/**
 * The New post composer's tag and labels dialogs: OF's checkbox rows (applyTagRows, applyLabelRows), the tag dialog's
 * view in the app URL (TagView, tagViewOf, tagHref, tagsRoute) and its tools (bindTags, tagViewClick, tagRowMenu), and
 * ADD LABELS (bindLabels, sortLabelRows). ofMirrorPost re-exports its public names.
 */

import { toChoice, type TaggedFriendUser } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { avatarOf } from "@/lib/ofMirrorAvatar";
import { fill, make, own, plain } from "@/lib/ofMirrorData";
import { closeMenu, ORDER_GROUP, showMenu, type MenuGroup } from "@/lib/ofMirrorMenu";
import { message, note, READ_ONLY, SELECT_MODEL } from "@/lib/ofMirrorWrites";
import { toast } from "@/lib/ofMirrorToast";
import { draftOf, type PostContext, type PostDraft, type PostHandlers } from "@/lib/ofMirrorPostDraft";

/** A post label as GET /api/of/v2/labels gives it (OF's `{list, hasMore}`, or a bare array). */
export interface PostLabel {
  id: number;
  name: string;
  postsCount?: number;
}
export type PostLabelsResp = { list?: PostLabel[]; hasMore?: boolean } | PostLabel[];
export const labelsOf = (r: PostLabelsResp): PostLabel[] => (Array.isArray(r) ? r : (r.list ?? []));
/** The labels a post can be given: the Creator's own (numeric ids); OF's Archive and Private Archive are not offered. */
export const postLabelsOf = (r: PostLabelsResp): PostLabel[] => labelsOf(r).filter((l) => Number.isInteger(Number(l.id)));

/** OF's checkbox list row (the tag and labels dialogs). */
export const LIST_ROW = "label.b-rows-lists__item";
/** The Relay list the tag dialog shows, and the labels dialog's NEW LABEL button. */
const TAGS = "/api/of/v2/posts/tagged-friend-users?limit=50&offset=0";
const NEW_LABEL = ".b-rows-lists__modal__add-list-btn";

/**
 * The tag dialog's rows for `items`: the examples hidden and the first one cloned per item (`data-oi-user="<id>"`,
 * its name and @username, checked when the id is `picked`). An empty list hides all rows. ofMirrorData's restore undoes it.
 * Only the open dialog's rows: the page behind may hold its own (New message's Send to lists).
 */
export function applyTagRows(doc: Document, items: TaggedFriendUser[], picked: number[], img?: (u: string) => string): void {
  const examples = [...(doc.querySelector(".modal.show") ?? doc).querySelectorAll<HTMLElement>(`${LIST_ROW}:not([data-oi-user])`)];
  if (!examples.length) return;
  const rows = items.map((item) => {
    const { id, name: label, username } = toChoice(item);
    const row = make(examples[0]);
    row.setAttribute("data-oi-user", String(id));
    // Its More menu's hide (OF's toggle-show takes the list entry's own id and type).
    row.setAttribute("data-oi-entity", String(item.id));
    row.setAttribute("data-oi-type", item.type ?? "user");
    if ((item.user as { hiddenForRf?: boolean } | undefined)?.hiddenForRf) row.setAttribute("data-oi-hidden", "");
    row.setAttribute("data-oi-wired", "");
    const box = row.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (box) box.checked = picked.includes(id);
    // OF sends names HTML-escaped ("&amp;"); its row shows the text.
    const name = row.querySelector(".b-rows-lists__item__name");
    if (name) name.textContent = ` ${plain(label)} `;
    // OF's avatar: the picture, else the initials (the example's is a grey placeholder picture).
    const user = item.user ?? { id, name: label, username };
    row.querySelector(".b-rows-lists__item__icon .g-avatar")?.replaceWith(avatarOf(doc, { ...user, name: plain(user.name ?? label) }, 36, img, "m-border-line m-absolute m-valign-center"));
    // the subline keeps one of OF's items, the @username ("Verified" and the rest dropped)
    const thumbs = row.querySelector(".b-content-inside-thumbs");
    const handle = thumbs?.lastElementChild;
    if (handle) handle.textContent = username ? ` @${username} ` : "";
    thumbs?.replaceChildren(...(handle ? [handle] : []));
    return row;
  });
  fill(doc, examples, rows);
}

/** OF's icon-release-form (its sprite's symbol; the captured tag dialog's cut-down sprite lacks it). */
const ICON_RELEASE_FORM =
  "M17,21H7c-2.21,0-4-1.79-4-4V7c0-2.21,1.79-4,4-4h6.88c.66,0,1.3,.27,1.77,.73l4.62,4.62c.47,.47,.73,1.11,.73,1.77v6.88c0,2.21-1.79,4-4,4Zm-2-15.09v3.09h3.09l-3.09-3.09Zm4,5.09h-5c-.55,0-1-.45-1-1V5H7c-1.1,0-2,.9-2,2v10c0,1.1,.9,2,2,2h10c1.1,0,2-.9,2-2v-6Zm-4,4h-6c-.55,0-1-.45-1-1s.45-1,1-1h6c.55,0,1,.45,1,1s-.45,1-1,1Zm-4.5-4h-1.5c-.55,0-1-.45-1-1s.45-1,1-1h1.5c.55,0,1,.45,1,1s-.45,1-1,1Z";
/** OF's English texts (texts_en.json) for the Release form tab's empty placeholder: message.no_rf_yet, and the
 * EmptyPlaceholder's default message.nothing_found_message while searching. */
export const NO_RELEASE_FORMS = "No release forms yet";
export const NOTHING_FOUND = "Nothing found";

/**
 * The tag dialog's Release form tab with no forms, as OF's DocsAndLinks (chunk 44328) in a modal (or the Release forms
 * page's, with no dialog open): the list's column becomes `d-flex flex-column flex-fill` (no scrollbar) and shows OF's
 * EmptyPlaceholder, the release-form icon (`m-md-size mb-1`) over "No release forms yet"; while searching the search icon
 * over "Nothing found". Returns its undo.
 */
export function applyFormsEmpty(doc: Document, searching: boolean): () => void {
  const docs = (doc.querySelector(".modal.show") ?? doc).querySelector<HTMLElement>(".b-release-form__docs");
  if (!docs) return () => {};
  const was = docs.className;
  docs.classList.remove("m-native-custom-scrollbar", "m-scrollbar-y", "m-invisible-scrollbar");
  docs.classList.add("d-flex", "flex-column", "flex-fill");
  const empty = doc.createElement("div");
  empty.className = "empty-message";
  empty.setAttribute("data-oi-empty", "");
  const icon = searching ? "icon-search" : "icon-release-form";
  const shape = searching ? `<use href="#icon-search" xlink:href="#icon-search"></use>` : `<path d="${ICON_RELEASE_FORM}"></path>`;
  empty.innerHTML = `<svg class="m-md-size mb-1 g-icon" data-icon-name="${icon}" aria-hidden="true" viewBox="0 0 24 24">${shape}</svg><span></span>`;
  empty.querySelector("span")!.textContent = searching ? NOTHING_FOUND : NO_RELEASE_FORMS;
  docs.append(empty);
  return () => {
    empty.remove();
    docs.className = was;
  };
}

/**
 * The labels dialog's rows for `items`: the examples hidden and the first one cloned per label (`data-oi-label="<id>"`,
 * its name and post count, no pictures, checked when the id is `picked`). An empty list hides all rows. ofMirrorData's
 * restore undoes it.
 */
export function applyLabelRows(doc: Document, items: PostLabel[], picked: number[]): void {
  const examples = [...doc.querySelectorAll<HTMLElement>(`${LIST_ROW}:not([data-oi-label])`)];
  if (!examples.length) return;
  const rows = items.map(({ id, name: label, postsCount }) => {
    const row = make(examples[0]);
    row.setAttribute("data-oi-label", String(id));
    row.setAttribute("data-oi-wired", "");
    const box = row.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (box) box.checked = picked.includes(id);
    const name = row.querySelector(".b-rows-lists__item__name");
    if (name) name.textContent = ` ${label} `;
    row.querySelector(".b-media-set")?.remove();
    const count = row.querySelector(".b-content-inside-thumbs__item");
    if (count) count.textContent = ` ${postsCount ?? 0} posts `;
    return row;
  });
  fill(doc, examples, rows);
}

/** The tag dialog's view (the app URL's ?tab= ?q= ?sort= ?order= ?filter=; OF's releaseForms fetch params). */
export interface TagView {
  tab: "users" | "forms";
  q: string | null;
  sort: "date" | "name";
  order: "asc" | "desc";
  filter: "all" | "pending";
}
export function tagViewOf(params: { get(k: string): string | null }): TagView {
  return {
    tab: params.get("tab") === "forms" ? "forms" : "users",
    q: params.get("q")?.trim() || null,
    sort: params.get("sort") === "name" ? "name" : "date",
    order: params.get("order") === "asc" ? "asc" : "desc",
    filter: params.get("filter") === "pending" ? "pending" : "all",
  };
}
/** The tag dialog's page with `view` (OF's defaults left out). */
export function tagHref(view: TagView, page: string): string {
  const q = new URLSearchParams();
  if (view.tab === "forms") q.set("tab", "forms");
  if (view.q) q.set("q", view.q);
  if (view.sort !== "date") q.set("sort", view.sort);
  if (view.order !== "desc") q.set("order", view.order);
  if (view.filter !== "all") q.set("filter", view.filter);
  const qs = q.toString();
  return `/of-manager/${page}${qs ? `?${qs}` : ""}`;
}
/**
 * The relay read for the tag dialog's rows: the Tag user tab is OF's tagged-friend-users (its `name` search: the relay's
 * `search`), the Release form tab OF's release-forms, both with OF's `sort` "<date|name>:<asc|desc>" and `filter`.
 */
export function tagsRoute(view: TagView): string {
  const q = new URLSearchParams({ limit: "50", offset: "0" });
  const plain = view.tab === "users" && !view.q && view.sort === "date" && view.order === "desc" && view.filter === "all";
  if (plain) return TAGS;
  q.set("sort", `${view.sort}:${view.order}`);
  q.set("filter", view.filter);
  if (view.q) q.set(view.tab === "users" ? "search" : "name", view.q);
  return `${view.tab === "users" ? "/api/of/v2/posts/tagged-friend-users" : "/api/of/v2/release-forms"}?${q}`;
}

/** What the tag dialog reads: the Relay's rows, its view, the draft's place, and the handlers its tools use. */
export type TagContext = Pick<PostContext, "tagItems" | "tagView" | "storage" | "accountId" | "draftId"> & {
  handlers: Pick<PostHandlers, "navigate" | "toggleTag" | "inviteGuest"> | null;
};
/** A tag dialog's picks kept elsewhere than New post's draft (a chat's): the picked ids, a row's toggle, the dialog's href for a view. */
export interface TagPicks {
  ids(): number[];
  toggle(pick: { id: number; type: string; name: string }, on: boolean): void;
  href(view: TagView): string;
}

/**
 * Wire the tag dialog (new-post/state-tag-people): its rows are the Relay's list with a single Creator, else none (the
 * captured examples never show: All-Creators, loading, a failure); a row's change toggles its id in the draft's Co-tags
 * (operator order, no duplicates). OF's own tools, for the view in the app URL (TagView, tagsRoute):
 * - the header's search icon opens a search field (OF's `name` search; typing stops for 400 ms: the dialog with ?q=);
 * - Sort: OF's menu (All / Pending, Recent / Name, Ascending / Descending), a pick opens the dialog sorted so;
 * - the Tag user / Release form tabs: the Release form tab lists OF's release forms (GET /release-forms), as rows to tag;
 *   none: OF's empty placeholder (applyFormsEmpty);
 * - a row's More: "Hide from list" (or "Show in list" for a hidden one) sends OF's toggle-show, then OF's toast;
 * - Invite new user: a name field and Save (POST /guests {name}); OF answers with the guest.
 * All-Creators: each says "Select a model". Returns an unbind, which puts the examples back.
 */
export function bindTags(doc: Document, ctx: TagContext, update: (patch: Partial<PostDraft>) => void, page: string, picks?: TagPicks): () => void {
  const { handlers, tagItems } = ctx;
  const view = ctx.tagView ?? tagViewOf(new URLSearchParams());
  const picked = () => (picks ? picks.ids() : draftOf(ctx).tagged_users);
  // Kept apart from ofMirrorData's restore: over Home, the feed's data re-applies (and this unbind leaves it alone).
  const undo = own(() => applyTagRows(doc, (handlers && tagItems) || [], picked(), (u) => proxyImage(u, ctx.accountId)));
  // The Release form tab's list came back empty: OF's placeholder (nothing while loading, after a failure, All-Creators).
  const undoEmpty = view.tab === "forms" && handlers && tagItems && !tagItems.length ? applyFormsEmpty(doc, !!view.q) : () => {};
  const modal = doc.querySelector<HTMLElement>(".modal.show");
  const header = modal?.querySelector<HTMLElement>(".modal-header");
  const sortBtn = modal?.querySelector<HTMLButtonElement>("button[aria-label='Sort']");
  // OF's search icon: the header's first round button (no label).
  const searchBtn = header?.querySelector<HTMLButtonElement>("button.g-btn.m-icon.m-icon-only:not([aria-label])");
  const tabs = [...(modal?.querySelectorAll<HTMLElement>(".b-tabs__nav__link") ?? [])];
  markTagTabs(tabs, view);
  const invite = [...(modal?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find((b) => b.textContent?.trim() === "Invite new user") ?? null;
  for (const el of [sortBtn, searchBtn, invite, ...doc.querySelectorAll(`${LIST_ROW} .m-btn-vertical-dots`)]) el?.setAttribute("data-oi-wired", "");
  const go = (next: TagView) => handlers?.navigate(picks ? picks.href(next) : tagHref(next, page));

  // The search field (OF's header search): open while the view has a query, or once the icon is clicked.
  let field: HTMLInputElement | null = null;
  let timer = 0;
  const title = header?.querySelector<HTMLElement>(".modal-title, h4");
  const openSearch = () => {
    if (field || !header) return field?.focus();
    field = doc.createElement("input");
    field.type = "search";
    field.maxLength = 100;
    field.placeholder = "Search...";
    field.setAttribute("aria-label", "Search creators");
    field.className = "b-search-form__input form-control";
    field.style.cssText = "flex:1;min-width:0;margin:0 8px;height:32px";
    field.value = view.q ?? "";
    field.setAttribute("data-oi-wired", "");
    field.id = "oi-tag-search";
    // OF's open search form takes the title's place.
    if (title) title.style.display = "none";
    (searchBtn ?? header.lastElementChild)?.before(field);
    field.addEventListener("input", () => {
      doc.defaultView?.clearTimeout(timer);
      timer = doc.defaultView?.setTimeout(() => go({ ...view, q: field?.value.trim() || null }), 400) ?? 0;
    });
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  };
  if (view.q && handlers) openSearch();

  const form = invite ? newLabelForm(doc, invite, "Name") : null;
  const openInvite = (on: boolean) => {
    if (!invite || !form) return;
    invite.style.display = on ? "none" : "";
    form.root.style.display = on ? "flex" : "none";
    form.input.value = "";
    form.save.disabled = true;
    if (on) form.input.focus();
  };
  const sendInvite = () => {
    const name = form?.input.value.trim();
    if (!handlers?.inviteGuest || !form || !name || form.save.disabled) return;
    form.save.disabled = true;
    handlers.inviteGuest(name).then(
      () => {
        openInvite(false);
        toast(doc, `${name} is invited`);
      },
      (e) => {
        form.save.disabled = false;
        note(doc, form.save, `Could not invite: ${message(e)}`, true);
      },
    );
  };

  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement;
    const row = box.closest?.<HTMLElement>(LIST_ROW);
    const id = Number(row?.getAttribute("data-oi-user"));
    if (!handlers || !id) return;
    if (picks) return picks.toggle({ id, type: row!.getAttribute("data-oi-type") ?? "user", name: row!.querySelector(".b-rows-lists__item__name")?.textContent?.trim() ?? "" }, box.checked);
    const others = draftOf(ctx).tagged_users.filter((t) => t !== id);
    update({ tagged_users: box.checked ? [...others, id] : others });
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (tagViewClick(doc, ev, { tabs, sortBtn, view, on: !!handlers, go })) return;
    if (searchBtn && t.closest("button") === searchBtn) {
      ev.preventDefault();
      return handlers ? openSearch() : note(doc, searchBtn, SELECT_MODEL);
    }
    const dots = t.closest<HTMLButtonElement>(`${LIST_ROW} .m-btn-vertical-dots`);
    if (dots) {
      ev.preventDefault();
      ev.stopPropagation();
      return tagRowMenu(doc, dots, handlers);
    }
    if (invite && form) {
      if (t.closest("button") === invite) {
        ev.preventDefault();
        return handlers ? openInvite(true) : note(doc, invite, SELECT_MODEL);
      }
      if (t.closest("[data-oi-cancel]") === form.cancel) {
        ev.preventDefault();
        return openInvite(false);
      }
      if (t.closest("[data-oi-save]") === form.save) {
        ev.preventDefault();
        sendInvite();
      }
    }
  };
  const onInput = (ev: Event) => {
    if (form && ev.target === form.input) form.save.disabled = !form.input.value.trim();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (form && ev.target === form.input && ev.key === "Enter") {
      ev.preventDefault();
      sendInvite();
    }
    if (field && ev.target === field && ev.key === "Enter") ev.preventDefault();
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("keydown", onKey);
  return () => {
    doc.defaultView?.clearTimeout(timer);
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("keydown", onKey);
    field?.remove();
    if (title) title.style.display = "";
    form?.root.remove();
    if (invite) invite.style.display = "";
    closeMenu(doc);
    undoEmpty();
    undo();
  };
}

/** The tag lists' sorts (OF's `sort`), as their Sort menu and filter title word them. */
export const TAG_SORT_LABELS: Record<TagView["sort"], string> = { date: "Recent", name: "Name" };
/** A tag list's tab (the tag dialog's, Release forms'): Release form lists OF's release forms, any other OF's users. */
const tagTabOf = (t: Element): TagView["tab"] => (t.textContent?.trim() === "Release form" ? "forms" : "users");

/** The tag list's tabs `tabs` for `view`: its tab current (OF's m-current, not clickable), each Wired. */
export function markTagTabs(tabs: Element[], view: TagView): void {
  for (const t of tabs) {
    const on = tagTabOf(t) === view.tab;
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    t.setAttribute("data-oi-wired", "");
  }
}

/**
 * A click on a tag list's view tools: one of `tabs` opens the list on that tab; `sortBtn` opens OF's Sort menu (All /
 * Pending, Recent / Name, Ascending / Descending), a pick opens the list so. `on` false (no model): the select-a-model
 * note. Returns whether the click was on one of them.
 */
export function tagViewClick(
  doc: Document,
  ev: MouseEvent,
  { tabs, sortBtn, view, on, go }: { tabs: Element[]; sortBtn?: HTMLButtonElement | null; view: TagView; on: boolean; go(view: TagView): void },
): boolean {
  const t = ev.target as Element;
  const tab = tabs.find((x) => x.contains(t));
  if (tab) {
    ev.preventDefault();
    if (!on) note(doc, tab, SELECT_MODEL);
    else if (tagTabOf(tab) !== view.tab) go({ ...view, tab: tagTabOf(tab) });
    return true;
  }
  if (!sortBtn || t.closest("button") !== sortBtn) return false;
  ev.preventDefault();
  if (!on) {
    note(doc, sortBtn, SELECT_MODEL);
    return true;
  }
  const groups: MenuGroup[] = [
    { name: "filter", value: view.filter, options: [{ value: "all", label: "All" }, { value: "pending", label: "Pending" }] },
    { name: "sort", value: view.sort, options: [{ value: "date", label: TAG_SORT_LABELS.date }, { value: "name", label: TAG_SORT_LABELS.name }] },
    ORDER_GROUP(view.order),
  ];
  showMenu(doc, sortBtn, groups, (g, v) => go({ ...view, [g]: v } as TagView));
  return true;
}

/**
 * A tag row's More (`dots`, an applyTagRows row's): OF's menu with "Hide from list" (or "Show in list" for a hidden row),
 * which sends OF's toggle-show for the row's list entry, then OF's toast. No handlers (All-Creators): the select-a-model note.
 */
export function tagRowMenu(doc: Document, dots: HTMLElement, handlers: Pick<PostHandlers, "toggleTag"> | null): void {
  const row = dots.closest<HTMLElement>(LIST_ROW);
  const entity = Number(row?.getAttribute("data-oi-entity"));
  if (!handlers || !row || !entity) return note(doc, row ?? dots, SELECT_MODEL);
  const hidden = row.hasAttribute("data-oi-hidden");
  showMenu(doc, dots, [{ name: "row", radio: false, options: [{ value: "toggle", label: hidden ? "Show in list" : "Hide from list" }] }], () => {
    if (!handlers.toggleTag) return note(doc, row, READ_ONLY);
    handlers.toggleTag({ entity_id: entity, entity_type: row.getAttribute("data-oi-type") ?? "user" }).then(
      () => {
        row.toggleAttribute("data-oi-hidden", !hidden);
        toast(doc, hidden ? "Successfully returned to the list" : "Successfully removed from the list");
      },
      (e) => note(doc, row, `Could not ${hidden ? "show" : "hide"}: ${message(e)}`, true),
    );
  });
}

/**
 * Wire the labels dialog (new-post/state-labels) as the tag dialog: its rows are the Relay's list with a single Creator,
 * else none; a row's change toggles the label's id in the draft's `label_ids`. NEW LABEL opens OF's name field in place of
 * the button (Cancel puts the button back; Save is enabled while the name has text): Save creates the label and picks it
 * (the Relay's list is then fetched again, and the rebind shows it checked); a failure shows a red "Could not create: …".
 * All-Creators: NEW LABEL gives the select-a-model note. Returns an unbind, which removes the field and puts the
 * examples back.
 */
function bindLabels(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void): () => void {
  const { handlers, labelItems } = ctx;
  // Kept apart from ofMirrorData's restore: the page's right column (promotions, events) re-applies over it.
  const undo = own(() => applyLabelRows(doc, (handlers && labelItems && postLabelsOf(labelItems)) || [], draftOf(ctx).label_ids ?? []));
  const add = doc.querySelector<HTMLButtonElement>(NEW_LABEL);
  add?.setAttribute("data-oi-wired", "");
  const form = add && newLabelForm(doc, add);
  // OF's Sort (labels/savePostLabelsOrder): the rows are put in that order at once, and OF keeps it.
  const sortBtn = doc.querySelector<HTMLButtonElement>(".modal.show button[aria-label='Sort']");
  sortBtn?.setAttribute("data-oi-wired", "");
  const sorted = { sort: ctx.labelSort?.sort ?? "recent", order: ctx.labelSort?.order ?? "desc" };

  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement;
    const id = Number(box.closest?.<HTMLElement>(LIST_ROW)?.getAttribute("data-oi-label"));
    if (!handlers || !id) return;
    const others = (draftOf(ctx).label_ids ?? []).filter((l) => l !== id);
    update({ label_ids: box.checked ? [...others, id] : others });
  };
  /** NEW LABEL's field shown (`on`) or the button back, the field emptied. */
  const open = (on: boolean) => {
    if (!add || !form) return;
    add.style.display = on ? "none" : "";
    form.root.style.display = on ? "flex" : "none";
    form.input.value = "";
    form.save.disabled = true;
    if (on) form.input.focus();
  };
  const create = () => {
    const name = form?.input.value.trim();
    if (!handlers || !form || !name || form.save.disabled) return;
    form.save.disabled = true;
    handlers.createLabel(name).then(
      (label) => {
        const id = Number(label?.id);
        if (id) update({ label_ids: [...(draftOf(ctx).label_ids ?? []).filter((l) => l !== id), id] });
        open(false);
      },
      (e) => {
        form.save.disabled = false;
        note(doc, form.save, `Could not create: ${message(e)}`, true);
      },
    );
  };
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (sortBtn && target?.closest?.("button") === sortBtn) {
      ev.preventDefault();
      if (!handlers) return note(doc, sortBtn, SELECT_MODEL);
      const groups: MenuGroup[] = [{ name: "sort", value: sorted.sort, options: LABEL_SORTS }, ORDER_GROUP(sorted.order)];
      showMenu(doc, sortBtn, groups, (g, v) => {
        Object.assign(sorted, { [g]: v });
        sortLabelRows(doc, labelItems ?? [], sorted.sort, sorted.order);
        if (!handlers.sortLabels) return note(doc, sortBtn, READ_ONLY);
        // (under the dialog's header: a note beside the button would squeeze its title)
        handlers.sortLabels(sorted.sort, sorted.order).catch((e) => note(doc, sortBtn.closest(".modal-header") ?? sortBtn, `Could not save the order: ${message(e)}`, true));
      });
      return;
    }
    if (!add || !form || !target?.closest) return;
    if (target.closest(NEW_LABEL) === add) {
      ev.preventDefault();
      return handlers ? open(true) : note(doc, add, SELECT_MODEL);
    }
    if (target.closest("[data-oi-cancel]") === form.cancel) {
      ev.preventDefault();
      return open(false);
    }
    if (target.closest("[data-oi-save]") === form.save) {
      ev.preventDefault();
      create();
    }
  };
  const onInput = (ev: Event) => {
    if (form && ev.target === form.input) form.save.disabled = !form.input.value.trim();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (form && ev.target === form.input && ev.key === "Enter") {
      ev.preventDefault();
      create();
    }
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("keydown", onKey);
  return () => {
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("keydown", onKey);
    form?.root.remove();
    if (add) add.style.display = "";
    undo();
  };
}

/** OF's labels Sort fields (labels/savePostLabelsOrder: recent | name | posts | custom). */
const LABEL_SORTS = [
  { value: "recent", label: "Recent" },
  { value: "name", label: "Name" },
  { value: "posts", label: "Posts" },
  { value: "custom", label: "Custom" },
];

/**
 * The labels dialog's rows in `sort` / `order` (Recent: newest id first, Name, Posts: post count; Custom: OF's own order,
 * the Relay's as read), moved in place.
 */
export function sortLabelRows(doc: Document, items: PostLabel[], sort: string, order: string): void {
  const rows = [...doc.querySelectorAll<HTMLElement>(`${LIST_ROW}[data-oi-label]`)];
  if (rows.length < 2) return;
  const byId = new Map(items.map((l, i) => [String(l.id), { ...l, at: i }]));
  const key = (r: HTMLElement) => byId.get(r.getAttribute("data-oi-label") ?? "");
  const dir = order === "asc" ? 1 : -1;
  const cmp = (a: HTMLElement, b: HTMLElement) => {
    const x = key(a);
    const y = key(b);
    if (!x || !y) return 0;
    if (sort === "name") return dir * x.name.localeCompare(y.name);
    if (sort === "posts") return dir * ((x.postsCount ?? 0) - (y.postsCount ?? 0));
    if (sort === "recent") return dir * (Number(x.id) - Number(y.id));
    return x.at - y.at;
  };
  const anchor = rows[0].previousSibling;
  const parent = rows[0].parentElement!;
  const ordered = [...rows].sort(cmp);
  if (anchor) anchor.after(...ordered);
  else parent.prepend(...ordered);
}

/**
 * NEW LABEL's name field (hidden until opened), in its own row above the labels dialog's footer: OF's outlined text
 * field (the Fundraising target's markup) with a Cancel and a Save in the footer's own button style.
 */
function newLabelForm(doc: Document, add: HTMLButtonElement, placeholder = "Label name") {
  const root = doc.createElement("div");
  root.id = "oi-new-label";
  root.style.cssText = "display:none;align-items:center;gap:8px;padding:8px 16px;min-width:0";
  const field = doc.createElement("div");
  field.className = "v-input form-control g-input mb-0 v-input--hide-details theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined";
  field.style.cssText = "flex:1;min-width:0;border-bottom:1px solid rgba(138,150,163,.5)";
  const slot = doc.createElement("div");
  slot.className = "v-text-field__slot";
  const input = doc.createElement("input");
  input.type = "text";
  input.maxLength = 64;
  input.style.cssText = "width:100%;padding:6px 0";
  input.placeholder = placeholder;
  input.setAttribute("aria-label", placeholder);
  input.setAttribute("data-oi-wired", "");
  slot.append(input);
  const control = doc.createElement("div");
  control.className = "v-input__control";
  const inner = doc.createElement("div");
  inner.className = "v-input__slot";
  inner.append(slot);
  control.append(inner);
  field.append(control);
  const button = (text: string, mark: string) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "g-btn m-flat m-btn-gaps m-uppercase m-reset-width";
    b.textContent = ` ${text} `;
    b.setAttribute(mark, "");
    b.setAttribute("data-oi-wired", "");
    return b;
  };
  const cancel = button("Cancel", "data-oi-cancel");
  const save = button("Save", "data-oi-save");
  save.disabled = true;
  root.append(field, cancel, save);
  (add.closest("footer") ?? add).before(root);
  return { root, input, cancel, save };
}

/** For ofMirrorPost only; not re-exported. */
export { bindLabels };
