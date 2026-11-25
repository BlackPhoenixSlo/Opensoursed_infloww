"use client";


import { useEffect, useMemo, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, toChoice, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultMedia, type VaultUploadResp } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { mirrorQuery, plain, rowsOf } from "@/lib/ofMirrorData";
import { VAULT_LISTS, vaultMediaOf } from "@/lib/ofMirrorDataQueries";
import { floatLabel, linkUser, toggleTile, userHref } from "@/lib/ofMirrorDom";
import { sortOfFolders } from "@/hooks/useVaultCache";
import { HOME_VAULT, homeDraft, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { FIELDS, LIST_SORTS, markTypeTabs, TYPES, vaultHref, viewOf } from "@/lib/ofMirrorVault";
import { applyFormat, COLORS, hasFormatting, ofHtml, setOfHtml, SIZES, type FormatCommand } from "@/lib/ofMirrorFormat";
import { formatAtCaret, tidy } from "@/lib/ofRichTextEditor";
import { closeMenu, ORDER_GROUP, showMenu } from "@/lib/ofMirrorMenu";
import { GREY, localIso, message, note, NOTE_STYLE, QUEUE, READ_ONLY, schedulePill, SELECT_MODEL, textOf } from "@/lib/ofMirrorWrites";
import { markNotYet, markWired } from "@/lib/ofMirrorTooltip";
import { useAgencyZone, wallClock } from "@/lib/ofMirrorFeedsShared";
import { ofPrice } from "@/lib/ofMirrorPostCard";
import { bindSchedule, clearDraft, clock, collectPost, COMPOSER, type CreatePostBody, draftOf, EMPTY_TEXT, keepOf, loadDraft, mergeSendWith, MONTHS, type PostContext, type PostDraft, type PostHandlers, type PriceLimits, saveDraft, type SearchPost, type SearchUser, type UploadsInFlight, VOTING_DAYS, WEEKDAYS } from "@/lib/ofMirrorPostDraft";
import { bindLabels, bindTags, labelsOf, type PostLabelsResp, tagsRoute, type TagView, tagViewOf } from "@/lib/ofMirrorPostTags";
import { refetchOwnStories, vaultStoryBody, type VaultStoryBody } from "@/lib/ofMirrorStory";
import { lock, RECORD_POPUP, recordPopup, toast } from "@/lib/ofMirrorToast";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";
import { prefetchRecorder, recordSession, refusedAudio, voiceFile, type TakeRecording } from "@/lib/ofMirrorComposer";

export { clearDraft, collectPost, collectSchedule, type CreatePostBody, draftKey, loadDraft, mergeSendWith, type PostContext, type PostDraft, type PostHandlers, type PriceLimits, renderCalendar, saveDraft, type SearchPost, type SearchUser, type UploadsInFlight, type Voting } from "@/lib/ofMirrorPostDraft";
export { applyFormsEmpty, applyLabelRows, applyTagRows, bindTags, labelsOf, LIST_ROW, markTagTabs, NO_RELEASE_FORMS, NOTHING_FOUND, type PostLabel, postLabelsOf, type PostLabelsResp, sortLabelRows, TAG_SORT_LABELS, type TagContext, tagHref, type TagPicks, tagRowMenu, tagsRoute, type TagView, tagViewClick, tagViewOf } from "@/lib/ofMirrorPostTags";
export { bindStory, highlightItems, NOT_STORY_MEDIA, STORY, STORY_PICK, type StoryHandlers, useOfStory, vaultStoryBody, type VaultStoryBody } from "@/lib/ofMirrorStory";
export { CARRY_MS, frameNavigate, lock, RECORD_TEXT, recordPopup, takeCarried, toast } from "@/lib/ofMirrorToast";

export function postPriceLimits(me: OfMe | undefined): PriceLimits | null | undefined {
  if (!me) return undefined;
  if (!me.canChangeContentPrice || !me.canEarn || Number(me.subscribePrice) !== 0) return null;
  const min = Number(me.postMinPrice);
  const max = Number(me.postMaxPrice);
  return min > 0 && max >= min ? { min, max } : null;
}

const UPLOADING = "Wait for the upload to finish";
const ONE_FOR_STORY = "Pick one vault item for the story";
export const POSTED_TOAST = "Your post has been published";
export const SCHEDULED_TOAST = "Your post is scheduled for";
export const SAVED_TOAST = "Your post has been saved for later";
const SFL_POSTS = "/of-manager/queue/saved-for-later-posts";
export const EDITING = "Editing a scheduled post";
export const EDITING_LATER = "Editing a post saved for later";
export const PUBLISH_EDITED = "This post has no date: publish it now?";
const HOME = "/of-manager/home";
// OF's longest expiration period and poll length, in days.
const MAX_DAYS = 30;
const MAX_OPTIONS = 20;
const MIN_TARGET = 10;
const NO_EXTRAS: Partial<PostDraft> = {
  posted_at: undefined,
  save_for_later: undefined,
  tagged_users: [],
  voting: undefined,
  voting_due: undefined,
  expire_days: undefined,
  fund_raising_target: undefined,
  label_ids: undefined,
  price: undefined,
  upload_failed: undefined,
};
const EDITOR = "[contenteditable][aria-label='Textbox field']";
const POST = "button[at-attr='submit_post']";
const FORMAT = ".js-text-editor-toolbar";
const DIALOG_SAVE = ".modal.show .modal-footer button";
const PERIOD = ".modal.show input[name='periodValue']";
const PERIOD_TAB = ".modal.show .b-tabs__nav__link";
const TARGET = ".modal.show input[at-attr='input']";
const VOTE_ROW = ".b-make-post__voting .vote-input";
const OPTION = "input[at-attr='input']";
const QUIZ_PICK = ".m-quiz-swithcer";
const ADD_OPTION = ".b-make-post__voting .new_vote_add_option";
const DROP_VOTING = ".b-make-post__voting .b-post-piece .b-dropzone__preview__delete";
const DELETE_OPTION = ".delete-vote-option";
const DRAG = ".m-drag-btn";
const VOTING_PIECE = ".b-make-post__voting .b-post-piece";
const VOTING_PAGES = { 1: "state-poll", 2: "state-quiz" } as const;
const PERIOD_PAGE = "state-expiration";
const composerPage = (ctx: PostContext, state: string) => `${ctx.composer ?? COMPOSER}/${state}`;
const DURATION_TITLES = { 1: " POLL DURATION ", 2: " QUIZ DURATION " } as const;
const TAG_PAGE = "new-post/state-tag-people";
const HOME_SCHEDULE = "home/state-schedule";
const HOME_TAGS = "home/state-tag-people";
const LABEL_PAGE = "new-post/state-labels";
const LABELS = "/api/of/v2/labels";
const STORIES = "/api/of/v2/stories";
const PRICE_BTN = "[at-attr='price_btn']";
const PRICE_PAGE = "new-post/state-price";
const NOT_WITH_PRICE = "[aria-label='Expiration period'], [aria-label='Your target']";
const POST_AS = "oi-post-as";

const daysText = (n: number) => (n ? `${n} ${n === 1 ? "day" : "days"}` : "No limit");
const when = (d: Date) => `${WEEKDAYS[d.getDay()].slice(0, 3)}, ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}, ${clock(d)}`;

export const POST_PICK = { accept: "image/*,video/*,audio/*", multiple: true };

const ADD_MEDIA = "button.attach_file[aria-label='Add media']";
const THUMBS_ROW = "oi-post-thumbs";
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
const VAULT_SEARCH = "input[name='media_vault_search']";
const OPEN_SEARCH = "button[aria-label='Search media']";
const CLOSE_SEARCH = "[at-attr='close_search']";
const SEARCH_OPEN = "m-search-form-visible";
const VAULT_TABS = ".modal.show .b-tabs__nav__link";

const dropMediaAt = ({ media_files, thumbs }: PostDraft, at: number): Pick<PostDraft, "media_files" | "thumbs"> => ({
  media_files: media_files.filter((_, i) => i !== at),
  thumbs: thumbs.filter((_, i) => i !== at),
});

type DialogBinder = (doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string) => () => void;

const bindVoting =
  (type: 1 | 2): DialogBinder =>
  (doc, ctx, update) => {
    const add = doc.querySelector<HTMLButtonElement>(ADD_OPTION);
    const first = doc.querySelector(VOTE_ROW);
    if (!add || !first) return () => {};
    const template = first.cloneNode(true) as HTMLElement;
    const rows = () => [...doc.querySelectorAll<HTMLElement>(VOTE_ROW)];
    const radio = (row: Element) => row.querySelector<HTMLInputElement>("input[type='radio']");
    const pick = (row: Element, on: boolean) => {
      const r = radio(row);
      if (r) {
        r.checked = on;
        r.toggleAttribute("checked", on);
      }
      row.querySelector(QUIZ_PICK)?.classList.toggle("m-gray", !on);
    };
    const wire = () => {
      for (const el of doc.querySelectorAll(`${VOTE_ROW} ${OPTION}, ${VOTE_ROW} ${QUIZ_PICK}, ${VOTE_ROW} input[type='radio'], ${VOTE_ROW} ${DELETE_OPTION}, ${VOTE_ROW} ${DRAG}`)) el.setAttribute("data-oi-wired", "");
      const many = rows().length > 2;
      for (const del of doc.querySelectorAll<HTMLButtonElement>(`${VOTE_ROW} ${DELETE_OPTION}`)) del.disabled = !many;
    };
    let added = 0;
    const addRow = () => {
      const row = template.cloneNode(true) as HTMLElement;
      const input = row.querySelector<HTMLInputElement>(OPTION);
      if (input) input.placeholder = "Enter another option...";
      const r = radio(row);
      if (r) r.name = `quiz-option-oi-${++added}`;
      rows().at(-1)!.after(row);
      wire();
      return input;
    };
    const saved = draftOf(ctx).voting;
    if (saved?.type === type) {
      while (rows().length < saved.options.length) addRow();
      rows().forEach((row, i) => {
        const input = row.querySelector<HTMLInputElement>(OPTION);
        if (input) input.value = saved.options[i] ?? "";
        pick(row, i === saved.correct);
      });
    }
    add.setAttribute("data-oi-wired", "");
    wire();
    const piece = doc.querySelector(VOTING_PIECE);
    piece?.setAttribute("data-oi-wired", "");
    const shown = piece?.querySelector(".b-post-piece__value");
    if (shown) shown.textContent = daysText(draftOf(ctx).voting_due ?? VOTING_DAYS);

    const save = () => {
      const all = rows();
      const options = all.map((row) => row.querySelector<HTMLInputElement>(OPTION)?.value ?? "");
      const correct = all.findIndex((row) => radio(row)?.checked);
      update({ voting: options.some((o) => o.trim()) ? { type, options, ...(type === 2 && correct >= 0 ? { correct } : {}) } : undefined });
    };
    const onInput = (ev: Event) => {
      if (ctx.handlers && (ev.target as Element | null)?.closest?.(VOTE_ROW)) save();
    };
    const onChange = (ev: Event) => {
      const field = ev.target as HTMLInputElement;
      if (ctx.handlers || !field.closest?.(VOTE_ROW) || field.type === "radio") return;
      field.value = "";
      note(doc, field, SELECT_MODEL);
    };
    const onClick = (ev: MouseEvent) => {
      const target = ev.target as Element | null;
      if (!target?.closest) return;
      if (target.closest(DROP_VOTING)) return update({ voting: undefined, voting_due: undefined });
      const handle = target.closest(`${VOTE_ROW} ${DRAG}`);
      if (handle) {
        ev.preventDefault();
        if (ctx.handlers) note(doc, handle.closest(VOTE_ROW) ?? handle, "Drag to reorder the options");
        return;
      }
      if (target.closest(ADD_OPTION) === add) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, add, SELECT_MODEL);
        if (rows().length < MAX_OPTIONS) addRow()?.focus();
        return;
      }
      if (piece && target.closest(VOTING_PIECE) === piece) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, piece, SELECT_MODEL);
        update({ period_for: type });
        return ctx.handlers.navigate(composerPage(ctx, PERIOD_PAGE));
      }
      const del = target.closest(DELETE_OPTION)?.closest(VOTE_ROW);
      if (del) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, del, SELECT_MODEL);
        if (rows().length <= 2) return;
        const wasCorrect = !!radio(del)?.checked;
        del.remove();
        if (wasCorrect) pick(rows()[0], true);
        wire();
        return save();
      }
      const row = target.closest(QUIZ_PICK)?.closest(VOTE_ROW);
      if (!row) return;
      for (const r of rows()) pick(r, !!ctx.handlers && r === row);
      if (ctx.handlers) save();
      else note(doc, row, SELECT_MODEL);
    };
    let dragging: HTMLElement | null = null;
    const onDown = (ev: PointerEvent | MouseEvent) => {
      const handle = (ev.target as Element | null)?.closest?.(`${VOTE_ROW} ${DRAG}`);
      if (!handle) return;
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, handle.closest(VOTE_ROW) ?? handle, SELECT_MODEL);
      dragging = handle.closest<HTMLElement>(VOTE_ROW);
      if (dragging) dragging.style.opacity = "0.5";
    };
    const onMove = (ev: PointerEvent | MouseEvent) => {
      if (!dragging) return;
      ev.preventDefault();
      const others = rows().filter((r) => r !== dragging);
      const before = others.find((r) => {
        const box = r.getBoundingClientRect();
        return ev.clientY < box.top + box.height / 2;
      });
      if (before) {
        if (dragging.nextElementSibling !== before) before.before(dragging);
      } else if (others.length && others.at(-1)!.nextElementSibling !== dragging) others.at(-1)!.after(dragging);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging.style.opacity = "";
      dragging = null;
      wire();
      save();
    };
    doc.addEventListener("input", onInput);
    doc.addEventListener("change", onChange);
    doc.addEventListener("click", onClick);
    doc.addEventListener("pointerdown", onDown);
    doc.addEventListener("pointermove", onMove);
    doc.addEventListener("pointerup", onUp);
    return () => {
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("change", onChange);
      doc.removeEventListener("click", onClick);
      doc.removeEventListener("pointerdown", onDown);
      doc.removeEventListener("pointermove", onMove);
      doc.removeEventListener("pointerup", onUp);
    };
  };

