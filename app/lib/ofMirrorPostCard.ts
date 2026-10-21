/**
 * What OF's post card draws beyond the captured row (ofMirrorFeeds' postRows clones it for My profile's wall, Home,
 * All bookmarks and a list's Posts tab), from OF's own Post component (app.js, build 202610161317) and the markup of a
 * live Home capture:
 * - a priced post's price beside its pin (OF's PostPrice: "$28" and the lock; another creator's opened post "Purchased
 *   for $28");
 * - another creator's priced post not opened yet: only its media it can view (none: no picture), then OF's locked block
 *   (PostPurchase: the locked media counts by type, the price and "Unlock post for $28", disabled with the tooltip: the
 *   mirror buys nothing);
 * - a post with more than one viewable file: OF's "1/N" counter on its picture;
 * - a poll or quiz (OF's PostVotingWrapper, PostVoteOption, ProgressVote and its due row), read-only: the Relay has no
 *   vote route, so a vote button is disabled with the tooltip;
 * - its viewable files stamped on the picture for the viewer (`MEDIA`, opened by ofMirrorHome's post actions), as My
 *   profile's Media tab tiles (ofMirrorFeeds).
 */

import { stillUrl } from "@/lib/ofMedia";
import type { OFMedia } from "@/lib/relay";
import type { ViewerItem } from "@/lib/ofMirrorVault";
import { NOT_YET } from "@/lib/ofMirrorWrites";

/**
 * OF's formatPrice (app.js module 748977 `QM`): "$" and the price with two decimals, ".00" dropped ("$28", "$12.50").
 * What OF prints on a post's price, its unlock button and a PPV's price.
 */
export function ofPrice(v: number | string): string {
  return `$${(Number(v) || 0).toFixed(2).replace(".00", "")}`;
}

/** A media with OF's video sources (a story's, a post's). */
export type ViewerMedia = OFMedia & { videoSources?: Record<string, string | null> | null };

/** A media's file for the viewer, through `img`: a video's or GIF's 720p, else its full file, else its still. */
export function viewerSrc(m: ViewerMedia, img: (u: string) => string): string | null {
  const url = ((m.type === "video" || m.type === "gif") && m.videoSources?.["720"]) || m.files?.full?.url || stillUrl(m);
  return url ? img(url) : null;
}

/** The viewer's items for `media` (each with a file), in order. */
export function viewerItems(media: readonly ViewerMedia[], img: (u: string) => string): ViewerItem[] {
  return media.flatMap((m) => {
    const src = viewerSrc(m, img);
    return src ? [{ src, type: m.type ?? "photo" }] : [];
  });
}

/**
 * The attribute holding a picture's viewer items (JSON), which ofMirrorHome's post actions open in the viewer. Not the
 * vault tiles' `data-oi-media` (their vault id): a vault dialog over Home would send its picks to the viewer.
 */
export const MEDIA = "data-oi-view-items";

/** Stamp `el` with `items` for the viewer (none: nothing to open, no stamp), enabling it (the generator's disabled tile). */
export function stampMedia(el: Element | null | undefined, items: ViewerItem[]) {
  if (!el || !items.length) return;
  el.setAttribute(MEDIA, JSON.stringify(items));
  el.removeAttribute("aria-disabled");
  if (el.getAttribute("title") === NOT_YET) el.removeAttribute("title");
}

/** A stamped picture's viewer items (none when unstamped or unreadable). */
export function mediaOf(el: Element): ViewerItem[] {
  try {
    const items = JSON.parse(el.getAttribute(MEDIA) ?? "[]") as ViewerItem[];
    return Array.isArray(items) ? items.filter((i) => typeof i?.src === "string") : [];
  } catch {
    return [];
  }
}

/** A poll's or quiz's option, as OF sends it on the post. */
export interface VoteOption {
  id?: number | string;
  name?: string | null;
  count?: number | null;
  isVoted?: boolean | null;
  isCorrect?: boolean | null;
}

/** A post's `voting` (OF's). */
export interface PostVoting {
  options?: VoteOption[] | null;
  total?: number | null;
  finishedAt?: string | null;
}

