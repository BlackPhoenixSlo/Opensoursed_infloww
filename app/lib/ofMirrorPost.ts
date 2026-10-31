"use client";

/**
 * Write-through for the New post composer (new-post and every new-post/state-* Mirror page).
 * Text or media enables Post, as OF's (a disabled Post's tooltip says why); the text is the Post draft, kept per Creator in
 * sessionStorage (`oi:new-post:<accountId>`) and restored on every new-post page, so a move to a
 * State page and back keeps it. Post sends exactly one POST /api/of/v2/posts with the Known body
 * {text, media_files, price} (the Relay's _CreatePostBody subset, as PostComposer sends it),
 * then clears the draft and stays: the composer empties and OF's toast says "Your post has been published" ("…is
 * scheduled for …", "…has been saved for later"). A failure re-enables Post, shows the Relay's own
 * text in a red note and keeps the draft. "as <model>" by Post names the model it goes to. In All models New post shows
 * the first model (OfMirrorFrame's standInModel), so the composer, its dialogs and Post are that model's; with no model at
 * all, Post sends nothing and shows "Select a model to save changes" and no draft is stored. All wiring is runtime DOM
 * (ADR-0006).
 *
 * Post price (new-post/state-price, OF's ModalPostPrice): the price button shows where OF's does (postPriceLimits: a
 * free page whose users/me allows prices); Save keeps a price within users/me's postMinPrice..postMaxPrice (empty: free)
 * on the draft and Post sends it. A price disables Expiration period and Fundraising target, and either of those the
 * price button, as OF's composer.
 *
 * Home's composer (home/index and its state-schedule, state-tag-people, state-vault, state-poll, state-quiz,
 * state-expiration, state-target and state-format-text pages: New post's dialogs and panels over Home) is the same
 * composer with its own draft (`oi:new-post:home:<accountId>`) and upload flight. It never leaves Home: its dialogs
 * return to Home (a poll's duration to Home's poll panel), and a sent Post clears the composer, refetches the Creator's Mirror data (the new post shows at
 * the top of the feed) and shows the same toast.
 *
 * Schedule (new-post/state-schedule): the captured vue-datetime calendar is re-rendered for the
 * draft's month (or the current month), past days disabled; the time tab takes a typed time. Next
 * stores `posted_at` (local ISO with offset) and returns to the composer, which then shows a
 * "Scheduled for … · Clear" line; Post sends `posted_at`.
 *
 * Tag other creators (new-post/state-tag-people): with a single Creator, the dialog lists the Creator's taggable
 * creators from GET /api/of/v2/posts/tagged-friend-users in OF's own row markup (the examples hidden); a checked row
 * is a Co-tag (`tagged_users`, OF user ids), named in the summary ("Tagged: …") and sent with Post. While the list
 * is loading, after it failed and in All-Creators scope the dialog has no rows (the captured examples never show).
 *
 * Add media from vault (new-post/state-vault): ofMirrorData shows the Creator's vault media, its picked tiles marked from
 * the draft; a tile click picks or unpicks it (its vault id in the draft's `media_files`, its picture in `thumbs`, in click
 * order). An example tile, or any tile in All-Creators scope, sends nothing and gives "Select a model". Its search box hides
 * the real tiles whose date label and AI text (description, tags) lack the query; it never touches the draft. Every new-post
 * page shows the picks as a row of 64px thumbs above the toolbar, and Post sends their ids as `media_files`. The dialog's
 * "Add to story" publishes the one picked vault item as the Creator's Story (POST /api/of/v2/stories: a photo by its full
 * picture, which the Relay re-uploads, anything else by its vault id, as OF's web client does).
 *
 * Add media (every composer page, Single-Creator scope): OF's button opens a hidden picker taking several photos, videos and
 * audio files at once (POST_PICK); each picked file uploads through POST /api/of/v2/upload, one after another in the picked
 * order, and an accepted upload's `send_with` entries are appended to the draft's `media_files` as the Relay returned them,
 * with a thumb from the browser's own copy of the file (a `blob:` URL; an audio file's is OF's grey square). Post stays
 * disabled while any upload is in flight.
 *
 * Add to story (every Mirror page with a story strip; OF's own tile is on home, new-post and their State pages): a click
 * on the tile opens a hidden image or video picker; the picked file is published as the Creator's Story through one multipart
 * POST /api/of/v2/stories/upload (part `file`); the tile is disabled until the upload settles, then "Added to story" shows under the strip (and the Creator's own stories are
 * read again, so Home's strip shows the new one), or a red
 * "Could not add: <message>" note stays; either way the picker is reset so the same file can be picked again. A picked file
 * that is neither image/* nor video/* (an empty type included) sends nothing and shows a red "Could not add: choose an image
 * or a video"; a cancelled picker sends nothing and shows nothing. All-Creators scope: no picker, the select-a-model note.
 *
 * Post extras (each saved on the draft, named in the composer summary, sent with Post; the summary's Clear drops them all):
 * Save for Later (state-schedule) sends `save_for_later` instead of a date; the poll
 * and quiz panels (state-poll, state-quiz) send their typed options (`voting_*`, a quiz's correct row from its radio; "+ Add
 * another option" adds a row, a row's delete removes it while more than two are left); the panel's "Poll · 7 days" piece
 * opens EXPIRATION PERIOD for the poll's length (`voting_due`, OF's 7-day default, No limit none), as OF's composer does;
 * EXPIRATION PERIOD's Save sends `expire_days` (a tab or a typed
 * number up to OF's 30, No limit none); Fundraising target's Save sends `fund_raising_target` (minimum $10); ADD LABELS lists the
 * Creator's own post labels from GET /api/of/v2/labels (not OF's Archive and Private Archive), a checked row is a `label_ids` pick, and NEW LABEL opens a name field
 * whose Save sends POST /api/of/v2/labels {name} and picks the new label. The Relay maps these names to OF's own keys.
 *
 * OF's own tools: the Format text panel (bindFormat: Bold, Italic, Text Color, Clear Formatting, Text Size; the post text is
 * then OF's composer markup, ofMirrorFormat), Record video and Record voice (a "not supported here" popup), the poll and
 * quiz drag handles, the tag dialog's search, Sort, Release form tab, row More and Invite new user, the vault dialog's folder
 * Search and Sort and media Sort, ADD LABELS' Sort and the right column's search (bindFeedSearch: OF's users and posts
 * search, each result a link to its OF Manager page). Sort menus are ofMirrorMenu's.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, toChoice, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultMedia, type VaultUploadResp } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { linkUser, mirrorQuery, plain, rowsOf, toggleTile, userHref, VAULT_LISTS, vaultMediaOf } from "@/lib/ofMirrorData";
import { sortOfFolders } from "@/hooks/useVaultCache";
import { HOME_VAULT, homeDraft, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { floatLabel } from "@/lib/ofMirrorSettings";
import { FIELDS, TYPES, vaultHref, viewOf } from "@/lib/ofMirrorVault";
import { applyFormat, COLORS, hasFormatting, ofHtml, setOfHtml, SIZES, type FormatCommand } from "@/lib/ofMirrorFormat";
import { closeMenu, ORDER_GROUP, showMenu } from "@/lib/ofMirrorMenu";
import { GREY, localIso, message, note, NOTE_STYLE, QUEUE, READ_ONLY, schedulePill, SELECT_MODEL, textOf } from "@/lib/ofMirrorWrites";
import { useAgencyZone, wallClock } from "@/lib/ofMirrorFeeds";
import { ofPrice } from "@/lib/ofMirrorPostCard";
import { bindSchedule, clearDraft, clock, collectPost, COMPOSER, type CreatePostBody, draftOf, EMPTY_TEXT, keepOf, loadDraft, mergeSendWith, MONTHS, type PostContext, type PostDraft, type PostHandlers, type PriceLimits, saveDraft, type SearchPost, type SearchUser, type UploadsInFlight, VOTING_DAYS, WEEKDAYS } from "@/lib/ofMirrorPostDraft";
import { bindLabels, bindTags, labelsOf, type PostLabelsResp, tagsRoute, type TagView, tagViewOf } from "@/lib/ofMirrorPostTags";
import { refetchOwnStories, vaultStoryBody, type VaultStoryBody } from "@/lib/ofMirrorStory";
import { lock, RECORD_POPUP, recordPopup, toast } from "@/lib/ofMirrorToast";

/** Split out of this file; importers keep importing them from here. */
export { clearDraft, collectPost, collectSchedule, type CreatePostBody, draftKey, loadDraft, mergeSendWith, type PostContext, type PostDraft, type PostHandlers, type PriceLimits, renderCalendar, saveDraft, type SearchPost, type SearchUser, type UploadsInFlight, type Voting } from "@/lib/ofMirrorPostDraft";
export { applyFormsEmpty, applyLabelRows, applyTagRows, bindTags, labelsOf, LIST_ROW, markTagTabs, NO_RELEASE_FORMS, NOTHING_FOUND, type PostLabel, postLabelsOf, type PostLabelsResp, sortLabelRows, TAG_SORT_LABELS, type TagContext, tagHref, type TagPicks, tagRowMenu, tagsRoute, type TagView, tagViewClick, tagViewOf } from "@/lib/ofMirrorPostTags";
export { bindStory, highlightItems, NOT_STORY_MEDIA, STORY, STORY_PICK, type StoryHandlers, useOfStory, vaultStoryBody, type VaultStoryBody } from "@/lib/ofMirrorStory";
export { CARRY_MS, frameNavigate, lock, RECORD_TEXT, recordPopup, takeCarried, toast } from "@/lib/ofMirrorToast";