const bindValueDialog =
  <K extends "expire_days" | "fund_raising_target" | "voting_due" | "price">(
    key: K,
    field: string,
    read: (value: string) => PostDraft[K] | null,
    extra: (doc: Document, input: HTMLInputElement, sync: () => void) => () => void = () => () => {},
    back?: string,
  ): DialogBinder =>
  (doc, ctx, update) => {
    const input = doc.querySelector<HTMLInputElement>(field);
    const save = doc.querySelector<HTMLButtonElement>(DIALOG_SAVE);
    if (!input || !save) return () => {};
    for (const el of [input, save]) el.setAttribute("data-oi-wired", "");
    const sync = () => {
      floatLabel(input, !!input.value);
      save.disabled = read(input.value) === null;
    };
    const saved = key === "voting_due" ? (draftOf(ctx).voting_due ?? VOTING_DAYS) : draftOf(ctx)[key];
    if (saved) {
      input.value = String(saved);
      sync();
    }
    const onInput = (ev: Event) => {
      if (ev.target === input) sync();
    };
    const onClick = (ev: MouseEvent) => {
      if ((ev.target as Element | null)?.closest?.(DIALOG_SAVE) !== save) return;
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, save, SELECT_MODEL);
      const value = read(input.value);
      if (value === null) return;
      update({ [key]: key === "voting_due" ? value : value || undefined });
      ctx.handlers.navigate(back ?? ctx.composer ?? COMPOSER);
    };
    const unbindExtra = extra(doc, input, sync);
    doc.addEventListener("input", onInput);
    doc.addEventListener("click", onClick);
    return () => {
      unbindExtra();
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("click", onClick);
    };
  };