/** The post fields the card reads (a MirrorPost's). */
export interface CardPost {
  price?: number | string | null;
  isOpened?: boolean | null;
  media?: OFMedia[];
  /** OF's: 1 a poll, 2 a quiz. */
  votingType?: number | null;
  voting?: PostVoting | null;
  isArchived?: boolean | null;
  isDeleted?: boolean | null;
  /** What a locked post shows free (OF's `preview`: media ids, "poll"). */
  preview?: (number | string)[] | null;
}

/** Who looks at the post: the Creator's own post, or another creator's whom the Creator is subscribed to (`subscribed`). */
export interface CardViewer {
  own: boolean;
  subscribed: boolean;
}

/** A static piece of OF's markup (no data in it) as an element of `doc`. */
function markup(doc: Document, html: string): HTMLElement {
  const t = doc.createElement("template");
  t.innerHTML = html;
  return doc.importNode(t.content, true).firstElementChild as HTMLElement;
}

const icon = (name: string, cls = "g-icon", scope = "") =>
  `<svg${scope} class="${cls}" data-icon-name="${name}" aria-hidden="true"><use href="#${name}" xlink:href="#${name}"></use></svg>`;

/** The post's media OF shows: all its own (or an opened post's); another creator's locked post only those it can view. */
export const visibleMedia = (p: CardPost) => (p.media ?? []).filter((m) => m.canView !== false);

const opened = (p: CardPost, v: CardViewer) => v.own || !!p.isOpened;
const priced = (p: CardPost) => Number(p.price) > 0;

/** OF's showPurchase: another creator's priced post the Creator has not opened. */
export const showPurchase = (p: CardPost, v: CardViewer) => !v.own && priced(p) && !p.isOpened;

/** OF's votingTotal: the options' counts summed, else the voting's own total. */
export function votingTotal(v: PostVoting): number {
  const sum = (v.options ?? []).reduce((n, o) => n + (Number(o.count) || 0), 0);
  return sum || Number(v.total) || 0;
}

/** OF's isFinished: an archived or deleted post's, or one whose `finishedAt` has passed. */
export const votingFinished = (p: CardPost, now: Date) =>
  !!p.isArchived || !!p.isDeleted || (!!p.voting?.finishedAt && new Date(p.voting.finishedAt).getTime() <= now.getTime());

/** OF's English relative words (dayjs' relativeTime with OF's locale) for a time `ms` away: "2 days", "1 hour", "seconds". */
export function ofDuration(ms: number): string {
  const s = Math.round(Math.abs(ms) / 1000);
  const min = Math.round(s / 60);
  const h = Math.round(s / 3600);
  const d = Math.round(s / 86400);
  const mo = Math.round(d / 30.4375);
  const y = Math.round(d / 365.25);
  if (s <= 44) return "seconds";
  if (s <= 89) return "1 minute";
  if (min <= 44) return `${min} minutes`;
  if (min <= 89) return "1 hour";
  if (h <= 21) return `${h} hours`;
  if (h <= 35) return "a day";
  if (d <= 25) return `${d} days`;
  if (d <= 45) return "a month";
  if (mo <= 10) return `${mo} months`;
  if (mo <= 17) return "a year";
  return `${y} years`;
}

/** OF's "{COUNT} Vote | {COUNT} Votes" (a quiz's Answer). */
const tally = (n: number, quiz: boolean) => `${n} ${quiz ? "Answer" : "Vote"}${n === 1 ? "" : "s"}`;

// Every voting element carries the voting stylesheet's scope (94746.css scopes all of them with it).
const VOTE = ' data-v-7e8caff8=""';

/** OF's ProgressVote: an option's bar, mark, label and count. */
function progress(doc: Document, o: VoteOption, quiz: boolean, total: number, v: CardViewer): HTMLElement {
  const el = markup(doc, `<div${VOTE} class="post-vote-button m-break-word"></div>`);
  el.classList.toggle("m-unvoted", !o.isVoted);
  el.classList.toggle("m-voted", !!o.isVoted && (v.own || v.subscribed));
  if (v.subscribed || v.own) {
    const bar = markup(doc, `<div${VOTE} class="post_voting_percent"></div>`);
    if (quiz) bar.classList.add(o.isCorrect ? "m-level-correct" : "m-level-incorrect");
    bar.style.width = `${total ? ((Number(o.count) || 0) / total) * 100 : 0}%`;
    el.append(bar);
  }
  if (quiz) el.append(markup(doc, `<div${VOTE} class="post-vote-button__icon ${o.isCorrect ? "m-correct" : "m-incorrect"}">${icon(o.isCorrect ? "icon-done" : "icon-close", "g-icon", VOTE)}</div>`));
  const label = markup(doc, `<span${VOTE} class="post-vote-button__label" at-attr="vote_label"></span>`);
  label.textContent = o.name ?? "";
  el.append(label);
  if ((v.subscribed && !quiz) || v.own) {
    const count = markup(doc, `<span${VOTE} class="post-vote-button__count"></span>`);
    count.textContent = ` ${Number(o.count) || 0} `;
    el.append(count);
  }
  return el;
}