/**
 * OF's price button on a post (MakeFeedPost isShowPriceBtn: canChangeContentPrice, canEarn and a free page) and its
 * limits; null: no price button (a paid page, say); undefined: users/me not loaded yet (no button either).
 */
export function postPriceLimits(me: OfMe | undefined): PriceLimits | null | undefined {
  if (!me) return undefined;
  if (!me.canChangeContentPrice || !me.canEarn || Number(me.subscribePrice) !== 0) return null;
  const min = Number(me.postMinPrice);
  const max = Number(me.postMaxPrice);
  return min > 0 && max >= min ? { min, max } : null;
}

const UPLOADING = "Wait for the upload to finish";
const ONE_FOR_STORY = "Pick one vault item for the story";
/** Where an immediate post lands, a saved-for-later one, and a dialog's Save or Next. */
/** OF's toast after a post goes through (the scheduled one ends with its moment). */
export const POSTED_TOAST = "Your post has been published";
export const SCHEDULED_TOAST = "Your post is scheduled for";
export const SAVED_TOAST = "Your post has been saved for later";
/** Where a saved edit goes: the Queue, or its Posts saved for later page. */
const SFL_POSTS = "/of-manager/queue/saved-for-later-posts";
/** The summary's first part while the draft edits a queued post, and the confirm before an edit publishes it. */
export const EDITING = "Editing a scheduled post";
export const EDITING_LATER = "Editing a post saved for later";
export const PUBLISH_EDITED = "This post has no date: publish it now?";
const HOME = "/of-manager/home";
/** OF's longest expiration period and poll length, in days (its period dialog's validator). */
const MAX_DAYS = 30;
/** OF's most poll options. */
const MAX_OPTIONS = 20;
/** The fundraising target's minimum, as the captured dialog states ("Minimum $10 USD"). */
const MIN_TARGET = 10;
/** Every post extra off the draft (the summary's Clear). */
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
};
/** OF's composer editor and its Post button (every new-post page has both). */
const EDITOR = "[contenteditable][aria-label='Textbox field']";
const POST = "button[at-attr='submit_post']";
/** The format-text panel (read-only), a dialog's Save (expiration, target) and its fields. */
const FORMAT = ".js-text-editor-toolbar";
const DIALOG_SAVE = ".modal.show .modal-footer button";
const PERIOD = ".modal.show input[name='periodValue']";
const PERIOD_TAB = ".modal.show .b-tabs__nav__link";
const TARGET = ".modal.show input[at-attr='input']";
/** The poll and quiz panels: an option row, its text, its correct-answer switch (quiz), "+ Add another option" and the × that drops the poll. */
const VOTE_ROW = ".b-make-post__voting .vote-input";
const OPTION = "input[at-attr='input']";
const QUIZ_PICK = ".m-quiz-swithcer";
const ADD_OPTION = ".b-make-post__voting .new_vote_add_option";
const DROP_VOTING = ".b-make-post__voting .b-post-piece .b-dropzone__preview__delete";
/** An option row's delete button, and the panel's "Poll · 7 days" piece (a click opens its duration in the period dialog). */
const DELETE_OPTION = ".delete-vote-option";
/** An option row's drag handle (OF's m-drag-btn). */
const DRAG = ".m-drag-btn";
const VOTING_PIECE = ".b-make-post__voting .b-post-piece";
/**
 * The poll and quiz pages, and the EXPIRATION PERIOD dialog's page (also the poll's duration, as OF's composer): State
 * pages of New post and of Home (`/of-manager/<composer>/<state>`, the composer's own).
 */