const readDays = (value: string): number | null => {
  const v = value.trim();
  const n = Number(v);
  return !v ? 0 : Number.isInteger(n) && n >= 1 && n <= MAX_DAYS ? n : null;
};
const periodTabs = (doc: Document, input: HTMLInputElement, sync: () => void) => {
  const tabs = [...doc.querySelectorAll<HTMLButtonElement>(PERIOD_TAB)];
  const daysOf = (tab: Element) => /\d+/.exec(tab.textContent ?? "")?.[0] ?? "";
  const mark = () => {
    for (const tab of tabs) tab.classList.toggle("m-current", readDays(daysOf(tab)) === readDays(input.value));
  };
  for (const tab of tabs) tab.setAttribute("data-oi-wired", "");
  mark();
  const onInput = (ev: Event) => {
    if (ev.target === input) mark();
  };
  const onClick = (ev: MouseEvent) => {
    const tab = (ev.target as Element | null)?.closest?.<HTMLButtonElement>(PERIOD_TAB);
    if (!tab || !tabs.includes(tab)) return;
    ev.preventDefault();
    input.value = daysOf(tab);
    mark();
    sync();
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
};
const bindPeriod: DialogBinder = (doc, ctx, update, page) => {
  const type = draftOf(ctx).period_for;
  if (!type) return bindValueDialog("expire_days", PERIOD, readDays, periodTabs)(doc, ctx, update, page);
  const back = composerPage(ctx, VOTING_PAGES[type]);
  const title = doc.querySelector(".modal.show .modal-title");
  const links = [...doc.querySelectorAll<HTMLAnchorElement>(".modal.show .modal-footer a, .modal.show .of-state-backdrop")];
  const was = { title: title?.textContent, hrefs: links.map((a) => a.getAttribute("href")) };
  if (title) title.textContent = DURATION_TITLES[type];
  for (const a of links) a.setAttribute("href", back);
  const unbind = bindValueDialog("voting_due", PERIOD, readDays, periodTabs, back)(doc, ctx, update, page);
  return () => {
    unbind();
    if (title) title.textContent = was.title ?? "";
    links.forEach((a, i) => a.setAttribute("href", was.hrefs[i] ?? ctx.composer ?? COMPOSER));
  };
};

const dollars = (value: string) => value.trim().replace(/^\$/, "");

export const readPrice =
  (limits: PriceLimits | null | undefined) =>
  (value: string): number | null => {
    const v = dollars(value);
    if (!v) return 0;
    const n = Number(v);
    return limits && Number.isFinite(n) && n >= limits.min && n <= limits.max ? Math.round(n * 100) / 100 : null;
  };

const bindPrice: DialogBinder = (doc, ctx, update, page) => {
  const help = doc.querySelector(".modal.show .g-input__help");
  const was = help?.textContent ?? "";
  if (help && ctx.priceLimits) help.textContent = `Minimum $${ctx.priceLimits.min} USD or free`;
  const saved = draftOf(ctx).price ?? 0;
  const read = (value: string) => {
    const n = readPrice(ctx.priceLimits)(value);
    return n === null || n === saved || (n === 0 && !saved) ? null : n;
  };
  const unbind = bindValueDialog("price", TARGET, read)(doc, ctx, update, page);
  return () => {
    unbind();
    if (help) help.textContent = was;
  };
};

const readTarget = (value: string): number | null => {
  const n = Number(dollars(value));
  return value.trim() && Number.isFinite(n) && n >= MIN_TARGET ? n : null;
};

export function bindVaultSearch(doc: Document): () => void {
  const search = doc.querySelector<HTMLInputElement>(VAULT_SEARCH);
  const header = search?.closest(".g-page__header");
  const opener = header?.querySelector(OPEN_SEARCH);
  const closer = header?.querySelector(CLOSE_SEARCH);
  if (!search || !header || !opener || !closer) return () => {};
  for (const el of [search, opener, closer]) el.setAttribute("data-oi-wired", "");
  const filter = () => {
    const query = search.value.trim().toLowerCase();
    for (const tile of doc.querySelectorAll<HTMLElement>("[data-oi-media]")) {
      tile.style.display = (tile.getAttribute("data-oi-text") ?? "").toLowerCase().includes(query) ? "" : "none";
    }
  };
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest(OPEN_SEARCH) === opener) {
      header.classList.add(SEARCH_OPEN);
      search.focus();
    } else if (target.closest(CLOSE_SEARCH) === closer) {
      header.classList.remove(SEARCH_OPEN);
      search.value = "";
      filter();
    }
  };
  const onInput = (ev: Event) => {
    if (ev.target === search) filter();
  };
  const onSubmit = (ev: Event) => {
    if (ev.target === search.form) ev.preventDefault();
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
  };
}

function bindVault(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string): () => void {
  const view = ctx.vaultView ?? {};
  const tabs = [...doc.querySelectorAll<HTMLElement>(VAULT_TABS)];
  markTypeTabs(tabs, view.type ?? null);
  const close = doc.querySelector(".modal.show .modal-footer a");
  const story = doc.createElement("button");
  story.type = "button";
  story.className = close?.className ?? "g-btn m-flat m-btn-gaps m-uppercase m-reset-width";
  story.textContent = " Add to story ";
  story.setAttribute("data-oi-wired", "");
  close?.before(story);
  const onStory = (ev: Event) => {
    ev.preventDefault();
    const { handlers } = ctx;
    if (!handlers) return note(doc, story, SELECT_MODEL);
    if (!handlers.addVaultStory) return note(doc, story, READ_ONLY);
    if (story.disabled) return;
    const ids = draftOf(ctx).media_files.filter((m): m is number => typeof m === "number");
    if (ids.length !== 1) return note(doc, story, ONE_FOR_STORY, true);
    story.disabled = true;
    doc.getElementById("oi-note")?.remove();
    handlers
      .addVaultStory(vaultStoryBody(ids[0], ctx.vaultItems))
      .then(
        () => note(doc, story, "Added to story"),
        (e) => note(doc, story, `Could not add: ${message(e)}`, true),
      )
      .finally(() => (story.disabled = false));
  };
  story.addEventListener("click", onStory);
  const onClick = (ev: MouseEvent) => {
    const tab = (ev.target as Element | null)?.closest?.(VAULT_TABS);
    if (tab) {
      ev.preventDefault();
      const type = TYPES[tabs.indexOf(tab as HTMLElement)] ?? null;
      if (type === (view.type ?? null)) return;
      return ctx.handlers ? ctx.handlers.navigate(vaultHref({ list: view.list, type }, `/of-manager/${page}`)) : note(doc, tab, SELECT_MODEL);
    }
    const tile = (ev.target as Element | null)?.closest?.(VAULT_TILE);
    if (!tile) return;
    const id = Number(tile.getAttribute("data-oi-media"));
    if (!ctx.handlers || !id) return note(doc, doc.querySelector(".modal-footer a") ?? tile, SELECT_MODEL);
    const draft = draftOf(ctx);
    const { media_files, thumbs } = draft;
    const at = media_files.indexOf(id);
    if (at < 0) {
      update({ media_files: [...media_files, id], thumbs: [...thumbs, tile.querySelector(".b-photos__item__img")?.getAttribute("src") ?? ""] });
    } else {
      update(dropMediaAt(draft, at));
    }
    toggleTile(tile, at < 0);
  };
  doc.addEventListener("click", onClick);
  const unbindSearch = bindVaultSearch(doc);
  const unbindTools = bindVaultTools(doc, ctx, page);
  return () => {
    doc.removeEventListener("click", onClick);
    story.removeEventListener("click", onStory);
    story.remove();
    unbindSearch();
    unbindTools();
  };
}

