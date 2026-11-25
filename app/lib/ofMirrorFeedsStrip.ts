"use client";


import type { OFMedia, OFUserMini } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { avatarOf, iconOf, type AvatarUser } from "@/lib/ofMirrorAvatar";
import { viewerItems } from "@/lib/ofMirrorPostCard";
import type { ViewerItem } from "@/lib/ofMirrorVault";
import { clock, dayOf, fill, make, plain, setAvatar, track, valid } from "@/lib/ofMirrorDom";

export interface StoryEntry {
  id?: number | string;
  media?: OFMedia[] | null;
  isWatched?: boolean | null;
}

export interface StoryUser extends AvatarUser {
  isVerified?: boolean;
  stories?: StoryEntry[] | null;
}

export const allWatched = (u: StoryUser): boolean => !!u.stories?.length && u.stories.every((s) => !!s.isWatched);

export interface FeedStream {
  id?: number | string;
  user?: (StoryUser & { subscribedBy?: unknown }) | number | string | null;
  isScheduled?: boolean | null;
  isActive?: boolean | null;
  startedAt?: string | null;
  scheduledAt?: string | null;
  thumbUrl?: string | null;
  media?: OFMedia | null;
  price?: number | null;
}

const streamUser = (s: FeedStream): StoryUser & { subscribedBy?: unknown } => (s.user && typeof s.user === "object" ? s.user : { id: s.user ?? undefined });

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

function untilText(at: Date, now: Date): string {
  const ms = at.getTime() - now.getTime();
  if (ms <= 60_000) return "Soon";
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const min = Math.round(ms / 60_000);
  if (min < 60) return rtf.format(min, "minute");
  const h = Math.round(min / 60);
  return h < 24 ? rtf.format(h, "hour") : rtf.format(Math.round(h / 24), "day");
}

export function stripUsers(me: StoryUser | undefined, mine: StoryEntry[] | undefined, feed: StoryUser[] | undefined): StoryUser[] | undefined {
  if (me?.id == null || !mine?.length) return feed;
  const id = String(me.id);
  return [{ ...me, stories: mine }, ...(feed ?? []).filter((u) => String(u.id) !== id)];
}

export function storyItems(stories: StoryEntry[], img: (u: string) => string): ViewerItem[] {
  return viewerItems(stories.flatMap((s) => s.media ?? []), img);
}

const STORY_STEP = 136;

export interface StripExtras {
  me?: StoryUser;
  streams?: FeedStream[];
  now?: Date;
}

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

export interface Promotion {
  id?: number | string;
  message?: string | null;
  price?: number | null;
  type?: string | null;
  claimsCount?: number | null;
  subscribeCounts?: number | null;
  subscribeDays?: number | null;
  isFinished?: boolean | null;
  canClaim?: boolean | null;
}

// OF leaves isFinished false on a spent promotion, so canClaim must not be false either.
export const onOffer = (p: Promotion) => !p.isFinished && p.canClaim !== false;

const PROMO_FOR: Record<string, string> = { new: "For new subscribers", expired: "For expired subscribers", all: "For new and expired subscribers" };

export function promotionTitle(p: Promotion, subscribePrice?: number | null): string {
  const n = p.subscribeDays ?? 0;
  const days = n > 0 ? ` for ${n} day${n === 1 ? "" : "s"}` : "";
  const price = typeof p.price === "number" ? p.price : null;
  if (price === 0) return `Limited offer - Free trial${days}!`;
  if (price !== null && subscribePrice && subscribePrice > price) return `Limited offer - ${Math.round((1 - price / subscribePrice) * 100)}% off${days}`;
  return `Limited offer${price !== null ? ` - $${price.toFixed(2)}` : ""}${days}`;
}

export function applyPromotions(doc: Document, promos: Promotion[], subscribePrice: number | null | undefined, me: OFUserMini | undefined, img: (u: string) => string) {
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
    el.querySelector(".b-menu-list__icon")?.remove();
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