const VOTING_PAGES = { 1: "state-poll", 2: "state-quiz" } as const;
const PERIOD_PAGE = "state-expiration";
/** `state`'s page under the composer `ctx` posts from (New post's, or Home's). */
const composerPage = (ctx: PostContext, state: string) => `${ctx.composer ?? COMPOSER}/${state}`;
/** The period dialog's title for a poll's or quiz's duration (OF's own strings for these are not in the capture). */
const DURATION_TITLES = { 1: " POLL DURATION ", 2: " QUIZ DURATION " } as const;
/** The tag dialog (new-post/state-tag-people). */
const TAG_PAGE = "new-post/state-tag-people";
/** Home's own copies of New post's schedule and tag dialogs (its vault dialog is ofMirrorRow's HOME_VAULT). */
const HOME_SCHEDULE = "home/state-schedule";
const HOME_TAGS = "home/state-tag-people";
/** The labels dialog (new-post/state-labels) and the Relay's post labels. */
const LABEL_PAGE = "new-post/state-labels";
const LABELS = "/api/of/v2/labels";
/** The Relay's Story route. */
const STORIES = "/api/of/v2/stories";
/** The price button (OF's `price_btn`) and its POST PRICE dialog's page; the two tools OF disables while a price is set. */
const PRICE_BTN = "[at-attr='price_btn']";
const PRICE_PAGE = "new-post/state-price";
const NOT_WITH_PRICE = "[aria-label='Expiration period'], [aria-label='Your target']";
/** The Post button's "as <model>" line. */
const POST_AS = "oi-post-as";

/** "1 day", "7 days" or "No limit" (0), as OF's poll piece and period tabs. */
const daysText = (n: number) => (n ? `${n} ${n === 1 ? "day" : "days"}` : "No limit");
/** "Tue, Oct 13, 6:30 PM": the composer summary's moment. */
const when = (d: Date) => `${WEEKDAYS[d.getDay()].slice(0, 3)}, ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}, ${clock(d)}`;

/** New post's Add media takes several files at once, audio too (OF's composer: photos, videos and audio). */
export const POST_PICK = { accept: "image/*,video/*,audio/*", multiple: true };

/** OF's "Add media" button on the composer (new-post index; its State page copies sit under the open dialog). */
const ADD_MEDIA = "button.attach_file[aria-label='Add media']";
/** The composer's row of picked media thumbs (rebuilt from the draft on every load). */
const THUMBS_ROW = "oi-post-thumbs";
/** A picker tile in the vault dialog (the folder rows' thumbnails are not). */
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
/** The vault dialog's search box, the header button that opens OF's search form and the form's Back. */
const VAULT_SEARCH = "input[name='media_vault_search']";
const OPEN_SEARCH = "button[aria-label='Search media']";
const CLOSE_SEARCH = "[at-attr='close_search']";
/** OF's mark on a page header whose search form is open (app.css, 70780.css). */
const SEARCH_OPEN = "m-search-form-visible";
/** The vault dialog's media type tabs (All, Photo, GIF, Video, Audio: ofMirrorVault's TYPES). */
const VAULT_TABS = ".modal.show .b-tabs__nav__link";

/** A dialog page's own binding: `update` saves a patch onto the draft. Returns an unbind. */
type DialogBinder = (doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string) => () => void;

/**
 * Wire the poll (`type` 1, new-post/state-poll) or quiz (2, new-post/state-quiz) panel: its rows show the draft's
 * options of that type ("+ Add another option" rows added as needed); typing saves the rows' text, and a quiz row's
 * correct-answer switch marks that row alone, as the draft's `voting` (none while every option is blank). "+ Add
 * another option" adds an empty row (OF's markup, cloned; at most 20). A row's delete removes it while more than two
 * are left (OF's minimum; a removed correct answer moves to the first row). The panel's "Poll · 7 days" piece shows the
 * draft's `voting_due` and a click on it opens the period dialog for it (`period_for`). The panel's × drops the poll and
 * its duration from the draft (its link then returns to the composer). All-Creators: a typed option or a switch is reset
 * and gives the select-a-model note, as do a delete, the piece and "+ Add another option". Returns an unbind.
 */