/** OF's PostVoteOption: the tally (voted, own, not subscribed, finished), else the vote button, disabled (no vote route). */
function option(doc: Document, o: VoteOption, quiz: boolean, total: number, voted: boolean, finished: boolean, v: CardViewer): HTMLElement {
  const wrap = markup(doc, `<div${VOTE} class="vote-button-wrapper"></div>`);
  if (o.isVoted || v.own || !v.subscribed || voted || finished) {
    wrap.classList.add("m-reset-wcag-link-focus");
    wrap.classList.toggle("m-owner", v.own);
    wrap.append(progress(doc, o, quiz, total, v));
    return wrap;
  }
  const btn = markup(doc, `<button${VOTE} type="button" disabled="disabled" class="post-vote-button m-break-word"></button>`) as HTMLButtonElement;
  btn.title = NOT_YET;
  if (quiz) btn.append(markup(doc, `<span${VOTE} class="post-vote-button__icon"></span>`));
  const label = markup(doc, `<span${VOTE} class="post-vote-button__label"></span>`);
  label.textContent = o.name ?? "";
  btn.append(label);
  wrap.append(btn);
  return wrap;
}

/** OF's poll or quiz block: its options, then the due row (Poll or Quiz, "Subscribe to vote", the votes, the time left). */
export function votingBlock(doc: Document, p: CardPost, v: CardViewer, now = new Date()): HTMLElement | null {
  const voting = p.voting;
  if (!voting?.options?.length) return null;
  const quiz = p.votingType === 2;
  const total = votingTotal(voting);
  const finished = votingFinished(p, now);
  const voted = voting.options.some((o) => o.isVoted);
  const block = markup(doc, `<div${VOTE} class="post_voting js-post-voting-wrapper"><div${VOTE} class="b-post-voting__inner-wrapper"></div></div>`);
  const inner = block.firstElementChild!;
  for (const o of voting.options) inner.append(option(doc, o, quiz, total, voted, finished, v));
  const due = markup(doc, `<div${VOTE} class="post_voting_due"></div>`);
  const item = (text: string, extra = "") => {
    const el = markup(doc, `<span${VOTE} class="post_voting_due__item${extra}"></span>`);
    el.textContent = text;
    return el;
  };
  const kind = markup(doc, `<span${VOTE} class="post_voting_due__item d-flex align-items-center">${icon(quiz ? "icon-quiz" : "icon-poll", "g-icon", VOTE)}</span>`);
  kind.append(` ${quiz ? "Quiz" : "Poll"} `);
  due.append(kind);
  if (!v.own && !v.subscribed) due.append(item(" Subscribe to vote "));
  // OF links the count to its voters list (the Creator's own post): the mirror has no such list.
  const count = item("", " m-reset-wcag-link-focus");
  const words = doc.createElement("span");
  words.setAttribute("data-v-7e8caff8", "");
  words.textContent = ` ${tally(total, quiz)} `;
  count.append(words);
  due.append(count);
  if (voting.finishedAt && !finished) due.append(item(` ${ofDuration(new Date(voting.finishedAt).getTime() - now.getTime())} left `));
  inner.append(due);
  return block;
}

// OF's PostPurchase (scope 99afd7e6) and its PostSubscribeBlock (752dbaa6), as the live capture has them.
const UNKNOWN = ' data-v-99afd7e6="" data-v-48bf68d0=""';
const BLOCK = ' data-v-752dbaa6="" data-v-99afd7e6=""';
const IN = ' data-v-99afd7e6="" data-v-752dbaa6=""';
/** OF's locked media icons by type (listOfAttachmentIcons). */
const LOCKED_ICONS: [string, string][] = [["photo", "icon-media"], ["video", "icon-video"], ["audio", "icon-voice"], ["gif", "icon-gif"]];