const folderRows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".modal.show .l-sidebar-column .b-rows-lists__item[data-oi-data]")];
const folderName = (r: Element) => r.querySelector(".b-rows-lists__item__name")?.textContent?.trim() ?? "";

export function sortFoldersByName(doc: Document, order: string): void {
  const rows = folderRows(doc);
  if (rows.length < 2) return;
  const dir = order === "asc" ? 1 : -1;
  const anchor = rows[0].previousSibling;
  const parent = rows[0].parentElement!;
  const sorted = [...rows].sort((a, b) => dir * folderName(a).localeCompare(folderName(b)));
  if (anchor) anchor.after(...sorted);
  else parent.prepend(...sorted);
}

export function bindVaultTools(
  doc: Document,
  ctx: Pick<PostContext, "vaultView" | "folderSort"> & { handlers: Pick<PostHandlers, "navigate" | "sortFolders"> | null },
  page: string,
  stay: (href: string) => string = (href) => href,
): () => void {
  const view = ctx.vaultView ?? {};
  const side = doc.querySelector<HTMLElement>(".modal.show .l-sidebar-column");
  const folderSearch = side?.querySelector<HTMLButtonElement>(".g-page__header button[aria-label='Search']");
  const folderSort = side?.querySelector<HTMLButtonElement>("button[aria-label='Sort']");
  const mediaSort = [...doc.querySelectorAll<HTMLButtonElement>(".modal.show button[aria-label='Sort']")].find((b) => !side?.contains(b)) ?? null;
  const submit = doc.querySelector<HTMLButtonElement>(".modal.show .b-search-form button[type='submit']");
  for (const el of [folderSearch, folderSort, mediaSort, submit]) el?.setAttribute("data-oi-wired", "");
  const greyed = [folderSearch, folderSort, mediaSort, submit].filter((b): b is HTMLButtonElement => !!b?.disabled);
  const tips = greyed.map((b) => b.getAttribute("title"));
  for (const b of greyed) {
    b.disabled = false;
    b.removeAttribute("title");
  }
  const mediaTitle = mediaSort?.closest(".b-content-filter")?.querySelector(".b-content-filter__title");
  const wasTitle = mediaTitle?.textContent ?? null;
  if (mediaTitle) mediaTitle.textContent = FIELDS[view.field ?? "recent"] ?? "Recent";
  const sorted = { sort: ctx.folderSort?.sort ?? "default", order: ctx.folderSort?.order ?? "desc" };
  let field: HTMLInputElement | null = null;
  let timer = 0;
  const win = doc.defaultView;
  const search = (q: string | null) => ctx.handlers?.navigate(stay(vaultHref({ ...view, slist: q }, `/of-manager/${page}`)));
  const openSearch = () => {
    if (field || !folderSearch) return;
    field = doc.createElement("input");
    field.type = "search";
    field.maxLength = 100;
    field.placeholder = "Search...";
    field.setAttribute("aria-label", "Search folders");
    field.className = "b-search-form__input form-control";
    field.style.cssText = "flex:1;min-width:0;margin:0 8px;height:32px";
    field.setAttribute("data-oi-wired", "");
    field.value = view.slist ?? "";
    field.addEventListener("input", () => {
      win?.clearTimeout(timer);
      timer = win?.setTimeout(() => search(field?.value.trim() || null), 400) ?? 0;
    });
    folderSearch.closest(".b-btns-group")?.before(field);
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  };
  if (view.slist) openSearch();
  const onClick = (ev: MouseEvent) => {
    const b = (ev.target as Element | null)?.closest?.("button");
    if (!b) return;
    if (b === folderSearch) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      if (!field) return openSearch();
      field.remove();
      field = null;
      if (view.slist) search(null);
      return;
    }
    if (b === folderSort) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      const { handlers } = ctx;
      const options = Object.entries(LIST_SORTS).map(([value, label]) => ({ value, label }));
      showMenu(doc, b, [{ name: "sort", value: sorted.sort, options }, ORDER_GROUP(sorted.order)], (g, v) => {
        Object.assign(sorted, { [g]: v });
        if (sorted.sort === "name") sortFoldersByName(doc, sorted.order);
        if (!handlers.sortFolders) return note(doc, b, READ_ONLY);
        handlers.sortFolders(sorted.sort, sorted.order).catch((e) => note(doc, b.closest(".b-content-filter") ?? b, `Could not sort: ${message(e)}`, true));
      });
      return;
    }
    if (b === mediaSort) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      const { handlers } = ctx;
      const fields = Object.entries(FIELDS).map(([value, label]) => ({ value, label }));
      showMenu(doc, b, [{ name: "field", value: view.field ?? "recent", options: fields }, ORDER_GROUP(view.sort ?? "desc")], (g, v) => {
        const next = g === "field" ? { ...view, field: v === "recent" ? null : v } : { ...view, sort: v === "asc" ? "asc" : null };
        handlers.navigate(stay(vaultHref(next, `/of-manager/${page}`)));
      });
    }
  };
  doc.addEventListener("click", onClick);
  return () => {
    win?.clearTimeout(timer);
    doc.removeEventListener("click", onClick);
    field?.remove();
    if (mediaTitle && wasTitle !== null) mediaTitle.textContent = wasTitle;
    greyed.forEach((b, i) => {
      b.disabled = true;
      if (tips[i] !== null) b.setAttribute("title", tips[i]!);
    });
    closeMenu(doc);
  };
}

export function bindAddMedia(
  doc: Document,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => TakenMedia,
  update: (patch: Partial<TakenMedia>) => void,
  uploading: (n: 1 | -1) => void,
  none: string = SELECT_MODEL,
  pick: { accept: string; multiple: boolean } = { accept: "image/*,video/*", multiple: false },
  done?: (file: File) => void,
): () => void {
  const button = doc.querySelector(ADD_MEDIA);
  if (!button) return () => {};
  const { handlers } = ctx;
  const input = doc.createElement("input");
  input.type = "file";
  input.accept = pick.accept;
  input.multiple = pick.multiple;
  input.hidden = true;
  // The field whose file Add media sends: not bindWrites' change path.
  input.setAttribute("data-oi-wired", "");
  doc.body.append(input);
  button.setAttribute("data-oi-wired", "");

  const onClick = (ev: Event) => {
    ev.preventDefault();
    if (handlers) input.click();
    else note(doc, button, none);
  };
  const take = mediaTaker(doc, button, ctx, media, update, uploading, done);
  const onChange = () => {
    const files = [...(input.files ?? [])];
    input.value = "";
    take(files);
  };
  button.addEventListener("click", onClick);
  input.addEventListener("change", onChange);
  return () => {
    button.removeEventListener("click", onClick);
    input.removeEventListener("change", onChange);
    input.remove();
  };
}

type TakenMedia = Pick<PostDraft, "media_files" | "thumbs" | "upload_failed">;
export const mediaKey = (file: File) => /^(voice|video)-\d+\./.exec(file.name)?.[1] ?? file.name;
export const pickKeys = (files: File[]) => {
  const seen = new Map<string, number>();
  return files.map((file) => {
    const key = mediaKey(file);
    const n = (seen.get(key) ?? 0) + 1;
    seen.set(key, n);
    return n > 1 ? `${key} #${n}` : key;
  });
};
function failedWith(failed: Record<string, string> | undefined, key: string, why?: string) {
  const next = { ...failed };
  if (why) next[key] = why;
  else delete next[key];
  return Object.keys(next).length ? next : undefined;
}
export const uploadFailed = (failed: Record<string, string>) => `Upload failed: ${[...new Set(Object.values(failed))].join("; ")}. Send without it?`;