const bindVoting =
  (type: 1 | 2): DialogBinder =>
  (doc, ctx, update) => {
    const add = doc.querySelector<HTMLButtonElement>(ADD_OPTION);
    const first = doc.querySelector(VOTE_ROW);
    if (!add || !first) return () => {};
    const template = first.cloneNode(true) as HTMLElement;
    const rows = () => [...doc.querySelectorAll<HTMLElement>(VOTE_ROW)];
    const radio = (row: Element) => row.querySelector<HTMLInputElement>("input[type='radio']");
    /** A quiz row's correct-answer switch on or off: its radio, and OF's grey dropped from the chosen switch. */
    const pick = (row: Element, on: boolean) => {
      const r = radio(row);
      if (r) {
        r.checked = on;
        r.toggleAttribute("checked", on);
      }
      row.querySelector(QUIZ_PICK)?.classList.toggle("m-gray", !on);
    };
    /** Mark the rows' controls, and enable their deletes while more than two rows are left. */
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
      if (r) r.name = `quiz-option-oi-${++added}`; // a row's own group, as each captured row has
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

    /** The panel's rows as the draft's `voting` (none while every option is blank). */
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
      field.value = ""; // nothing was saved: show the real state again
      note(doc, field, SELECT_MODEL);
    };
    const onClick = (ev: MouseEvent) => {
      const target = ev.target as Element | null;
      if (!target?.closest) return;
      if (target.closest(DROP_VOTING)) return update({ voting: undefined, voting_due: undefined });
      // A handle only drags; a plain click says so.
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
    // OF's drag handle (its m-draggable list): a press on a row's handle carries the row; it is put before the first row
    // whose middle lies below the pointer (else last), and the release saves the new order.
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

/**
 * A dialog with one field and a Save (`field`; EXPIRATION PERIOD, Fundraising target, a poll's duration): it opens on the
 * draft's value; `read` gives the field's value for the draft, or null while it is not valid (Save is disabled then). Save
 * stores it (0 or "" as none; `voting_due` keeps 0, its No limit, and opens on OF's 7 days when unset) and returns to
 * `back` (default: the composer); All-Creators: the select-a-model note. `extra` wires anything else and returns its unbind.
 */
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

/** EXPIRATION PERIOD's days: "" (No limit) is 0; a whole 1-30 (OF's maximum) is itself; anything else is null. */
const readDays = (value: string): number | null => {
  const v = value.trim();
  const n = Number(v);
  return !v ? 0 : Number.isInteger(n) && n >= 1 && n <= MAX_DAYS ? n : null;
};
/** Its tabs (No limit, 1 day, …): a click puts its days in the field; the tab of the field's days is current. */
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
/**
 * The EXPIRATION PERIOD dialog (new-post/state-expiration): the post's `expire_days`, or, when a poll or quiz panel's
 * duration opened it (the draft's `period_for`), that poll's `voting_due`: then its title names the duration, and Save,
 * Cancel and the backdrop return to the poll or quiz panel. Returns an unbind, which puts the title and links back.
 */
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

/** POST PRICE's dollars: "" is free (0); a number within `limits` is itself; anything else (or no limits) is null. */
export const readPrice =
  (limits: PriceLimits | null | undefined) =>
  (value: string): number | null => {
    const v = value.trim().replace(/^\$/, "");
    if (!v) return 0;
    const n = Number(v);
    return limits && Number.isFinite(n) && n >= limits.min && n <= limits.max ? Math.round(n * 100) / 100 : null;
  };

/**
 * The POST PRICE dialog (new-post/state-price, OF's ModalPostPrice over the composer): it opens on the draft's price, its
 * line under the field states the Creator's minimum ("Minimum $3 USD or free", OF's), and Save keeps a price within the
 * limits on the draft and returns to the composer. As OF's isPriceInvalid, Save is disabled while the field is empty
 * (unless it clears a saved price: the post is free again) or holds the saved price. No limits (a paid page): Save
 * stays disabled.
 */
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

/** The fundraising target in dollars ("$" allowed), or null below the minimum. */
const readTarget = (value: string): number | null => {
  const n = Number(value.trim().replace(/^\$/, ""));
  return value.trim() && Number.isFinite(n) && n >= MIN_TARGET ? n : null;
};

/**
 * Wire the vault dialog's search (new-post/state-vault): Search media opens OF's search form (Back closes and clears
 * it); typing there hides (display:none) every real tile whose `data-oi-text` (ofMirrorData's date label and AI text)
 * lacks the trimmed, case-folded query, an empty query shows all, and a submit stays on the page. Search never touches
 * the draft. Returns an unbind.
 */
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

/**
 * Wire the vault dialog (new-post/state-vault): a click on a real tile (`data-oi-media`, stamped by ofMirrorData) adds or
 * removes its vault id and picture in the draft, and its mark follows the draft; an example tile or All-Creators scope
 * gives the select-a-model note. Its search is `bindVaultSearch`. An "Add to story" button (OF's footer button markup)
 * before Close publishes the one picked vault item as the Creator's Story (`vaultStoryBody`): disabled while it sends,
 * then "Added to story", or a red "Could not add: …"; none or several picked: a red "Pick one vault item for the story"
 * and nothing is sent; All-Creators: the select-a-model note. The pick stays in the Post draft. Its media type tabs show
 * the view's type and a click opens the dialog on that type (`page`'s own route, the folder kept), as the Vault page's
 * tabs do. Returns an unbind, which removes the button.
 */
function bindVault(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string): () => void {
  const view = ctx.vaultView ?? {};
  const tabs = [...doc.querySelectorAll<HTMLElement>(VAULT_TABS)];
  tabs.forEach((t, i) => {
    const on = (TYPES[i] ?? null) === (view.type ?? null);
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    t.setAttribute("data-oi-wired", "");
  });
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
    // In the dialog's footer: a note in the grid would take a tile's place.
    if (!ctx.handlers || !id) return note(doc, doc.querySelector(".modal-footer a") ?? tile, SELECT_MODEL);
    const { media_files, thumbs } = draftOf(ctx);
    const at = media_files.indexOf(id);
    if (at < 0) {
      update({ media_files: [...media_files, id], thumbs: [...thumbs, tile.querySelector(".b-photos__item__img")?.getAttribute("src") ?? ""] });
    } else {
      update({ media_files: media_files.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
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

/** OF's vault folder Sort (the Vault page's captured menu: sort default | name | recent | media | custom, and order). */
const FOLDER_SORTS = [
  { value: "default", label: "Default" },
  { value: "name", label: "Name" },
  { value: "recent", label: "Recent" },
  { value: "media", label: "Media" },
  { value: "custom", label: "Custom" },
];

/** The folder rows ofMirrorData drew (not "All media"), in the dialog's folder column. */
const folderRows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".modal.show .l-sidebar-column .b-rows-lists__item[data-oi-data]")];
const folderName = (r: Element) => r.querySelector(".b-rows-lists__item__name")?.textContent?.trim() ?? "";

/** The folder rows by name in `order`, moved in place (OF's other sorts come back from the Relay, already in its order). */
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

/**
 * The vault dialog's own tools: the folder column's Search (a field in its header; typing, 400 ms after it stops, opens the
 * dialog with ?slist=, which ofMirrorData sends to GET /vault/lists as OF's `query`, as the Vault page's), the folder Sort (OF's menu; a pick sends OF's POST
 * /vault/lists/sort, and Name re-orders the rows at once) and the media Sort (OF's fields Recent, Most liked, Highest
 * tips, Buyers and the order: the dialog with ?field= and ?sort=, as the Vault page's). A chat's vault dialog has them
 * too (`stay` keeps its ?chat=). Returns an unbind.
 */
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
  // A chat's dialog comes greyed by the generator ("Not available in Inflowwww yet"): these tools run there too.
  const greyed = [folderSearch, folderSort, mediaSort, submit].filter((b): b is HTMLButtonElement => !!b?.disabled);
  const tips = greyed.map((b) => b.getAttribute("title"));
  for (const b of greyed) {
    b.disabled = false;
    b.removeAttribute("title");
  }
  // The media column's title names its sort (OF's "Recent", "Most liked", …), as the Vault page's.
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
      showMenu(doc, b, [{ name: "sort", value: sorted.sort, options: FOLDER_SORTS }, ORDER_GROUP(sorted.order)], (g, v) => {
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

/**
 * Wire OF's "Add media" (any composer page, a chat's too: `media` reads its draft's picks): a click opens a hidden one-file image/video picker (All-Creators scope: the
 * select-a-model note). The picked file uploads at once; an accepted upload's `send_with` is appended to the draft's
 * `media_files` (`mergeSendWith`), each entry with a thumb from the file's object URL, made in the app's window (the
 * frame's document is replaced on every State page). The picker is cleared so the same file can be picked again, and
 * further picks are allowed while one uploads; `uploading` is told when each upload starts (+1) and settles (-1).
 * A refused upload (`ready` not true) or a thrown one shows a red "Could not upload: …" note and attaches nothing.
 * Returns an unbind, which removes the picker.
 */
export function bindAddMedia(
  doc: Document,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => Pick<PostDraft, "media_files" | "thumbs">,
  update: (patch: Pick<PostDraft, "media_files" | "thumbs">) => void,
  uploading: (n: 1 | -1) => void,
  /** The note when nothing can be sent (`ctx.handlers` null): All-Creators scope's by default. */
  none: string = SELECT_MODEL,
  /** What the picker takes (a chat's: one image or video; New post's: POST_PICK). */
  pick: { accept: string; multiple: boolean } = { accept: "image/*,video/*", multiple: false },
  /** Told of each attached file (a chat counts its voice notes by MIME). */
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
  input.setAttribute("data-oi-wired", ""); // the field whose file Add media sends: not bindWrites' change path
  doc.body.append(input);
  button.setAttribute("data-oi-wired", "");

  const onClick = (ev: Event) => {
    ev.preventDefault();
    if (handlers) input.click();
    else note(doc, button, none);
  };
  const take = mediaTaker(doc, button, ctx, media, update, uploading, done);
  const onChange = () => {
    // The File comes from the frame's realm: no `instanceof File` on it.
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

/**
 * Add media's upload of `files` (a pick, a drop, a recording): each file goes to POST /api/of/v2/upload, one after
 * another (the draft keeps their order), and an accepted upload's `send_with` is appended to the draft's `media_files`
 * with a thumb from the file's object URL; `done` is told of each attached file. Every file counts as in flight
 * (`uploading`) from the start. A refused or failed upload shows a red "Could not upload: …" note after `anchor` and
 * attaches nothing. No `ctx.handlers` (or no files): nothing is sent.
 */
export function mediaTaker(
  doc: Document,
  anchor: Element,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => Pick<PostDraft, "media_files" | "thumbs">,
  update: (patch: Pick<PostDraft, "media_files" | "thumbs">) => void,
  uploading: (n: 1 | -1) => void,
  done?: (file: File) => void,
): (files: File[]) => void {
  const send = (file: File) =>
    ctx
      .handlers!.upload(file)
      .then(
        ({ ready, send_with, note: why }) => {
          if (ready !== true) return note(doc, anchor, `Could not upload: ${why || "upload not ready"}`, true);
          if (!send_with.length) return;
          const { media_files, thumbs } = media();
          const thumb = proxyImage(URL.createObjectURL(file), ctx.accountId);
          update({ media_files: mergeSendWith(media_files, send_with), thumbs: [...thumbs, ...send_with.map(() => thumb)] });
          done?.(file);
        },
        (e) => note(doc, anchor, `Could not upload: ${message(e)}`, true),
      )
      .finally(() => uploading(-1));
  return (files) => {
    if (!files.length || !ctx.handlers) return;
    // Every file counts as in flight at once (Post waits for all); they upload one after another.
    files.forEach(() => uploading(1));
    let chain: Promise<unknown> | null = null;
    for (const file of files) chain = chain ? chain.then(() => send(file)) : send(file);
  };
}

/**
 * The Format text panel (new-post/state-format-text, OF's TextEditorToolbar): Bold, Italic and Clear Formatting format
 * the editor's selection; Text Color and Text Size open OF's lists (ofMirrorMenu) and format it with the picked one.
 * The editor then holds OF's own markup (ofMirrorFormat), which is the post's text (bindPost saves it as the draft's
 * `html`). A press on the panel keeps the editor's selection; with nothing selected a tool says "Select some text to
 * format". All-Creators: the select-a-model note. Returns an unbind.
 */
const bindFormat: DialogBinder = (doc, ctx) => {
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const panel = doc.querySelector<HTMLElement>(FORMAT);
  if (!editor || !panel) return () => {};
  return bindFormatPanel(doc, editor, panel, () => (ctx.handlers ? null : SELECT_MODEL));
};

/** OF's Format text `panel` over `editor` (New post's dialog, a chat's composer); `blocked`: the note when no write may be made. */
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
  const apply = (cmd: FormatCommand) => {
    const why = blocked();
    if (why) return note(doc, panel, why);
    if (saved) {
      editor.focus();
      const sel = doc.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(saved);
    }
    if (!applyFormat(editor, cmd)) return note(doc, panel, "Select some text to format");
    onSelection();
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const onDown = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (t?.closest && panel.contains(t) && !t.closest("a[href]")) ev.preventDefault();
  };
  const onClick = (ev: MouseEvent) => {
    const t = (ev.target as Element | null)?.closest?.<HTMLElement>("[aria-label]");
    if (!t || !panel.contains(t)) return;
    const label = t.getAttribute("aria-label");
    if (label === "Bold" || label === "Italic" || label === "Clear Formatting") {
      ev.preventDefault();
      return apply({ kind: label === "Bold" ? "bold" : label === "Italic" ? "italic" : "clear" });
    }
    if (label === "Text Color" && color) {
      ev.preventDefault();
      const options = COLORS.map((c) => ({ value: c.cls, label: c.label, className: c.cls }));
      showMenu(doc, color, [{ name: "color", radio: false, options }], (_, cls) => {
        apply({ kind: "color", cls });
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
        apply({ kind: "size", cls });
        if (shown) shown.textContent = SIZES.find((x) => x.cls === cls)?.label ?? "Default";
      });
    }
  };
  doc.addEventListener("selectionchange", onSelection);
  doc.addEventListener("mousedown", onDown);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("selectionchange", onSelection);
    doc.removeEventListener("mousedown", onDown);
    doc.removeEventListener("click", onClick);
    closeMenu(doc);
  };
}

/** The composer tools Home's composer shares with New post: each a State page of both (home/<state>, new-post/<state>). */
const SHARED_DIALOGS: Record<string, DialogBinder> = {
  [VOTING_PAGES[1]]: bindVoting(1),
  [VOTING_PAGES[2]]: bindVoting(2),
  [PERIOD_PAGE]: bindPeriod,
  "state-target": bindValueDialog("fund_raising_target", TARGET, readTarget),
  "state-format-text": bindFormat,
};

/** new-post/state-* (and Home's copies of most of them) page -> its dialog's binding. */
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

/** The composer's Record video and Record voice buttons. */
const RECORD = "button.b-chat__video-record-btn, button[aria-label='Record voice']";

/** The right column's search box (OF's "Search users or posts"), its submit, and the results list under it. */
const FEED_SEARCH = "input[name='feed-search-input']";
const SEARCH_RESULTS = "oi-search-results";

/** Where a search result opens (userHref): a user's OF profile; a post, My profile when it is the model's own, else its
 *  author's OF profile. */
export function searchHref(kind: "user" | "post", item: SearchUser | SearchPost, meId?: number | string): string | null {
  const me = meId == null ? null : String(meId);
  return kind === "user" ? userHref(item as SearchUser, me) : userHref((item as SearchPost).author, me);
}

/** A search response's rows: a bare array, or OF's `{list}` / `{items}`. */
const rowsIn = <T,>(r: unknown): T[] => (Array.isArray(r) ? (r as T[]) : ((r as { list?: T[]; items?: T[] } | null)?.list ?? (r as { items?: T[] } | null)?.items ?? []));

/**
 * Wire the right column's search (New post's and Home's): typing (400 ms after it stops) runs OF's users search and posts
 * search, and a list under the box shows "Users" and "Posts" rows, each a link to its OF profile or My profile (searchHref); the
 * submit (Enter or the search button) runs it at once and never reloads the frame; an empty box clears the list.
 * All-Creators: the select-a-model note. Returns an unbind.
 */
function bindFeedSearch(doc: Document, ctx: PostContext): () => void {
  const input = doc.querySelector<HTMLInputElement>(FEED_SEARCH);
  if (!input) return () => {};
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
    // OF's names and texts come HTML-escaped (and a post's text as markup): shown as text.
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
    if (!q) return results()?.remove();
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
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
    results()?.remove();
  };
}

/**
 * Wire the composer of a new-post Mirror page (`page`: its path under of-mirror/pages, e.g.
 * "new-post/index" or "new-post/state-schedule") in `doc`. Returns an unbind.
 */
export function bindPost(doc: Document, page: string, given: PostContext): () => void {
  // Home's composer posts in place, and its dialogs (Home's own State pages) return to Home.
  const home = page.startsWith("home/");
  const ctx: PostContext = { ...given, composer: home ? HOME : COMPOSER };
  const { handlers } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const post = doc.querySelector<HTMLButtonElement>(POST);
  if (!editor || !post) return () => {};
  const keep = keepOf(ctx);
  post.setAttribute("data-oi-wired", "");

  /** A Co-tag's name from the Relay's list, else its id. */
  const tagName = (id: number) => {
    const u = ctx.tagItems?.map(toChoice).find((t) => t.id === id);
    return u ? u.name : String(id);
  };
  /** The picked labels' names from the Relay's list ("Summer, Beach"); null while any is unknown (the summary counts them). */
  const labelNames = (ids: number[]) => {
    const names = ids.map((id) => ctx.labelItems?.find((l) => Number(l.id) === id)?.name);
    return names.every(Boolean) ? names.join(", ") : null;
  };
  /** "Scheduled for … · Tagged: … · Poll: … · Clear" under the editor while the draft has extras (note's grey, persistent). */
  const summary = () => {
    const { posted_at: at, save_for_later: later, tagged_users: tags, voting, voting_due: due, expire_days: days, fund_raising_target: target, label_ids: labels, price, edit_id: editing } = draftOf(ctx);
    // OF's tools a price rules out (and the price button while they are set).
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
    // Editing a queued post: Discard drops the whole draft (the queued post stays as it is).
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
  /**
   * The draft's picked media as one row of 64px squares directly before the actions bar, in click order: each OF's vault
   * tile picture markup with the draft's thumb as its src. A picture that fails to load (a video, or a `blob:` URL dead
   * after a full reload) leaves a plain square in OF's grey; its media stays in the draft. Each square's X drops that
   * file. Rebuilt from the draft; no row while nothing is picked.
   */
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
        // OF's X on an attached file's preview: it drops that file from the post.
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
  /** Save `patch` onto this scope's draft (none is kept in All-Creators scope) and show it in the summary and the media row. */
  const update = (patch: Partial<PostDraft>) => {
    if (keep) saveDraft(keep.storage, keep.accountId, { ...draftOf(ctx), ...patch });
    summary();
    if (patch.thumbs) media();
    if (patch.media_files) sync(textOf(editor));
  };

  /** Add media's uploads in flight (an earlier bind's may still be running). */
  const flight = ctx.uploads ?? { count: 0 };
  /**
   * OF's placeholder marks follow the editor's text; Post is enabled while there is text or media and no upload is in
   * flight, and a disabled Post says why (its tooltip).
   */
  const sync = (text: string) => {
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const why = flight.count > 0 ? UPLOADING : !text.trim() && !draftOf(ctx).media_files.length ? EMPTY_TEXT : "";
    post.disabled = !!why;
    if (why) post.title = why;
    else post.removeAttribute("title");
  };
  /** Redraw this bind from the saved draft: Post state and the media row (an earlier bind's upload may have saved to it). */
  const refresh = () => {
    sync(textOf(editor));
    media();
  };
  flight.refresh = refresh;
  /** An upload started (+1) or settled (-1): the current bind is refreshed from the saved draft. */
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };

  /** The editor shows `text`, one <p> per line, or the draft's formatted `html` (OF's markup). */
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
  /** The editor's formatted text as OF's markup, or undefined while it has no formatting. */
  const html = () => (hasFormatting(editor) ? ofHtml(editor) : undefined);
  // OF shows the price button only where a post can have a price (postPriceLimits).
  const priceBtn = doc.querySelector<HTMLElement>(PRICE_BTN);
  if (priceBtn) priceBtn.style.display = ctx.priceLimits ? "" : "none";
  // Which model New post's Post goes to, by the button (All models posts as the model the page shows).
  doc.getElementById(POST_AS)?.remove();
  if (ctx.postAs && !home) {
    const as = doc.createElement("span");
    as.id = POST_AS;
    as.textContent = `as ${ctx.postAs}`;
    as.style.cssText = `color:${GREY};font-size:13px;margin-right:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px`;
    post.before(as);
  }
  // This scope's draft (a rebind after a scope change replaces the other scope's text).
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
      const at = Number(remove.dataset.oiRemoveMedia);
      const { media_files, thumbs } = draftOf(ctx);
      return update({ media_files: media_files.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
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
    const editing = draftOf(ctx).edit_id;
    // An edited post with no date and not saved for later goes out at once: OF asks too (confirm_post_right_now).
    if (editing && !body.posted_at && !body.save_for_later && !(handlers.confirm?.(PUBLISH_EDITED) ?? false)) return;
    post.disabled = true;
    doc.getElementById("oi-note")?.remove();
    (editing && handlers.editPost ? handlers.editPost(editing, body) : handlers.createPost(body)).then(
      () => {
        if (keep) clearDraft(keep.storage, keep.accountId);
        // Saving an edited queued post goes back to where it is listed, as OF's (the queue, or saved for later).
        // (OF opens the queue on the post's day: /my/queue/<yyyy-mm-dd>.)
        if (editing) return handlers.navigate(body.save_for_later ? SFL_POSTS : `${QUEUE}?date=${localIso(wallClock(new Date(body.posted_at!), ctx.zone)).slice(0, 10)}`);
        // The composer empties in place, OF's toast says what happened, and the Creator's reads (Home's feed, the
        // Scheduled events, the queue) are fetched again.
        show("");
        summary();
        media();
        // An open poll or quiz panel empties too: its options went with the post, and the draft no longer has them.
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

  // A poll's duration opens the period dialog only straight from its panel.
  if (!page.endsWith(`/${PERIOD_PAGE}`) && draftOf(ctx).period_for) update({ period_for: undefined });
  const unbindDialog = Object.hasOwn(DIALOGS, page) ? DIALOGS[page](doc, ctx, update, page) : () => {};
  // New post's Record video and Record voice: OF records in the browser, which the mirror does not (the popup says so).
  const records = home ? [] : [...doc.querySelectorAll<HTMLButtonElement>(RECORD)];
  for (const b of records) b.setAttribute("data-oi-wired", "");
  const onRecord = (ev: Event) => {
    ev.preventDefault();
    const b = ev.currentTarget as HTMLButtonElement;
    b.setAttribute("aria-expanded", "true");
    recordPopup(doc, () => b.removeAttribute("aria-expanded"));
  };
  for (const b of records) b.addEventListener("click", onRecord);
  const unbindSearch = bindFeedSearch(doc, ctx);
  // Every composer page: the State pages' toolbar sits under their panel, and OF's Add media works there too.
  const unbindAddMedia = bindAddMedia(doc, ctx, () => draftOf(ctx), update, uploading, SELECT_MODEL, POST_PICK);
  const unbindOverflow = bindActionsOverflow(doc);
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    if (flight.refresh === refresh) flight.refresh = undefined;
    doc.getElementById(POST_AS)?.remove();
    for (const b of records) b.removeEventListener("click", onRecord);
    doc.getElementById(RECORD_POPUP)?.remove();
    unbindSearch();
    unbindDialog();
    unbindAddMedia();
    unbindOverflow();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
}

const MORE_ACTIONS = "oi-actions-more";

/**
 * The composer toolbar on a narrow screen, as OF's MakeFeedPost resize(): while the row of action buttons is wider than
 * the composer, its last button moves into a More menu (OF's icon-more dropdown), one at a time, and comes back once
 * there is room. A More row clicks the button it stands for. Re-run on every resize (a ResizeObserver on the composer).
 * Returns an unbind, which puts every button back.
 */
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
    closeMenu(doc);
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

/** Each Creator's uploads in flight, kept for the page's lifetime so they outlive the frame and its component. */
const flights = new Map<string, UploadsInFlight>();
const flightOf = (accountId: string) => {
  if (!flights.has(accountId)) flights.set(accountId, { count: 0 });
  return flights.get(accountId)!;
};

/**
 * new-post, home and their state-* pages: bind the composer on every frame load (posts only with a single Creator). Home's
 * composer keeps its own draft and uploads, and a post from it refreshes the feed's queries.
 */
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
  // Not awaited: the new label is picked before the refetched list rebinds the dialog.
  const { mutateAsync: createLabel } = useMutation({
    mutationFn: (name: string) => relay.post<{ id?: number }>(LABELS, { name }, { accountId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, LABELS] }),
  });
  const params = useSearchParams();
  // Fetched only on the tag dialog (its view: search, sort, filter, tab); its cached rows also name the Co-tags in the
  // composer summary.
  const tagPage = path === TAG_PAGE || path === HOME_TAGS;
  const tagView = tagViewOf(tagPage ? params : new URLSearchParams());
  const tags = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagView), tagPage));
  const tagItems = accountId ? (tags.data?.items ?? rowsOf<TaggedFriendUser>(tags.data)) : undefined;
  // Fetched on the labels dialog, and on the composer while the draft has labels: the summary names them.
  const keep = typeof window === "undefined" ? null : keepOf({ storage: window.sessionStorage, accountId, draftId });
  const draftLabels = !!path && !!keep && !!loadDraft(keep.storage, keep.accountId).label_ids?.length;
  const labels = useQuery(mirrorQuery<PostLabelsResp>(accountId, LABELS, path === LABEL_PAGE || draftLabels));
  const labelItems = accountId && labels.data ? labelsOf(labels.data) : undefined;
  const labelSort = labels.data && !Array.isArray(labels.data) ? { sort: (labels.data as { sort?: string }).sort, order: (labels.data as { order?: string }).order } : undefined;
  const { mutateAsync: addVaultStory } = useMutation({
    mutationFn: (body: VaultStoryBody) => relay.post(STORIES, body, { accountId }),
    onSuccess: () => refetchOwnStories(qc, accountId),
  });
  // The vault dialog's tiles' own query (ofMirrorData's), so Add to story reads the media the tiles show; its folders'
  // (their sort).
  const vaultPage = path === VAULT_DIALOG || path === HOME_VAULT;
  const vault = useQuery(mirrorQuery(accountId, vaultMediaOf(params), vaultPage));
  const vaultItems = accountId ? rowsOf<VaultMedia>(vault.data) : undefined;
  const lists = useQuery(mirrorQuery<{ sort?: string; order?: string }>(accountId, VAULT_LISTS, vaultPage)).data;
  const folderSort = lists ? { sort: lists.sort, order: lists.order } : undefined;
  // The price button and its limits, and the name by Post (the Creator's OF name; the model in All models).
  const me = useQuery(ofMeQuery(accountId)).data;
  const priceLimits = useMemo(() => postPriceLimits(me), [me]);
  const postAs = me?.name || me?.username || undefined;
  const meId = me?.id ?? undefined;
  const tagKey = JSON.stringify(tagView);
  const sortKey = JSON.stringify([labelSort, folderSort]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !path) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const navigate = (href: string) => router.push(href);
      const upload = (file: File) => relay.uploadFile<VaultUploadResp>("/api/of/v2/upload", file, "file", { accountId });
      // Home's feed, its Scheduled events and the rest of this Creator's mirror reads.
      const posted = () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] });
      const sorts = JSON.parse(sortKey) as [PostContext["labelSort"] | null, PostContext["folderSort"] | null];
      const refetch = (path: string) => () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, path] });
      const tools: Partial<PostHandlers> = {
        sortLabels: (sort, order) => relay.post(`${LABELS}/sort`, { sort, order }, { accountId }).then(refetch(LABELS)),
        sortFolders: (sort, order) => sortOfFolders(accountId!, { sort, order }).then(refetch(VAULT_LISTS)),
        toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
        inviteGuest: (name) => relay.post("/api/of/v2/guests", { name }, { accountId }),
        searchUsers: (q) => relay.get<SearchUser[]>(`/api/of/v2/users/search?q=${encodeURIComponent(q)}&limit=5`, { accountId }),
        searchPosts: (q) => relay.get<SearchPost[]>(`/api/of/v2/posts/search?query=${encodeURIComponent(q)}&limit=5`, { accountId }),
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
          })
        : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, accountId, draftId, qc, createPost, savePost, createLabel, addVaultStory, router, tagItems, labelItems, vaultItems, params, priceLimits, postAs, zone, meId, tagKey, sortKey]);
}

