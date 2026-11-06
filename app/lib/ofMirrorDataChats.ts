"use client";

/** The Messages pages' rows, cut from ofMirrorData (applyData draws them): the chat list, the open chat's thread, its links and scroll. */

import type { OFChatItem, OFMedia, OFMessage } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { basePage, keepQuery } from "@/lib/ofMirrorRow";
import { NOT_YET } from "@/lib/ofMirrorWrites";
import { applyWith, attachmentIcons, chatHref, dollars, fillIcons, icon, setIconName, GALLERY_PAGE, PINNED_PAGE, type ThreadMessage } from "@/lib/ofMirrorThread";
import { clock, dayOf, dropClass, fill, handleOf, make, nameOf, plain, sameId, setAttr, setAvatar, setOfText, setText, stamp, track, unit, valid, type MorePages } from "@/lib/ofMirrorDom";
import type { MirrorData } from "@/lib/ofMirrorDataOf";

const CHAT_MARKS = ["current", "m-muted", "m-muted-by-me", "m-muted-notifications", "m-unread", "m-unread-muted"];

/**
 * The chat rows: one copy of the template row per chat, its link to the chat carrying the list's view (`listQuery`, see
 * ofMirrorChats), stamped `data-oi-chat="<fan id>"` (its "x", Clear messages, is ofMirrorChats'); its avatar links to the
 * fan's OnlyFans profile in a new tab, as OF's avatar goes to the profile (only while OF says canGoToProfile).
 */
export function applyChats(doc: Document, chats: OFChatItem[], open: string | null, img: (u: string) => string, borrowed?: Element, listQuery = "") {
  let rows = [...doc.querySelectorAll<HTMLElement>(".b-chats__item")];
  // A list captured with no chat: the borrowed list (its hidden row) put in, and OF's empty-list layout dropped.
  const dialogues = doc.querySelector(".b-chats__list-dialogues");
  if (!rows.length && borrowed && dialogues) {
    const list = doc.importNode(borrowed, true) as HTMLElement;
    dialogues.prepend(list);
    track(doc, () => list.remove());
    const scroller = doc.querySelector(".b-chats__scroller.m-empty-section");
    if (scroller && chats.length) dropClass(doc, scroller, "m-empty-section");
    rows = [...doc.querySelectorAll<HTMLElement>(".b-chats__item")];
  }
  if (!rows.length) return;
  const tpl = unit(rows.find((r) => r.querySelector(".b-chats__item__last-message__text")) ?? rows[0]);
  const clones = chats.map((c, i) => {
    const el = make(tpl);
    el.style.removeProperty("display"); // the generator's hidden template
    const u = c.withUser;
    const row = el.matches(".b-chats__item") ? el : el.querySelector(".b-chats__item")!;
    const unread = c.unreadMessagesCount ?? (c.hasUnread ? 1 : 0);
    row.classList.remove(...CHAT_MARKS);
    row.classList.toggle("m-unread", unread > 0);
    row.classList.toggle("current", sameId(u.id, open));
    el.querySelector("[data-index]")?.setAttribute("data-index", String(i));
    row.setAttribute("data-oi-chat", String(u.id));
    row.toggleAttribute("data-oi-unread", unread > 0);
    // OF's swipe label (the row's SwipeOut): what a swipe left does to this chat.
    const swipe = el.querySelector(".b-chats__mark-as-read-label");
    if (swipe) swipe.textContent = unread > 0 ? " Mark as Read " : " Mark as Unread ";
    el.querySelector(".b-chats__item__btn-clear")?.setAttribute("data-oi-wired", "");
    // The example's state icons and verified mark (the Relay sends none).
    for (const x of el.querySelectorAll(".b-icon-state-dialog, .b-chats__item__last-message__icons, [data-icon-name='icon-verified']")) x.remove();
    for (const x of el.querySelectorAll(".g-user-name")) {
      x.classList.remove("m-verified");
      x.textContent = nameOf(u);
    }
    for (const x of el.querySelectorAll(".g-user-username")) x.textContent = ` @${handleOf(u)} `;
    el.querySelector(".b-chats__item__link")?.setAttribute("href", `/of-manager/messages/chat?chat=${encodeURIComponent(String(u.id))}${listQuery ? `&${listQuery}` : ""}`);
    const content = el.querySelector(".b-chats__item__last-message__content");
    if (content) {
      const span = (content.firstElementChild?.cloneNode(false) as HTMLElement | undefined) ?? doc.createElement("span");
      span.className = "b-chats__item__last-message__text";
      const m = c.lastMessage;
      span.textContent = plain(m?.text) || (m?.mediaCount ? "Media" : "");
      content.replaceChildren(span);
    }
    const time = el.querySelector(".b-chats__item__time span");
    const at = valid(c.lastMessage?.createdAt);
    if (time) {
      time.textContent = at ? ` ${at.toDateString() === new Date().toDateString() ? clock(at) : dayOf(at)} ` : "";
      if (at) time.setAttribute("title", stamp(at));
      else time.removeAttribute("title");
    }
    if (!unread) el.querySelector(".b-chats__item__uread-count")?.remove(); // the unread dot: only unread rows have it
    const avatar = el.querySelector<HTMLAnchorElement>(".b-available-users__round-img .g-avatar");
    setAvatar(avatar, u, img);
    if (avatar) {
      const profile = c.canGoToProfile === true && u.username ? `https://onlyfans.com/${encodeURIComponent(u.username)}` : null;
      avatar.classList.toggle("g-pointer-cursor", !!profile);
      if (profile) {
        avatar.setAttribute("href", profile);
        avatar.setAttribute("target", "_blank");
        avatar.setAttribute("rel", "noopener noreferrer");
      }
    }
    return el;
  });
  // OF's "Nothing found" (the generator's) only for an empty list.
  const empty = chats.length ? [...doc.querySelectorAll<HTMLElement>(".b-chats__scroller [data-oi-empty]")] : [];
  fill(doc, [...rows.map(unit), ...empty], clones);
}