export function mediaTaker(
  doc: Document,
  anchor: Element,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => TakenMedia,
  update: (patch: Partial<TakenMedia>) => void,
  uploading: (n: 1 | -1) => void,
  done?: (file: File) => void,
): (files: File[]) => void {
  const send = (file: File, key: string) => {
    const fail = (why: string) => {
      update({ upload_failed: failedWith(media().upload_failed, key, why) });
      note(doc, anchor, `Could not upload: ${why}`, true);
    };
    const upload = (up: File) => ctx.handlers!.upload(up).then((r) => ({ ...r, up }));
    return (refusedAudio(file) ? voiceFile(file).then(upload) : upload(file))
      .then(
        ({ ready, send_with, note: why, up }) => {
          if (ready !== true) return fail(why || "upload not ready");
          const { media_files, thumbs, upload_failed } = media();
          const kept = { upload_failed: failedWith(upload_failed, key) };
          if (!send_with.length) return update(kept);
          const thumb = proxyImage(URL.createObjectURL(up), ctx.accountId);
          update({ media_files: mergeSendWith(media_files, send_with), thumbs: [...thumbs, ...send_with.map(() => thumb)], ...kept });
          done?.(up);
        },
        (e) => fail(message(e)),
      )
      .finally(() => uploading(-1));
  };
  return (files) => {
    if (!files.length || !ctx.handlers) return;
    files.forEach(() => uploading(1));
    const keys = pickKeys(files);
    let chain: Promise<unknown> | null = null;
    files.forEach((file, i) => (chain = chain ? chain.then(() => send(file, keys[i])) : send(file, keys[i])));
  };
}

const bindFormat: DialogBinder = (doc, ctx) => {
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const panel = doc.querySelector<HTMLElement>(FORMAT);
  if (!editor || !panel) return () => {};
  return bindFormatPanel(doc, editor, panel, () => (ctx.handlers ? null : SELECT_MODEL));
};

const PLAIN_FORMATS: Record<string, "bold" | "italic" | "clear"> = { Bold: "bold", Italic: "italic", "Clear Formatting": "clear" };

export function bindFormatPanel(doc: Document, editor: HTMLElement, panel: HTMLElement, blocked: () => string | null): () => void {
  const tool = (label: string) => panel.querySelector<HTMLElement>(`[aria-label='${label}']`);
  const size = tool("Text Size");
  const color = tool("Text Color");
  for (const el of panel.querySelectorAll("button, .v-input, .v-input__slot, input")) el.setAttribute("data-oi-wired", "");
  let saved: Range | null = null;
  const onSelection = () => {
    const sel = doc.getSelection();
    if (sel?.rangeCount && editor.contains(sel.getRangeAt(0).commonAncestorContainer)) saved = sel.getRangeAt(0).cloneRange();
  };
  const apply = (cmd: FormatCommand): boolean => {
    const why = blocked();
    if (why) {
      note(doc, panel, why);
      return false;
    }
    const sel = doc.getSelection();
    if (saved && !(sel?.rangeCount && editor.contains(sel.anchorNode))) {
      editor.focus();
      sel?.removeAllRanges();
      sel?.addRange(saved);
    }
    const caret = !!sel?.rangeCount && sel.isCollapsed && editor.contains(sel.anchorNode);
    if (!(caret ? formatAtCaret(editor, sel!, cmd) : applyFormat(editor, cmd))) {
      note(doc, panel, "Select some text to format");
      return false;
    }
    onSelection();
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  };
  const onInput = () => tidy(editor);
  const onDown = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (t?.closest && panel.contains(t) && !t.closest("a[href]")) ev.preventDefault();
  };
  const onClick = (ev: MouseEvent) => {
    const t = (ev.target as Element | null)?.closest?.<HTMLElement>("[aria-label]");
    if (!t || !panel.contains(t)) return;
    const label = t.getAttribute("aria-label");
    if (label && Object.hasOwn(PLAIN_FORMATS, label)) {
      ev.preventDefault();
      return apply({ kind: PLAIN_FORMATS[label] });
    }
    if (label === "Text Color" && color) {
      ev.preventDefault();
      const options = COLORS.map((c) => ({ value: c.cls, label: c.label, className: c.cls }));
      showMenu(doc, color, [{ name: "color", radio: false, options }], (_, cls) => {
        if (!apply({ kind: "color", cls })) return;
        const swatch = color.querySelector(".b-text-colour");
        if (swatch) swatch.className = `b-text-colour ${cls}`;
      });
      return;
    }
    if (label === "Text Size" && size) {
      ev.preventDefault();
      const shown = size.querySelector(".v-select__selection");
      const current = SIZES.find((x) => x.label === shown?.textContent?.trim())?.cls ?? "m-editor-fs__default";
      const options = SIZES.map((x) => ({ value: x.cls, label: x.label, className: x.cls }));
      showMenu(doc, size, [{ name: "size", radio: false, value: current, options }], (_, cls) => {
        if (apply({ kind: "size", cls }) && shown) shown.textContent = SIZES.find((x) => x.cls === cls)?.label ?? "Default";
      });
    }
  };
  // Put the editor's selection back only when it left: a selection change drops the browser's armed typing style.
  doc.addEventListener("selectionchange", onSelection);
  doc.addEventListener("mousedown", onDown);
  doc.addEventListener("click", onClick);
  editor.addEventListener("input", onInput);
  return () => {
    editor.removeEventListener("input", onInput);
    doc.removeEventListener("selectionchange", onSelection);
    doc.removeEventListener("mousedown", onDown);
    doc.removeEventListener("click", onClick);
    closeMenu(doc);
  };
}

const SHARED_DIALOGS: Record<string, DialogBinder> = {
  [VOTING_PAGES[1]]: bindVoting(1),
  [VOTING_PAGES[2]]: bindVoting(2),
  [PERIOD_PAGE]: bindPeriod,
  "state-target": bindValueDialog("fund_raising_target", TARGET, readTarget),
  "state-format-text": bindFormat,
};

const DIALOGS: Record<string, DialogBinder> = {
  "new-post/state-schedule": bindSchedule,
  [HOME_SCHEDULE]: bindSchedule,
  [TAG_PAGE]: bindTags,
  [HOME_TAGS]: bindTags,
  [VAULT_DIALOG]: bindVault,
  [HOME_VAULT]: bindVault,
  [LABEL_PAGE]: bindLabels,
  [PRICE_PAGE]: bindPrice,
  ...Object.fromEntries(Object.entries(SHARED_DIALOGS).flatMap(([state, bind]) => [[`new-post/${state}`, bind], [`home/${state}`, bind]])),
};

const RECORD = "button.b-chat__video-record-btn, button[aria-label='Record voice']";
const RECORD_VIDEO = "button.b-chat__video-record-btn";

const FEED_SEARCH = "input[name='feed-search-input']";
const SEARCH_RESULTS = "oi-search-results";

export function searchHref(kind: "user" | "post", item: SearchUser | SearchPost, meId?: number | string): string | null {
  const me = meId == null ? null : String(meId);
  return kind === "user" ? userHref(item as SearchUser, me) : userHref((item as SearchPost).author, me);
}

export const rowsIn = <T,>(r: unknown): T[] => (Array.isArray(r) ? (r as T[]) : ((r as { list?: T[]; items?: T[] } | null)?.list ?? (r as { items?: T[] } | null)?.items ?? []));

export type FeedSearchHandlers = Required<Pick<PostHandlers, "searchUsers" | "searchPosts">>;
export function feedSearchHandlers(accountId: string | null): FeedSearchHandlers {
  return {
    searchUsers: (q) => relay.get<SearchUser[]>(`/api/of/v2/users/search?q=${encodeURIComponent(q)}&limit=5`, { accountId }),
    searchPosts: (q) => relay.get<SearchPost[]>(`/api/of/v2/posts/search?query=${encodeURIComponent(q)}&limit=5`, { accountId }),
  };
}

