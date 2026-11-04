"use client";

/** Home's story strip (stories and streams) and the right column's promotions. */

import type { OFMedia, OFUserMini } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { avatarOf, iconOf, type AvatarUser } from "@/lib/ofMirrorAvatar";
import { viewerItems } from "@/lib/ofMirrorPostCard";
import type { ViewerItem } from "@/lib/ofMirrorVault";
import { clock, dayOf, fill, make, plain, setAvatar, track, valid } from "@/lib/ofMirrorDom";

/** One story as OF lists it (GET /stories, GET /users/{id}/stories): its media, and whether the Creator has watched it. */
export interface StoryEntry {
  id?: number | string;
  media?: OFMedia[] | null;
  /** OF's flag (app.js stories store `isAllUserStoriesWatched`); absent: not watched. */
  isWatched?: boolean | null;
}

/** A creator in Home's story strip, as GET /stories lists them (the Creator's feed of followed creators' stories). */
export interface StoryUser extends AvatarUser {
  isVerified?: boolean;
  stories?: StoryEntry[] | null;
}

/**
 * A creator's tile is a watched one once every story of theirs is (OF's StoriesWidget `processedStories`: its first
 * unwatched story, else its first, decides; the tile then sits after "Start profile promotion", marked `m-viewed`).
 */
export const allWatched = (u: StoryUser): boolean => !!u.stories?.length && u.stories.every((s) => !!s.isWatched);

/** A stream as OF's GET /streams/feed lists it (app.js 622365 `GQ`; the strip's TheStream and ScheduledStream tiles). */
export interface FeedStream {
  id?: number | string;
  /** Its creator: a profile, or only an id. */
  user?: (StoryUser & { subscribedBy?: unknown }) | number | string | null;
  isScheduled?: boolean | null;
  isActive?: boolean | null;
  startedAt?: string | null;
  scheduledAt?: string | null;
  /** A live stream's preview picture. */
  thumbUrl?: string | null;
  /** A scheduled stream's cover. */
  media?: OFMedia | null;
  price?: number | null;
}

const streamUser = (s: FeedStream): StoryUser & { subscribedBy?: unknown } => (s.user && typeof s.user === "object" ? s.user : { id: s.user ?? undefined });

/**
 * The strip's streams, as OF's StoriesWidget splits GET /streams/feed: only the Creator's own (`me`, their id) and those
 * of creators they are subscribed to (`user.subscribedBy`; a creator without it is left out); live ones (`isScheduled`
 * false, or `isActive`) in the feed's order, scheduled ones (`isScheduled` and not `isActive`) by `startedAt`, as
 * lodash's sortBy (stable, a missing one last).
 */
export function stripStreams(streams: FeedStream[], me?: string): { live: FeedStream[]; scheduled: FeedStream[] } {
  const shown = streams.filter((s) => {
    const u = streamUser(s);
    return u.id != null && ((me != null && String(u.id) === me) || !!u.subscribedBy);
  });
  const at = (s: FeedStream) => s.startedAt ?? null;
  const scheduled = shown
    .filter((s) => s.isScheduled === true && !s.isActive)
    .map((s, i) => ({ s, i }))
    .sort((a, b) => {
      const x = at(a.s);
      const y = at(b.s);
      if (x === y) return a.i - b.i;
      if (x === null) return 1;
      if (y === null) return -1;
      return x < y ? -1 : 1;
    })
    .map(({ s }) => s);
  return { live: shown.filter((s) => s.isScheduled === false || !!s.isActive), scheduled };
}

/** A scheduled stream's "in 3 hours" (OF's "Soon" within a minute; ScheduledStream `checkTime`). */
function untilText(at: Date, now: Date): string {
  const ms = at.getTime() - now.getTime();
  if (ms <= 60_000) return "Soon";
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const min = Math.round(ms / 60_000);
  if (min < 60) return rtf.format(min, "minute");
  const h = Math.round(min / 60);
  return h < 24 ? rtf.format(h, "hour") : rtf.format(Math.round(h / 24), "day");
}

/**
 * Home's strip, in OF's stories list order: the Creator's own tile first while they have active stories (OF's
 * `userStories` item, read from GET /users/{id}/stories), then the creators GET /stories lists (the Creator left out of
 * those, so their tile never shows twice). `me` without an id, or no stories of their own: the feed as it is.
 */
export function stripUsers(me: StoryUser | undefined, mine: StoryEntry[] | undefined, feed: StoryUser[] | undefined): StoryUser[] | undefined {
  if (me?.id == null || !mine?.length) return feed;
  const id = String(me.id);
  return [{ ...me, stories: mine }, ...(feed ?? []).filter((u) => String(u.id) !== id)];
}