/** OF's infinite loader under the chat list (its spinner prompt): shown while the next page is read. */
export function applyChatsMore(doc: Document, more: MorePages) {
  const spinner = [...doc.querySelectorAll<HTMLElement>(".b-chats__scroller .infinite-status-prompt")].find((p) => p.querySelector(".b-posts_preloader"));
  if (spinner && more.loading) setAttr(doc, spinner, "style", "");
}

/**
 * The chat list before its chats are here: OF's "Nothing found" reads "Loading chats…" while the Relay answers (`error`
 * null), or the red "Could not load chats: <the Relay's text>" after it failed (as the notifications tabs).
 */
export function applyChatsStatus(doc: Document, error: string | null) {
  const text = doc.querySelector<HTMLElement>(".b-chats__scroller [data-oi-empty] .empty-message > span");
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading chats…" : `Could not load chats: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

/**
 * A message's price line, in OF's payment-state words (its time bar, shown while `price > 0`): "$9 not paid yet" until
 * the fan opened or paid it (`isOpened || isPaid`, Messages Pro's rule), then "$9 paid"; a free message and a tip (OF
 * sends a tip with price 0, its amount in tipAmount) none.
 */
export function paymentState(m: Pick<OFMessage, "price" | "isTip" | "isOpened" | "isPaid">): string {
  if (m.isTip || !(typeof m.price === "number" && m.price > 0)) return "";
  return `${dollars(m.price)} ${m.isOpened || m.isPaid ? "paid" : "not paid yet"}`;
}

/** OF's tip bubble (its ItemTips, scoped data-v-364cdc78): the funds icon, the tip line, a heart, then the fan's note. */
export const isTipMessage = (m: ThreadMessage) => !!(m.isTip || m.isFundRaisingTip) && (m.tipAmount ?? 0) > 0;

/**
 * OF's purchase card on a message the Creator cannot open (isMessagePurchaseVisible: not the Creator's, not a tip, with
 * media or locked text, purchasable or "unsubscribed"): another creator's PPV in the Creator's chat with them.
 */
export const isPurchaseCard = (m: ThreadMessage, fromMe: boolean) =>
  !fromMe && !m.isTip && ((m.media?.length ?? 0) > 0 || !!m.lockedText) && (m.canPurchase === true || m.canPurchaseReason === "unsubscribed");

function tipBubble(doc: Document, m: ThreadMessage): HTMLElement {
  const scope = "data-v-364cdc78";
  const wrap = doc.createElement("div");
  wrap.className = "b-chat__message__text-wrapper";
  const box = doc.createElement("div");
  box.className = "b-chat__message__text m-message-content-bg m-possible-markdown m-break-word-default";
  box.setAttribute("at-attr", "message_text");
  box.setAttribute(scope, "");
  const line = doc.createElement("span");
  line.className = "b-chat__message__tip-text";
  line.setAttribute(scope, "");
  const words = doc.createElement("span");
  words.setAttribute("at-attr", "msg_tip");
  words.setAttribute(scope, "");
  words.textContent = plain(m.text) || `I sent you a ${dollars(m.tipAmount)} tip`;
  line.append(icon(doc, "icon-funds"), words, icon(doc, "icon-likes"));
  box.appendChild(line);
  const said = plain(m.tipText);
  if (said) {
    const note = doc.createElement("span");
    note.className = "b-chat__message__text-content";
    note.setAttribute(scope, "");
    note.textContent = said;
    box.appendChild(note);
  }
  wrap.appendChild(box);
  return wrap;
}

/**
 * The captured purchase card (`.m-purchase-chat`) for `m`: its media counts or length, the price with OF's lock, and
 * "Unlock for $X", disabled with the tooltip (unlocking is a payment from the Creator's balance; Inflowwww makes none).
 */
function purchaseCard(tpl: Element, m: ThreadMessage): HTMLElement {
  const card = make(tpl);
  delete card.dataset.oiData;
  const locked = (m.media ?? []).filter((x) => x.canView === false);
  fillIcons(card.querySelector(".b-purchase__list"), attachmentIcons(locked.length ? locked : (m.media ?? []), !!m.lockedText));
  const price = card.querySelector(".m-price-lock .b-purchase__list-item__count");
  if (price) price.textContent = ` ${dollars(m.price)} `;
  setIconName(card.querySelector(".m-price-lock svg"), "icon-locked");
  const btn = card.querySelector<HTMLButtonElement>("button.post-subscribe-btn");
  if (btn) {
    btn.textContent = ` Unlock for ${dollars(m.price)} `;
    btn.disabled = true;
    btn.setAttribute("title", NOT_YET);
  }
  return card;
}

/**
 * A chat page's links to the open chat's other pages: its header's Gallery and pin (lit, OF's `icon-pin-on`, "Open
 * pinned messages", while the chat has pinned messages), the gallery's and pinned page's Back, and their "with <name>".
 */
export function applyChatLinks(doc: Document, page: string, chat: string, data: MirrorData, listQuery = "") {
  const q = `?chat=${encodeURIComponent(chat)}${listQuery ? `&${listQuery}` : ""}`;
  if (page !== "messages/chat") {
    keepQuery(doc, "messages/chat", q);
    track(doc, () => keepQuery(doc, "messages/chat", ""));
  }
  for (const a of doc.querySelectorAll<HTMLAnchorElement>("a[data-oi-chat-link]")) {
    setAttr(doc, a, "href", chatHref(a.dataset.oiChatLink === "pinned" ? PINNED_PAGE : GALLERY_PAGE, chat, listQuery));
    if (a.dataset.oiChatLink !== "pinned" || data.pinnedCount === undefined) continue;
    const on = data.pinnedCount > 0;
    const was = a.className;
    a.classList.toggle("m-active", on);
    a.classList.toggle("m-gray", !on);
    track(doc, () => (a.className = was));
    const svg = a.querySelector("svg");
    setIconName(svg, on ? "icon-pin-on" : "icon-pin");
    track(doc, () => setIconName(svg, "icon-pin"));
    setAttr(doc, a, "aria-label", on ? "Open pinned messages" : "No pinned messages");
    setAttr(doc, a, "title", on ? "Open pinned messages" : "No pinned messages");
  }
  applyWith(doc, data.chatFan ?? null);
}

/**
 * One media item in OF's chat bubble markup: a copy of the capture's single-photo media block (no
 * slideshow), else a bare one with OF's media classes. Its <img>s are left for chatMedia to fill.
 */
export function chatMediaTemplate(doc: Document, wrapper: Element | null): HTMLElement {
  const single = [...(wrapper?.querySelectorAll(".b-chat__message__media-wrapper") ?? [])].find(
    (w) => !w.querySelector(".swiper") && w.querySelectorAll(".b-post__media__item-inner").length === 1 && w.querySelector("img.b-post__media__img"),
  );
  if (single) {
    const tpl = make(single);
    delete tpl.dataset.oiData;
    tpl.querySelector(".b-post__media__item-inner")?.classList.remove("g-pointer-cursor");
    // The example's PPV lock, and OF's loading cover (its script drops it once the picture loads).
    for (const x of tpl.querySelectorAll(".m-purchase-chat, .post_media__loading")) x.remove();
    return tpl;
  }
  const tpl = doc.createElement("div");
  tpl.className = "b-chat__message__media-wrapper";
  const box = doc.createElement("div");
  box.className = "b-chat__message__media m-message-content-bg";
  const pic = doc.createElement("img");
  pic.className = "b-post__media__img img-responsive m-object-contain";
  pic.setAttribute("alt", "");
  pic.setAttribute("loading", "lazy");
  box.appendChild(pic);
  tpl.appendChild(box);
  return tpl;
}

/** `media`'s still (`src`) in a copy of `tpl`, sized to its aspect when known. */
export function chatMedia(tpl: HTMLElement, media: OFMedia, src: string): HTMLElement {
  const el = tpl.cloneNode(true) as HTMLElement;
  const ratio = media.width && media.height ? Math.min(1.5, Math.max(0.5, media.height / media.width)) : 1;
  const box = el.querySelector<HTMLElement>(".b-chat__message__media");
  if (box) box.style.width = "min(100%, 280px)";
  const area = el.querySelector<HTMLElement>(".b-post-media-size-area");
  if (area) area.style.paddingTop = `${(ratio * 100).toFixed(3)}%`;
  for (const pic of el.querySelectorAll("img")) {
    pic.setAttribute("src", src);
    pic.removeAttribute("width");
    pic.removeAttribute("height");
  }
  return el;
}

/** OF's chat message classes (82027): with media, a photo among it, text (or nothing else to show), the Creator's own, a tip. */
export const bubbleClass = (b: { media: boolean; photo: boolean; text: boolean; fromMe: boolean; tip?: boolean }) =>
  `b-chat__message${b.media ? " m-has-media" : ""}${b.photo ? " m-photo" : ""}${b.text ? " m-text" : ""}${b.fromMe ? " m-from-me" : ""}${b.tip ? " m-tip" : ""}`;

export function applyThread(doc: Document, page: string, chat: string, thread: NonNullable<MirrorData["thread"]>, img: (u: string) => string, listQuery = "") {
  const { fan, messages } = thread;
  if (fan) {
    const name = nameOf(fan);
    for (const el of doc.querySelectorAll(".b-chat__header__title span.g-user-name")) setText(doc, el, name);
    const title = doc.querySelector("title");
    if (title) setText(doc, title, (title.textContent ?? "").replace(/[^:›]+$/, ` ${name}`));
  }
  keepQuery(doc, basePage(page), `?chat=${encodeURIComponent(chat)}${listQuery ? `&${listQuery}` : ""}`);
  track(doc, () => keepQuery(doc, basePage(page), ""));

  const wrapper = doc.querySelector(".b-chat__messages-wrapper");
  const groups = wrapper ? [...wrapper.querySelectorAll<HTMLElement>(":scope > .b-chat__item-message")] : [];
  const msgTpl = wrapper?.querySelector(".b-chat__message.m-media-less-text") ?? wrapper?.querySelector(".b-chat__message");
  if (!groups.length || !msgTpl) return;
  const groupTpl = make(groups[0]);
  groupTpl.style.removeProperty("display"); // the generator's hidden template
  for (const m of groupTpl.querySelectorAll(".b-chat__message")) m.remove();
  const mediaTpl = chatMediaTemplate(doc, wrapper!);
  const stateTpl = wrapper!.querySelector(".b-chat__message__payment-state");
  const purchaseTpl = wrapper!.querySelector(".m-purchase-chat");
  const menuTagged = !!msgTpl.querySelector("[data-oi-msg-menu]");

  const sorted = [...messages].sort((a, b) => (valid(a.createdAt)?.getTime() ?? 0) - (valid(b.createdAt)?.getTime() ?? 0) || Number(a.id) - Number(b.id));
  const clones: HTMLElement[] = [];
  let day = "";
  for (const m of sorted) {
    const at = valid(m.createdAt);
    const key = at ? at.toDateString() : "";
    if (!clones.length || key !== day) {
      day = key;
      const g = groupTpl.cloneNode(true) as HTMLElement;
      const label = g.querySelector(".b-chat__messages__time span");
      if (label) {
        label.textContent = at ? ` ${dayOf(at)} ` : "";
        if (at) label.setAttribute("title", stamp(at));
      }
      clones.push(g);
    }
    const fromMe = !sameId(m.fromUser?.id, chat);
    const tm = m as ThreadMessage;
    const el = make(msgTpl);
    delete el.dataset.oiData;
    el.dataset.oiMsg = String(m.id);
    if (menuTagged) el.querySelector(".m-btn-vertical-dots")?.setAttribute("data-oi-msg-menu", ""); // make() drops the generator's tag
    const tip = isTipMessage(tm);
    const purchase = !!purchaseTpl && isPurchaseCard(tm, fromMe);
    const notPaid = !m.isTip && (m.price ?? 0) > 0 && !m.isOpened && !m.isPaid; // OF's isNotPaidYet (!isFree && !isOpened)
    // OF hides a PPV's locked text until it is opened (another creator's, here); a tip's text is its tip line.
    const text = tip || (purchase && m.lockedText && notPaid) ? "" : plain(m.text);
    const stills = (m.media ?? []).filter((x) => x.canView !== false).map((x) => ({ x, url: stillUrl(x) })).filter((s) => s.url);
    el.className = bubbleClass({ media: !!stills.length || purchase, photo: !!stills.length, text: !!text || tip || (!stills.length && !purchase), fromMe, tip });
    for (const x of el.querySelectorAll(".b-chat__message__media-wrapper, .m-purchase-chat, .b-chat__message__payment-state")) x.remove();
    const body = el.querySelector(".b-chat__message__body");
    if (body && (stills.length || purchase)) {
      const shown = stills.map((s) => chatMedia(mediaTpl, s.x, img(s.url!)));
      if (purchase) {
        // OF's ItemMedia: the free previews, then the purchase card, in one media wrapper.
        const box = shown.at(-1) ?? doc.createElement("div");
        box.classList.add("b-chat__message__media-wrapper");
        box.appendChild(purchaseCard(purchaseTpl!, tm));
        if (!shown.length) shown.push(box);
      }
      body.prepend(...shown);
      if (!text) el.querySelector(".b-chat__message__text-wrapper")?.remove();
    }
    if (tip) {
      el.querySelector(".b-chat__message__text-wrapper")?.remove();
      body?.prepend(tipBubble(doc, tm));
    }
    const avatar = el.querySelector(".b-chat__message__content > .g-avatar");
    if (fromMe) avatar?.remove();
    else if (fan) setAvatar(avatar, fan, img);
    const holder = el.querySelector(".b-chat__message__text-holder");
    if (holder) {
      // OF draws the text's own markup (bold, italic, its colours and sizes; the mirrored stylesheet has the classes).
      if (text) setOfText(holder, m.text ?? "");
      else {
        const p = doc.createElement("p");
        p.textContent = !stills.length && !purchase && (m.mediaCount ?? m.media?.length ?? 0) > 0 ? "Media" : "";
        holder.replaceChildren(p);
      }
    }
    const time = el.querySelector(".b-chat__message__time > span");
    if (time) time.textContent = at ? ` ${clock(at)} ` : "";
    const state = paymentState(m);
    if (state) {
      const span = (stateTpl?.cloneNode(false) as HTMLElement | undefined) ?? doc.createElement("span");
      span.className = "b-chat__message__payment-state";
      span.textContent = ` ${state} `;
      el.querySelector(".b-chat__message__time")?.appendChild(span);
    }
    // OF's classes (82027): m-purchase on a purchase card (never the Creator's own), m-not-paid-yet on any PPV not opened.
    if (purchase) el.classList.add("m-purchase");
    if (notPaid) el.classList.add("m-not-paid-yet");
    clones[clones.length - 1].appendChild(el);
  }
  fill(doc, groups, clones);
  // The pinned page with none: OF's empty placeholder ("pinned_messages_will_be_shown_here").
  if (!clones.length && wrapper!.classList.contains("m-pinned")) {
    const empty = doc.createElement("div");
    empty.className = "text-center m-mall-auto g-sides-gaps";
    empty.dataset.oiEmpty = "";
    empty.style.cssText = "padding:32px 16px;color:#8a96a3";
    empty.textContent = "Pinned messages will be shown here";
    wrapper!.before(empty);
    track(doc, () => empty.remove());
  }
  // The scroll position (the newest message on open, kept on a redraw) is useOfData's: keepThreadScroll.
}

/** The thread's scroller. */
export const THREAD_BOX = ".b-chat__messages";
/** How near the thread's top (px) its older messages are asked for, and how near its end counts as "at the newest". */
export const OLDER_PX = 300;
const AT_END_PX = 40;

/** Where the thread was scrolled before a redraw (threadScroll), for keepThreadScroll. */
export interface ThreadScroll {
  /** The chat the box showed. */
  chat: string;
  /** Its oldest drawn message's id: another one after the redraw means older messages were put in above. */
  first: string | null;
  top: number;
  /** Its distance from the end (scrollHeight - scrollTop). */
  fromEnd: number;
}

const firstShown = (box: Element) => box.querySelector<HTMLElement>(".b-chat__item-message[data-oi-data] [data-oi-msg]")?.dataset.oiMsg ?? null;

/**
 * Where `chat`'s thread is scrolled before a redraw, or null when it shows no real message yet (a first draw), sits at
 * the newest message, or showed another chat (a switch opens the new one at its newest, never at the last one's
 * offset). Read before applyData's restore empties it.
 */
export function threadScroll(doc: Document, chat: string | null): ThreadScroll | null {
  const box = doc.querySelector<HTMLElement>(THREAD_BOX);
  if (!chat || !box?.querySelector(".b-chat__item-message[data-oi-data]") || box.dataset.oiChat !== chat) return null;
  const fromEnd = box.scrollHeight - box.scrollTop;
  return fromEnd - box.clientHeight <= AT_END_PX ? null : { chat, first: firstShown(box), top: box.scrollTop, fromEnd };
}

/**
 * After a redraw of `chat`: at the newest message as OF opens a chat (`was` null: a first draw, or it was at the end, so
 * a new message is followed); older messages put in above keep the same distance from the end (no jump); any other
 * redraw (a poll, a message arriving below while scrolled up) keeps the same scrollTop, so nothing in view moves.
 */
export function keepThreadScroll(doc: Document, chat: string, was: ThreadScroll | null) {
  const box = doc.querySelector<HTMLElement>(THREAD_BOX);
  if (!box) return;
  box.dataset.oiChat = chat;
  if (!was || was.chat !== chat) box.scrollTop = box.scrollHeight;
  else if (firstShown(box) !== was.first) box.scrollTop = box.scrollHeight - was.fromEnd;
  else box.scrollTop = was.top;
}