export function bindFeedSearch(doc: Document, ctx: { handlers: Pick<PostHandlers, "searchUsers" | "searchPosts"> | null; meId?: number | string }): () => void {
  const input = doc.querySelector<HTMLInputElement>(FEED_SEARCH);
  if (!input) return () => {};
  input.disabled = false;
  const form = input.closest("form");
  const submit = form?.querySelector<HTMLButtonElement>("button[type='submit']") ?? null;
  for (const el of [input, submit, form]) el?.setAttribute("data-oi-wired", "");
  let timer = 0;
  let asked = "";
  const win = doc.defaultView;
  const results = () => doc.getElementById(SEARCH_RESULTS);
  const draw = (users: SearchUser[], posts: SearchPost[]) => {
    results()?.remove();
    const box = doc.createElement("div");
    box.id = SEARCH_RESULTS;
    box.setAttribute("data-oi-wired", "");
    box.className = "b-rows-lists";
    box.style.cssText = "padding:4px 0;font-size:14px;line-height:20px";
    const head = (text: string) => {
      const h = doc.createElement("div");
      h.className = "g-gray-text g-text-uppercase";
      h.style.cssText = "padding:8px 16px 4px;font-size:12px";
      h.textContent = text;
      return h;
    };
    const link = (href: string | null, text: string) => {
      const a = doc.createElement("a");
      a.className = "b-rows-lists__item__text m-with-rectangle-hover g-text-ellipsis";
      a.style.cssText = "display:block;padding:6px 16px";
      a.textContent = text;
      if (href) linkUser([a], href);
      else a.setAttribute("aria-disabled", "true");
      return a;
    };
    if (!users.length && !posts.length) box.append(head("Nothing found"));
    if (users.length) box.append(head("Users"), ...users.map((u) => link(searchHref("user", u, ctx.meId), `${plain(u.name)}${u.username ? ` @${u.username}` : ""}`.trim())));
    if (posts.length) {
      box.append(
        head("Posts"),
        ...posts.map((p) => {
          const text = plain((p.rawText ?? p.text ?? "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").slice(0, 80) || "Post";
          const by = p.author?.username ? ` · @${p.author.username}` : "";
          return link(searchHref("post", p, ctx.meId), `${text}${by}`);
        }),
      );
    }
    (form ?? input).after(box);
  };
  const run = (q: string) => {
    const { handlers } = ctx;
    if (!q) {
      asked = "";
      return results()?.remove();
    }
    if (!handlers) return note(doc, input, SELECT_MODEL);
    if (!handlers.searchUsers || !handlers.searchPosts) return note(doc, input, READ_ONLY);
    asked = q;
    Promise.allSettled([handlers.searchUsers(q), handlers.searchPosts(q)]).then(([u, p]) => {
      if (asked !== q) return;
      draw(u.status === "fulfilled" ? rowsIn<SearchUser>(u.value) : [], p.status === "fulfilled" ? rowsIn<SearchPost>(p.value) : []);
      if (u.status === "rejected" && p.status === "rejected") note(doc, input, `Could not search: ${message(u.reason)}`, true);
    });
  };
  const onInput = (ev: Event) => {
    if (ev.target !== input) return;
    if (submit) submit.disabled = !input.value.trim();
    win?.clearTimeout(timer);
    const q = input.value.trim();
    if (!q) return run("");
    timer = win?.setTimeout(() => run(q), 400) ?? 0;
  };
  const onSubmit = (ev: Event) => {
    if (ev.target !== form) return;
    ev.preventDefault();
    win?.clearTimeout(timer);
    run(input.value.trim());
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    win?.clearTimeout(timer);
    asked = "";
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
    results()?.remove();
  };
}

function bindRecordPopup(doc: Document): () => void {
  const records = [...doc.querySelectorAll<HTMLButtonElement>(RECORD)];
  for (const b of records) markWired(b, true);
  const onRecord = (ev: Event) => {
    ev.preventDefault();
    const b = ev.currentTarget as HTMLButtonElement;
    b.setAttribute("aria-expanded", "true");
    recordPopup(doc, () => b.removeAttribute("aria-expanded"));
  };
  for (const b of records) b.addEventListener("click", onRecord);
  return () => {
    for (const b of records) b.removeEventListener("click", onRecord);
    doc.getElementById(RECORD_POPUP)?.remove();
  };
}

function bindRecorder(doc: Document, key: string, take: TakeRecording, selected: boolean): () => void {
  const records = [...doc.querySelectorAll<HTMLButtonElement>(RECORD)];
  for (const b of records) markWired(b, true);
  if (selected) prefetchRecorder(doc);
  const rec = recordSession(doc, key, take);
  const onRecord = (ev: Event) => {
    ev.preventDefault();
    const b = ev.currentTarget as HTMLButtonElement;
    if (!selected) return note(doc, b, SELECT_MODEL);
    if (b.disabled || rec.busy()) return;
    rec.record(b.matches(RECORD_VIDEO) ? "video" : "voice", b, true);
  };
  for (const b of records) b.addEventListener("click", onRecord);
  return () => {
    for (const b of records) {
      b.removeEventListener("click", onRecord);
      markNotYet(b);
    }
    rec.release();
  };
}

export function bindPost(doc: Document, page: string, given: PostContext): () => void {
  const home = page.startsWith("home/");
  const ctx: PostContext = { ...given, composer: home ? HOME : COMPOSER };
  const { handlers } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const post = doc.querySelector<HTMLButtonElement>(POST);
  if (!editor || !post) return () => {};
  const keep = keepOf(ctx);
  post.setAttribute("data-oi-wired", "");

  const tagName = (id: number) => {
    const u = ctx.tagItems?.map(toChoice).find((t) => t.id === id);
    return u ? u.name : String(id);
  };
  const labelNames = (ids: number[]) => {
    const names = ids.map((id) => ctx.labelItems?.find((l) => Number(l.id) === id)?.name);
    return names.every(Boolean) ? names.join(", ") : null;
  };
  const summary = () => {
    const { posted_at: at, save_for_later: later, tagged_users: tags, voting, voting_due: due, expire_days: days, fund_raising_target: target, label_ids: labels, price, edit_id: editing } = draftOf(ctx);
    for (const el of doc.querySelectorAll<HTMLElement>(NOT_WITH_PRICE)) lock(el, !!price);
    const priceBtn = doc.querySelector<HTMLElement>(PRICE_BTN);
    if (priceBtn) lock(priceBtn, !!(days || target));
    const parts = [
      ...(editing ? [later ? EDITING_LATER : EDITING] : []),
      ...(price ? [`Price: ${ofPrice(price)}`] : []),
      ...(later ? ["Saved for later"] : at ? [`Scheduled for ${when(wallClock(new Date(at), ctx.zone))}`] : []),
      ...(tags.length ? [`Tagged: ${tags.map(tagName).join(", ")}`] : []),
      ...(voting ? [`${voting.type === 2 ? "Quiz" : "Poll"}: ${voting.options.filter((o) => o.trim()).length} options${due === undefined ? "" : `, ${daysText(due)}`}`] : []),
      ...(days ? [`Expires after ${days} ${days === 1 ? "day" : "days"}`] : []),
      ...(target ? [`Target: ${ofPrice(target)}`] : []),
      ...(labels?.length ? [`Labels: ${labelNames(labels) ?? labels.length}`] : []),
    ];
    schedulePill(doc, editor, editing ? (later ? "Saved for later" : at ? when(wallClock(new Date(at), ctx.zone)) : null) : null);
    const old = doc.getElementById("oi-post-summary");
    if (!parts.length) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = "oi-post-summary";
    el.style.cssText = NOTE_STYLE;
    el.style.color = GREY;
    const clear = doc.createElement("a");
    clear.href = "#";
    clear.textContent = "Clear";
    clear.setAttribute("data-oi-wired", "");
    clear.setAttribute("data-oi-clear", "");
    el.replaceChildren(`${parts.join(" · ")} · `, clear);
    if (editing) {
      const discard = doc.createElement("a");
      discard.href = "#";
      discard.textContent = "Discard";
      discard.setAttribute("data-oi-wired", "");
      discard.setAttribute("data-oi-discard", "");
      el.append(" · ", discard);
    }
    if (!old) (editor.closest(".g-input__wrapper") ?? editor).after(el);
  };
  const media = () => {
    doc.getElementById(THUMBS_ROW)?.remove();
    const { thumbs } = draftOf(ctx);
    const actions = doc.querySelector(".b-make-post__actions");
    if (!thumbs.length || !actions) return;
    const row = doc.createElement("div");
    row.id = THUMBS_ROW;
    row.dataset.oiData = "";
    row.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px";
    row.append(
      ...thumbs.map((src, at) => {
        const item = doc.createElement("div");
        item.className = "b-photos__item";
        item.style.cssText = "position:relative;width:64px;height:64px;flex:none;border-radius:6px;overflow:hidden";
        const img = doc.createElement("img");
        img.alt = "";
        img.className = "b-photos__item__img";
        img.addEventListener("error", () => {
          img.remove();
          item.style.background = GREY;
        });
        img.src = src;
        const remove = doc.createElement("button");
        remove.type = "button";
        remove.className = "b-dropzone__preview__delete g-btn m-rounded m-reset-width m-thumb-r-corner-pos m-btn-remove m-sm-icon-size";
        remove.style.cssText = "position:absolute;top:4px;right:4px;z-index:1";
        remove.setAttribute("aria-label", "Delete");
        remove.setAttribute("data-oi-wired", "");
        remove.dataset.oiRemoveMedia = String(at);
        remove.innerHTML = `<svg data-icon-name="icon-close" aria-hidden="true" class="g-icon"><use href="#icon-close" xlink:href="#icon-close"></use></svg>`;
        item.append(img, remove);
        return item;
      }),
    );
    actions.before(row);
  };
  const update = (patch: Partial<PostDraft>) => {
    if (keep) saveDraft(keep.storage, keep.accountId, { ...draftOf(ctx), ...patch });
    summary();
    if (patch.thumbs) media();
    if (patch.media_files) sync(textOf(editor));
  };

  const flight = ctx.uploads ?? { count: 0 };
  const sync = (text: string) => {
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const why = flight.count > 0 ? UPLOADING : !text.trim() && !draftOf(ctx).media_files.length ? EMPTY_TEXT : "";
    post.disabled = !!why;
    if (why) post.title = why;
    else post.removeAttribute("title");
  };
  const refresh = () => {
    sync(textOf(editor));
    media();
  };
  flight.refresh = refresh;
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };

  const show = (text: string, html?: string) => {
    if (html) setOfHtml(editor, html);
    else
      editor.replaceChildren(
        ...text.split("\n").map((line) => {
          const p = doc.createElement("p");
          p.append(line || doc.createElement("br"));
          return p;
        }),
      );
    sync(text);
  };
  const html = () => (hasFormatting(editor) ? ofHtml(editor) : undefined);
  const priceBtn = doc.querySelector<HTMLElement>(PRICE_BTN);
  if (priceBtn) priceBtn.style.display = ctx.priceLimits ? "" : "none";
  doc.getElementById(POST_AS)?.remove();
  if (ctx.postAs && !home) {
    const as = doc.createElement("span");
    as.id = POST_AS;
    as.textContent = `as ${ctx.postAs}`;
    as.style.cssText = `color:${GREY};font-size:13px;margin-right:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px`;
    post.before(as);
  }
  show(draftOf(ctx).text, draftOf(ctx).html);
  summary();
  media();

  const onInput = (ev: Event) => {
    if (!(ev.target as Element | null)?.closest?.(EDITOR)) return;
    const text = textOf(editor);
    sync(text);
    update({ text, html: html() });
  };

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest("[data-oi-clear]")) {
      ev.preventDefault();
      return update(NO_EXTRAS);
    }
    const remove = target.closest<HTMLElement>("[data-oi-remove-media]");
    if (remove) {
      ev.preventDefault();
      return update(dropMediaAt(draftOf(ctx), Number(remove.dataset.oiRemoveMedia)));
    }
    if (target.closest("[data-oi-discard]")) {
      ev.preventDefault();
      if (keep) clearDraft(keep.storage, keep.accountId);
      show("");
      summary();
      return media();
    }
    if (target.closest(POST) !== post) return;
    ev.preventDefault();
    if (!handlers) return note(doc, post, SELECT_MODEL);
    if (post.disabled) return;
    const body = collectPost(textOf(editor), { ...draftOf(ctx), html: html() });
    if (typeof body === "string") return note(doc, post, body, true);
    const failed = draftOf(ctx).upload_failed;
    if (failed && !(handlers.confirm?.(uploadFailed(failed)) ?? false)) return;
    const editing = draftOf(ctx).edit_id;
    if (editing && !body.posted_at && !body.save_for_later && !(handlers.confirm?.(PUBLISH_EDITED) ?? false)) return;
    post.disabled = true;
    doc.getElementById("oi-note")?.remove();
    (editing && handlers.editPost ? handlers.editPost(editing, body) : handlers.createPost(body)).then(
      () => {
        if (keep) clearDraft(keep.storage, keep.accountId);
        if (editing) return handlers.navigate(body.save_for_later ? SFL_POSTS : `${QUEUE}?date=${localIso(wallClock(new Date(body.posted_at!), ctx.zone)).slice(0, 10)}`);
        show("");
        summary();
        media();
        for (const input of doc.querySelectorAll<HTMLInputElement>(`${VOTE_ROW} ${OPTION}`)) input.value = "";
        for (const r of doc.querySelectorAll<HTMLInputElement>(`${VOTE_ROW} input[type='radio']`)) r.checked = false;
        const due = doc.querySelector(`${VOTING_PIECE} .b-post-piece__value`);
        if (due) due.textContent = daysText(VOTING_DAYS);
        handlers.posted?.();
        toast(doc, body.save_for_later ? SAVED_TOAST : body.posted_at ? `${SCHEDULED_TOAST} ${when(wallClock(new Date(body.posted_at), ctx.zone))}` : POSTED_TOAST);
      },
      (e) => {
        sync(textOf(editor));
        note(doc, post, `Could not ${editing ? "save" : "post"}: ${message(e)}`, true);
      },
    );
  };

  if (!page.endsWith(`/${PERIOD_PAGE}`) && draftOf(ctx).period_for) update({ period_for: undefined });
  const unbindDialog = Object.hasOwn(DIALOGS, page) ? DIALOGS[page](doc, ctx, update, page) : () => {};
  const unbindRecord =
    ctx.newWrites
      ? bindRecorder(doc, ctx.draftId ?? ctx.accountId ?? "", (files, anchor) => mediaTaker(doc, anchor, ctx, () => draftOf(ctx), update, uploading)(files), !!handlers)
      : home
        ? () => {}
        : bindRecordPopup(doc);
  const unbindSearch = bindFeedSearch(doc, ctx);
  const unbindAddMedia = bindAddMedia(doc, ctx, () => draftOf(ctx), update, uploading, SELECT_MODEL, POST_PICK);
  const unbindOverflow = bindActionsOverflow(doc);
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    if (flight.refresh === refresh) flight.refresh = undefined;
    doc.getElementById(POST_AS)?.remove();
    unbindRecord();
    unbindSearch();
    unbindDialog();
    unbindAddMedia();
    unbindOverflow();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
}