/** The viewer's items for `stories` (every story's media, in order), each `{src, type}`. */
export function storyItems(stories: StoryEntry[], img: (u: string) => string): ViewerItem[] {
  return viewerItems(stories.flatMap((s) => s.media ?? []), img);
}

/** OF's horizontal step between two story tiles (its recycle scroller's item size). */
const STORY_STEP = 136;

/** What Home's strip shows besides the creators' stories: the Creator (their id marks their own tile and streams; their
 *  profile draws their own streams), the streams feed (GET /streams/feed) and the time scheduled streams count from. */
export interface StripExtras {
  me?: StoryUser;
  streams?: FeedStream[];
  now?: Date;
}

/**
 * Home's story strip, in OF's StoriesWidget order: after "Add to story", the live streams, then one tile per creator in
 * `users` whose stories are not all watched (the Creator's own first, as stripUsers puts it); after the captured
 * "Start profile promotion", the creators whose stories are all watched (allWatched, OF's `m-viewed`; the Creator's own
 * never moves), then the scheduled streams (stripStreams). The strip's tiles are laid out again from the left.
 *
 * A story tile is OF's at-attr="story_item" (as captured: the 36px avatar in its ring, the name with the verified mark,
 * the still of the first unwatched story, else the first, behind), stamped `data-oi-story-user` (the creator's id, which
 * ofMirrorPost's bindStory reads on a click) and, when the feed carries the stories' media, `data-oi-story` (their viewer
 * items). A stream tile is OF's TheStream or ScheduledStream (`m-gradient-backward`, a scheduled one `m-scheduled-story`
 * with its date and "in 3 hours"), stamped `data-oi-stream` ("live" or "scheduled"); the Creator's own scheduled stream
 * links to the queue that lists it, any other stream tile is left to bindStory's Read-only note (Inflowwww plays no live
 * video). Nothing to show (or no strip): the strip stays as captured.
 */