/** OF's locked block on another creator's post not opened: the locked media by type, the price and the unlock button. */
export function purchaseBlock(doc: Document, p: CardPost): HTMLElement {
  const price = ofPrice(p.price ?? 0);
  const locked = (p.media ?? []).filter((m) => m.canView === false);
  const items = LOCKED_ICONS.flatMap(([type, name]) => {
    const n = locked.filter((m) => (m.type ?? "photo") === type).length;
    return n ? [`<li${IN} class="b-purchase__list-item">${icon(name, "m-icon-extra-sm m-aligned-top g-icon", IN)}<span${IN} class="b-purchase__list-item__count"> ${n} </span></li>`] : [];
  });
  const list = items.length ? `<ul${IN} class="b-purchase__list g-text-ellipsis">${items.join("")}</ul>` : "";
  const block = markup(
    doc,
    `<div${UNKNOWN} class="b-post__unknown m-default-bg"><div${BLOCK} class="b-subscribe-block"><div${IN} class="content-icons">${list}` +
      `<div${IN} class="b-purchase__list-item m-price-lock g-semibold g-sm-text g-nowrap"><span${IN} class="b-purchase__list-item__count"> ${price} </span>${icon("icon-locked", "m-icon-extra-sm m-aligned-top g-icon", IN)}</div></div>` +
      `<button${IN} type="button" disabled="disabled" class="g-btn m-rounded post-subscribe-btn m-uppercase m-block${list ? " mt-1" : ""}"> Unlock post for ${price} </button></div></div>`,
  );
  block.querySelector("button")!.title = NOT_YET;
  return block;
}

/** OF's PostPrice in the header's second row, after the pin: the price and the lock ("Purchased for" another creator's opened post). */
export function priceBadge(doc: Document, p: CardPost, v: CardViewer): HTMLElement | null {
  if (!priced(p)) return null;
  const price = ofPrice(p.price!);
  return markup(doc, `<div class="b-price" data-v-48bf68d0=""> ${!v.own && opened(p, v) ? `Purchased for ${price}` : price} ${icon("icon-locked")}</div>`);
}

/** OF's "1/N" over a post's picture (its media switcher), for `n` files. */
export function mediaCounter(doc: Document, n: number): HTMLElement {
  const s = ' data-v-56671c9b=""';
  return markup(
    doc,
    `<div${s} data-v-40cc47d3="" class="switcher-media-content js-switcher-media-content" data-v-488f0057=""><div${s} class="switcher-media-content__btn active-btn">` +
      `<div${s} class="switcher-media-content__icon">${icon("icon-media", "g-icon", s)}</div><span${s} class="switcher-media-content__val"><span${s}>1</span>/ </span>` +
      `<span${s} class="switcher-media-content__val-total">${n}</span></div></div>`,
  );
}

/** OF's showVoting: a post with options, opened (or its poll shown free). */
const showVoting = (p: CardPost, v: CardViewer) => !!p.voting?.options?.length && (opened(p, v) || (p.preview ?? []).includes("poll"));

/**
 * Draw OF's post extras into the cloned row `el` (its picture already the first visible file's, or gone): the price by
 * the pin, the counter and the viewer's files on the picture, then the poll and the locked block at the content's end.
 */
export function drawPostCard(doc: Document, el: HTMLElement, p: CardPost, v: CardViewer, img: (u: string) => string, now = new Date()) {
  const badge = priceBadge(doc, p, v);
  const details = el.querySelectorAll(".b-post__header .b-username-row .b-post__profile-details")[1];
  if (badge && details) details.append(badge);
  const media = el.querySelector(".post_media");
  const shown = visibleMedia(p);
  if (media) {
    stampMedia(media, viewerItems(shown, img));
    if (shown.length > 1) {
      media.classList.add("m-with-counter");
      media.querySelector(".b-post-media-size-area")?.prepend(mediaCounter(doc, shown.length));
    }
  }
  const content = el.querySelector(".b-post__content");
  if (!content) return;
  const voting = showVoting(p, v) ? votingBlock(doc, p, v, now) : null;
  if (voting) content.append(voting);
  if (showPurchase(p, v)) content.append(purchaseBlock(doc, p));
}