const MORE_ACTIONS = "oi-actions-more";

export function bindActionsOverflow(doc: Document): () => void {
  const actions = doc.querySelector<HTMLElement>(".b-make-post__actions");
  const btns = actions?.querySelector<HTMLElement>(".b-make-post__actions__btns");
  const box = actions?.parentElement;
  if (!actions || !btns || !box) return () => {};
  const more = doc.createElement("button");
  more.type = "button";
  more.id = MORE_ACTIONS;
  more.className = "g-btn m-with-round-hover m-icon m-icon-only m-gray m-sm-size has-tooltip";
  more.setAttribute("aria-label", "More");
  more.setAttribute("aria-haspopup", "true");
  more.setAttribute("data-oi-wired", "");
  more.innerHTML = '<svg class="g-icon" aria-hidden="true"><use href="#icon-more" xlink:href="#icon-more"></use></svg>';
  const moved = () => [...btns.querySelectorAll<HTMLElement>(":scope > [data-oi-overflow]")];
  const restore = () => {
    for (const b of moved()) {
      b.style.display = "";
      b.removeAttribute("data-oi-overflow");
    }
    more.remove();
  };
  const layout = () => {
    // Only More's own menu: a resize must not close another menu just opened (Text Color's).
    if (more.getAttribute("aria-expanded") === "true") closeMenu(doc);
    restore();
    if (actions.offsetWidth <= box.clientWidth) return;
    btns.append(more);
    const shown = () => [...btns.children].filter((c): c is HTMLElement => c !== more && (c as HTMLElement).style.display !== "none");
    for (let left = shown(); left.length && actions.offsetWidth > box.clientWidth; left = shown()) {
      const last = left[left.length - 1];
      last.style.display = "none";
      last.setAttribute("data-oi-overflow", "");
    }
  };
  const onMore = (ev: Event) => {
    ev.preventDefault();
    ev.stopPropagation();
    const items = moved();
    showMenu(doc, more, [{ name: "actions", radio: false, options: items.map((b, i) => ({ value: String(i), label: b.getAttribute("aria-label") ?? "", icon: b.querySelector("use")?.getAttribute("href")?.replace(/^#/, "") })) }], (_g, v) => items[Number(v)]?.click());
  };
  more.addEventListener("click", onMore);
  layout();
  const win = doc.defaultView as (Window & typeof globalThis) | null;
  const observer = win?.ResizeObserver ? new win.ResizeObserver(() => layout()) : null;
  observer?.observe(box);
  return () => {
    observer?.disconnect();
    more.removeEventListener("click", onMore);
    closeMenu(doc);
    restore();
  };
}

const flights = new Map<string, UploadsInFlight>();
const flightOf = (accountId: string) => {
  if (!flights.has(accountId)) flights.set(accountId, { count: 0 });
  return flights.get(accountId)!;
};

export function useOfPost(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const path = /^\/of-mirror\/pages\/((?:new-post|home)\/(?:index|state-[^/]+))\.html$/.exec(src)?.[1] ?? "";
  const draftId = accountId && path.startsWith("home/") ? homeDraft(accountId) : undefined;
  const qc = useQueryClient();
  const { mutateAsync: createPost } = useMutation({
    mutationFn: (body: CreatePostBody) => relay.post("/api/of/v2/posts", body, { accountId }),
  });
  const { mutateAsync: savePost } = useMutation({
    mutationFn: ({ id, body }: { id: string; body: CreatePostBody }) => relay.put(`/api/of/v2/queue/posts/${encodeURIComponent(id)}`, body, { accountId }),
  });
  const zone = useAgencyZone();
  const { mutateAsync: createLabel } = useMutation({
    mutationFn: (name: string) => relay.post<{ id?: number }>(LABELS, { name }, { accountId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, LABELS] }),
  });
  const params = useSearchParams();
  const tagPage = path === TAG_PAGE || path === HOME_TAGS;
  const tagView = tagViewOf(tagPage ? params : new URLSearchParams());
  const tags = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagView), tagPage));
  const tagItems = accountId ? (tags.data?.items ?? rowsOf<TaggedFriendUser>(tags.data)) : undefined;
  const keep = typeof window === "undefined" ? null : keepOf({ storage: window.sessionStorage, accountId, draftId });
  const draftLabels = !!path && !!keep && !!loadDraft(keep.storage, keep.accountId).label_ids?.length;
  const labels = useQuery(mirrorQuery<PostLabelsResp>(accountId, LABELS, path === LABEL_PAGE || draftLabels));
  const labelItems = accountId && labels.data ? labelsOf(labels.data) : undefined;
  const labelSort = labels.data && !Array.isArray(labels.data) ? { sort: (labels.data as { sort?: string }).sort, order: (labels.data as { order?: string }).order } : undefined;
  const { mutateAsync: addVaultStory } = useMutation({
    mutationFn: (body: VaultStoryBody) => relay.post(STORIES, body, { accountId }),
    onSuccess: () => refetchOwnStories(qc, accountId),
  });
  const vaultPage = path === VAULT_DIALOG || path === HOME_VAULT;
  const vault = useQuery(mirrorQuery(accountId, vaultMediaOf(params), vaultPage));
  const vaultItems = accountId ? rowsOf<VaultMedia>(vault.data) : undefined;
  const lists = useQuery(mirrorQuery<{ sort?: string; order?: string }>(accountId, VAULT_LISTS, vaultPage)).data;
  const folderSort = lists ? { sort: lists.sort, order: lists.order } : undefined;
  const me = useQuery(ofMeQuery(accountId)).data;
  const priceLimits = useMemo(() => postPriceLimits(me), [me]);
  const postAs = me?.name || me?.username || undefined;
  const meId = me?.id ?? undefined;
  const tagKey = JSON.stringify(tagView);
  const sortKey = JSON.stringify([labelSort, folderSort]);
  const newWrites = useOfmNewWrites(!!path, accountId);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !path) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const navigate = (href: string) => router.push(href);
      const upload = (file: File) => relay.uploadFile<VaultUploadResp>("/api/of/v2/upload", file, "file", { accountId });
      const posted = () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] });
      const sorts = JSON.parse(sortKey) as [PostContext["labelSort"] | null, PostContext["folderSort"] | null];
      const refetch = (path: string) => () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, path] });
      const tools: Partial<PostHandlers> = {
        sortLabels: (sort, order) => relay.post(`${LABELS}/sort`, { sort, order }, { accountId }).then(refetch(LABELS)),
        sortFolders: (sort, order) => sortOfFolders(accountId!, { sort, order }).then(refetch(VAULT_LISTS)),
        toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
        inviteGuest: (name) => relay.post("/api/of/v2/guests", { name }, { accountId }),
        ...feedSearchHandlers(accountId),
      };
      unbind = doc?.body
        ? bindPost(doc, path, {
            handlers: accountId
              ? { createPost, editPost: (id, body) => savePost({ id, body }).then((r) => (posted(), r)), confirm: (text) => window.confirm(text), createLabel, upload, addVaultStory, navigate, posted, ...tools }
              : null,
            storage: window.sessionStorage,
            accountId,
            tagItems,
            labelItems,
            vaultItems,
            vaultView: viewOf(params),
            uploads: accountId ? flightOf(draftId ?? accountId) : undefined,
            draftId,
            priceLimits,
            postAs,
            zone,
            meId,
            tagView: JSON.parse(tagKey) as TagView,
            labelSort: sorts[0] ?? undefined,
            folderSort: sorts[1] ?? undefined,
            newWrites,
          })
        : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, accountId, draftId, qc, createPost, savePost, createLabel, addVaultStory, router, tagItems, labelItems, vaultItems, params, priceLimits, postAs, zone, meId, tagKey, sortKey, newWrites]);
}