export function applyStories(doc: Document, users: StoryUser[], img: (u: string) => string, extras: StripExtras = {}) {
  const own = doc.querySelector<HTMLElement>(".stories-list .b-story-item.m-story-item-own");
  const view = own?.closest<HTMLElement>(".vue-recycle-scroller__item-view");
  const wrapper = view?.parentElement;
  const meId = extras.me?.id != null && extras.me.id !== "" ? String(extras.me.id) : undefined;
  const shown = users.filter((u) => u.id != null && u.id !== "");
  const { live, scheduled } = stripStreams(extras.streams ?? [], meId);
  if (!own || !view || !wrapper || !(shown.length || live.length || scheduled.length)) return;
  const vAttrs = (el: Element) => [...own.attributes].filter((a) => a.name.startsWith("data-v-")).forEach((a) => el.setAttribute(a.name, ""));
  const scoped = <T extends Element>(el: T) => (el.setAttribute("data-v-298a5704", ""), el);
  const span = (cls: string) => scoped(Object.assign(doc.createElement("span"), { className: cls }));
  const still = (src: string, cls = "img-responsive") => {
    const pic = scoped(doc.createElement("img"));
    pic.src = img(src);
    pic.alt = cls === "img-responsive" ? "thumb" : "";
    pic.draggable = false;
    pic.className = cls;
    return pic;
  };
  // OF's ButtonBlock: the tile, its inside, the avatar and the name with the verified mark.
  const block = (u: StoryUser, cls: string, href?: string) => {
    const v = doc.createElement("div");
    v.className = "vue-recycle-scroller__item-view";
    const b = href ? Object.assign(doc.createElement("a"), { href, target: "_top" }) : Object.assign(doc.createElement("button"), { type: "button" });
    vAttrs(b);
    b.className = cls;
    const name = (u.name || u.username || "").trim();
    b.title = name;
    const inside = scoped(doc.createElement("div"));
    inside.className = "b-story-item__inside";
    const icon = span("b-story-item__icon m-avatar");
    icon.append(scoped(avatarOf(doc, u, 36, img, "m-border-line")));
    const text = span(`b-story-item__text g-text-ellipsis user-select-none g-user-name${u.isVerified ? " m-verified" : ""} align-self-start mw-100`);
    text.append(` ${name} `);
    if (u.isVerified) text.append(scoped(iconOf(doc, "verified", "m-verified g-icon")));
    inside.append(icon, text);
    b.append(inside);
    v.append(b);
    return { v, b, inside };
  };
  const storyTile = (u: StoryUser, watched: boolean) => {
    const { v, b, inside } = block(u, `b-story-item m-gradient-overlay${watched ? " m-viewed" : ""}`);
    inside.classList.add("m-default-bg");
    b.setAttribute("at-attr", "story_item");
    b.dataset.oiStoryUser = String(u.id);
    const items = storyItems(u.stories ?? [], img);
    if (items.length) b.dataset.oiStory = JSON.stringify(items);
    const stories = u.stories ?? [];
    const first = stories.find((s) => !s.isWatched) ?? stories[0];
    const pic = [first, ...stories].flatMap((st) => st?.media ?? []).map((m) => m.files?.thumb?.url || stillUrl(m)).find(Boolean);
    if (pic) inside.append(still(pic));
    return v;
  };
  const now = extras.now ?? new Date();
  const streamTile = (s: FeedStream, isLive: boolean) => {
    const by = streamUser(s);
    const mine = meId != null && String(by.id) === meId;
    const u = mine ? { ...extras.me, ...by } : by;
    const { v, b, inside } = block(u, `b-story-item m-gradient-overlay m-gradient-backward${isLive ? "" : " m-scheduled-story"}`, !isLive && mine ? "/of-manager/queue" : undefined);
    b.dataset.oiStream = isLive ? "live" : "scheduled";
    if (by.id != null) b.dataset.oiStreamUser = String(by.id);
    if (isLive) {
      inside.classList.add("m-default-bg");
      if (s.price) inside.append(Object.assign(scoped(doc.createElement("div")), { className: "b-story-item__cost g-md-text g-semibold", textContent: ` $${s.price} ` }));
      if (s.thumbUrl) inside.append(still(s.thumbUrl, "img-responsive m-stream-image"));
      return v;
    }
    const cover = s.media?.files?.thumb?.url;
    const at = valid(s.scheduledAt ?? undefined);
    if (at) {
      const near = span(`b-story-item__text-near-avatar g-sm-text g-semibold${cover ? "" : " m-over-light-bg"}`);
      const date = doc.createElement("span");
      date.className = "datetime";
      date.append(Object.assign(doc.createElement("span"), { textContent: dayOf(at) }), Object.assign(doc.createElement("span"), { textContent: clock(at) }));
      near.append(date);
      const when = scoped(doc.createElement("div"));
      when.className = "b-story-item__time-scheduled d-flex align-items-center g-md-text";
      when.append(scoped(iconOf(doc, "live")), Object.assign(doc.createElement("div"), { className: "g-text-ellipsis", textContent: ` ${untilText(at, now)} ` }));
      inside.append(near, when);
    }
    if (cover) inside.append(still(cover, "img-responsive m-stream-image"));
    return v;
  };
  const back = (u: StoryUser) => String(u.id) !== meId && allWatched(u);
  const front = [...live.map((s) => streamTile(s, true)), ...shown.filter((u) => !back(u)).map((u) => storyTile(u, false))];
  const after = [...shown.filter(back).map((u) => storyTile(u, true)), ...scheduled.map((s) => streamTile(s, false))];
  const tiles = [...front, ...after];
  view.after(...front);
  wrapper.append(...after);
  const views = [...wrapper.querySelectorAll<HTMLElement>(":scope > .vue-recycle-scroller__item-view")];
  const before = views.map((el) => el.style.transform);
  const width = wrapper.style.minWidth;
  views.forEach((el, i) => (el.style.transform = `translateX(${i * STORY_STEP}px)`));
  wrapper.style.minWidth = `${views.length * STORY_STEP}px`;
  track(doc, () => {
    for (const t of tiles) t.remove();
    views.forEach((el, i) => !(tiles as HTMLElement[]).includes(el) && (el.style.transform = before[i]));
    wrapper.style.minWidth = width;
  });
}

/** A `/promotions` item, as OF sends it (service/of_promos.py has the live-captured contract). */
export interface Promotion {
  id?: number | string;
  message?: string | null;
  /** The promotion's price: 0 is a free trial. OF sends no discount on read. */
  price?: number | null;
  /** Who can claim it: "new", "expired" or "all" subscribers. */
  type?: string | null;
  claimsCount?: number | null;
  /** The claim cap (0: no cap). */
  subscribeCounts?: number | null;
  subscribeDays?: number | null;
  isFinished?: boolean | null;
  canClaim?: boolean | null;
}

/** On offer: OF leaves isFinished false on a spent promotion, so canClaim must not be false either. */
export const onOffer = (p: Promotion) => !p.isFinished && p.canClaim !== false;

const PROMO_FOR: Record<string, string> = { new: "For new subscribers", expired: "For expired subscribers", all: "For new and expired subscribers" };

/** OF's card title: "Limited offer - Free trial for 30 days!", "... - 50% off for 31 days" (from the subscription price), else "... - $2.50". */
export function promotionTitle(p: Promotion, subscribePrice?: number | null): string {
  const n = p.subscribeDays ?? 0;
  const days = n > 0 ? ` for ${n} day${n === 1 ? "" : "s"}` : "";
  const price = typeof p.price === "number" ? p.price : null;
  if (price === 0) return `Limited offer - Free trial${days}!`;
  if (price !== null && subscribePrice && subscribePrice > price) return `Limited offer - ${Math.round((1 - price / subscribePrice) * 100)}% off${days}`;
  return `Limited offer${price !== null ? ` - $${price.toFixed(2)}` : ""}${days}`;
}

/**
 * Home's right column: one copy of the generator's hidden promotion card per promotion on offer (onOffer), in the
 * Relay's order: its title (promotionTitle), who it is for and the claims left (a capped one), and its message in the
 * Creator's bubble (`me`'s avatar; no message: no bubble). OF's toggle is plain text there; its Stop promotion
 * (data-oi-finish) and Copy link to profile (data-oi-copy, the profile link) stay for ofMirrorOffers. None on offer: the
 * column shows no card.
 */
export function applyPromotions(doc: Document, promos: Promotion[], subscribePrice: number | null | undefined, me: OFUserMini | undefined, img: (u: string) => string) {
  // My profile has two copies of the column's cards (the wall's column shows them on a phone).
  for (const tpl of doc.querySelectorAll<HTMLElement>("[data-oi-template='promotion']")) promotionCards(doc, tpl, promos, subscribePrice, me, img);
}

function promotionCards(doc: Document, tpl: HTMLElement, promos: Promotion[], subscribePrice: number | null | undefined, me: OFUserMini | undefined, img: (u: string) => string) {
  const wrapper = tpl.parentElement;
  const on = promos.filter(onOffer);
  if (!wrapper || !on.length) return;
  const cards = on.map((p) => {
    const el = make(tpl);
    el.style.removeProperty("display");
    const head = el.querySelector("button.b-menu-list__el");
    if (head) {
      const div = doc.createElement("div");
      for (const a of head.attributes) if (a.name !== "type") div.setAttribute(a.name, a.value);
      div.append(...head.childNodes);
      head.replaceWith(div);
    }
    el.querySelector(".b-menu-list__icon")?.remove(); // the toggle's chevron
    const title = el.querySelector(".b-menu-list__text");
    if (title) title.textContent = ` ${promotionTitle(p, subscribePrice)} `;
    const sub = el.querySelector(".b-offer-join__left-time");
    const proto = sub?.querySelector(".b-offer-join__left-time__el");
    if (sub && proto) {
      const bits = [PROMO_FOR[p.type ?? "all"] ?? PROMO_FOR.all];
      if (p.subscribeCounts) bits.push(`left ${Math.max(0, p.subscribeCounts - (p.claimsCount ?? 0))}`);
      sub.replaceChildren(
        ...bits.map((b) => {
          const x = proto.cloneNode(false);
          x.textContent = ` ${b} `;
          return x;
        }),
      );
    }
    const bubble = el.querySelector(".b-offer-join__bubble");
    const text = plain(p.message);
    const holder = bubble?.querySelector(".b-offer-join__bubble__text .g-truncated-text");
    if (!text || !holder) bubble?.remove();
    else {
      holder.textContent = text;
      setAvatar(bubble!.querySelector(".g-avatar"), me ?? { id: "" }, img);
    }
    // OF's own card buttons: Stop promotion and Copy link to profile (ofMirrorOffers binds both).
    const btns = [...el.querySelectorAll<HTMLButtonElement>(".b-offer-join__btn button")];
    const stop = btns.find((b) => b.textContent?.trim() === "Stop promotion");
    const copy = btns.find((b) => b.textContent?.trim() === "Copy link to profile");
    if (stop && p.id != null) stop.setAttribute("data-oi-finish", String(p.id));
    else stop?.remove();
    if (copy && me?.username) copy.setAttribute("data-oi-copy", `https://onlyfans.com/${me.username}`);
    else copy?.remove();
    for (const b of el.querySelectorAll(".b-offer-join__btn button")) b.setAttribute("data-oi-wired", "");
    if (!el.querySelector(".b-offer-join__btn button")) el.querySelector(".b-offer-join__btn")?.remove();
    return el;
  });
  fill(doc, [tpl], cards, [wrapper]);
  const was = wrapper.getAttribute("style");
  wrapper.removeAttribute("style");
  track(doc, () => (was === null ? wrapper.removeAttribute("style") : wrapper.setAttribute("style", was)));
}
