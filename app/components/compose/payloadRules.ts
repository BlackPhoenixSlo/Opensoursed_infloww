/**
 * payloadRules — what the backend does with a ready-made rule's payload, mirrored as pure reads (no row, no copy).
 * The one place the editor's Save gate (ruleEditorForm `derive`) and the rule summary (readyMadeContent
 * `summarize`) learn how the server reads a `{posts|messages:[…]}` item:
 *
 *   • readers — `asItem`, `intList` (`_pools.int_list`), `truthy` (Python truthiness), `itemText` (`pick_text`),
 *     `itemHasMedia` (`has_media_source`), `explicitFans` / `filtersOf` (the mass audience keys as read).
 *   • `hasContent` — some item has what it sends.
 *   • `massReaches` / `MASS_AUDIENCE_KEYS` — a message names someone to send to (`empty_audience`).
 *   • `onlineWithoutList` — D5: an online filter with no `user_lists`, an OF shape never verified.
 *   • `sendGap` — why no item would send (or one must not), null when one would; `sendAdvice` — a warning that
 *     doesn't block (D6).
 *   • `ppvPrice`, `GUARD_DEFAULT_H` — the price and the default-on guards as the backend applies them.
 */

/** A ready-made rule kind (automation_rules.kind). */
export type Kind = "auto_posts" | "mass_premade";

/** Each kind's payload list: `{posts:[…]}` | `{messages:[…]}`. */
export const LIST_KEY: Record<Kind, "posts" | "messages"> = { auto_posts: "posts", mass_premade: "messages" };

/** The kind's own list in `payload` (`posts` | `messages`); not an array → `[]`. */
export function listItems(payload: Record<string, unknown> | undefined, kind: Kind): unknown[] {
  const arr = payload?.[LIST_KEY[kind]];
  return Array.isArray(arr) ? arr : [];
}

/** The default-on contact guards a mass applies when its payload leaves them out (hours; an explicit 0 = off):
 *  service/audiences.py `BROADCAST_DEFAULT_OUTBOUND_H` (`exclude_replied_hours`) / `BROADCAST_DEFAULT_INBOUND_H`
 *  (`exclude_inbound_hours`), read by send_mass_message via `resolve_window_hours`. */
export const GUARD_DEFAULT_H = { replied: 6, inbound: 2 } as const;

/** A price the way the backend reads it (`price or 0`, a numeric string charges too): > 0 = PPV, else 0. */
export function ppvPrice(v: unknown): number {
  const n = typeof v === "number" || typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export type Item = Record<string, unknown>;

/** A list entry as the backend reads it: a non-object is `{}` (`spec = m if isinstance(m, dict) else {}`). */
export const asItem = (raw: unknown): Item => (raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Item : {});

/** `_pools.int_list`: the entries Python's `int()` takes (42, 4.5, " 42 ", true). */
export function intList(v: unknown): unknown[] {
  return Array.isArray(v) ? v.filter((x) => typeof x === "number" ? Number.isFinite(x)
    : typeof x === "boolean" || (typeof x === "string" && /^\s*[-+]?\d+\s*$/.test(x))) : [];
}

/** Python truthiness of a JSON value: `[]`, `{}`, `""`, `0`, `null` are false. */
export function truthy(v: unknown): boolean {
  if (Array.isArray(v)) return v.length > 0;
  if (v && typeof v === "object") return Object.keys(v).length > 0;
  return Boolean(v);
}

/** The backend's `pick_text`: a non-blank `texts` entry, else a non-blank `text`. */
export function itemText(it: Item): string {
  if (Array.isArray(it.texts)) {
    const t = it.texts.find((x): x is string => typeof x === "string" && x.trim() !== "");
    if (t) return t.trim();
  }
  return typeof it.text === "string" ? it.text.trim() : "";
}

/** The backend's `has_media_source`: an int-able media id or a folder. */
export function itemHasMedia(it: Item): boolean {
  return intList(it.media_files).length > 0 || it.media_folder_id != null;
}

export const hasFunnel = (it: Item) => it.funnel_id != null || !!it.funnel_name || !!it.funnel;

/** The explicit fans a message sends to: `included_users` as `int_list` reads it. (`fan_ids` is read by
 *  send_mass_decide `seed` but mass_premade's `_SEND_KEYS` never forwards it, so a rule's `fan_ids` reaches nobody.) */
export const explicitFans = (it: Item): unknown[] => intList(it.included_users);

/** A message's `filters` as send_mass_decide reads it: a dict, else none (`{}`). */
export const filtersOf = (it: Item): Item =>
  it.filters && typeof it.filters === "object" && !Array.isArray(it.filters) ? it.filters as Item : {};

/** The item has what it sends. A message needs text (or a funnel, whose opener is the text): `send_mass_decide.plan`
 *  skips a text-less mass (`no_text`); a post needs text or media (`auto_posts` `empty_post`). */
function itemHasContent(it: Item, kind: Kind): boolean {
  return itemText(it) !== "" || (kind === "mass_premade" ? hasFunnel(it) : itemHasMedia(it));
}

/** Some item of the kind's list has what it sends. */
export function hasContent(payload: Record<string, unknown>, kind: Kind): boolean {
  return listItems(payload, kind).some((raw) => itemHasContent(asItem(raw), kind));
}

function posNumber(v: unknown): boolean {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

/** Each key that makes a message reach someone, as the backend reads it (`send_mass_decide.plan`'s
 *  `empty_audience`: explicit fans + our DB lists' members + the recent-chat / unread includes of
 *  audiences.resolve_mass_audience, or `user_lists` / `filters` that OF resolves). `online_only` is the backend's too
 *  but left out: alone it is D5's `online` wait (`onlineWithoutList`), and with `user_lists` those reach. */
const REACHES = {
  user_lists: truthy,
  included_users: (v: unknown) => intList(v).length > 0,
  list_ids: (v: unknown) => intList(v).length > 0,
  filters: (v: unknown) => truthy(filtersOf({ filters: v })),
  // A window / cap only reaches anyone when it's a positive number (`-1` = a future cutoff, nobody; a string = no math).
  recent_chat_hours: posNumber,
  unread_limit: posNumber,
} satisfies Record<string, (v: unknown) => boolean>;

/** The message keys that name an audience (`massReaches`), in the order the help line lists them. */
export const MASS_AUDIENCE_KEYS = Object.keys(REACHES) as (keyof typeof REACHES)[];

/** A message item names someone to send to. Only the item counts: mass_premade forwards each message's own keys. */
export function massReaches(it: Item): boolean {
  return MASS_AUDIENCE_KEYS.some((k) => REACHES[k](it[k]));
}

/** D5: an online filter (`online_only`, `filters.online`) with no `user_lists` — OF gets `userLists: []` + the
 *  online filter, a shape never verified (the verified one names a list, `of_sends`). */
export function onlineWithoutList(it: Item): boolean {
  return (truthy(it.online_only) || truthy(filtersOf(it).online)) && !truthy(it.user_lists);
}

/** A paid post carries media: `auto_posts` skips a priced post that resolved to none (`paid_no_media`; its
 *  free-preview pool and `media_claims` — a list only, `auto_posts.py:229` — join the media first). */
function postPaidHasMedia(it: Item): boolean {
  return ppvPrice(it.price) === 0 || itemHasMedia(it) || intList(it.preview_media_files).length > 0
    || it.preview_media_folder_id != null || (Array.isArray(it.media_claims) && it.media_claims.length > 0);
}

/** Why Create / Save changes waits on a payload. */
export type SendGap = "content" | "audience" | "online" | "price" | "ppv";

/** Gaps that block Save whichever item has them (the item would send wrong or crash the run), not only when no
 *  item sends: D5's `online`, and a post `price` that isn't a number (`auto_posts` compares `"12" > 0`: TypeError). */
const ANY_ITEM: SendGap[] = ["online", "price"];

function itemGap(it: Item, kind: Kind): SendGap | null {
  if (!itemHasContent(it, kind)) return "content";
  if (kind === "mass_premade") {
    if (onlineWithoutList(it)) return "online";
    return massReaches(it) ? null : "audience";
  }
  if (typeof it.price !== "number" && truthy(it.price)) return "price";
  return postPaidHasMedia(it) ? null : "ppv";
}

/** Why the payload can't be saved, or null. An item with an `ANY_ITEM` gap blocks; otherwise some item must send
 *  (a skipped item only drains to the next): no text / media (`content`), a message that reaches nobody
 *  (`audience`, `massReaches`), a paid post with no media (`ppv`). Several items: the one closest to sending says
 *  why. */
export function sendGap(payload: Record<string, unknown>, kind: Kind): SendGap | null {
  const gaps = listItems(payload, kind).map((raw) => itemGap(asItem(raw), kind));
  const blocking = ANY_ITEM.find((g) => gaps.includes(g));
  if (blocking) return blocking;
  if (gaps.includes(null)) return null;
  return gaps.includes("ppv") ? "ppv" : gaps.includes("audience") ? "audience" : "content";
}

/** A warning that doesn't block Save (D6): a paid message with no media (and no funnel opener media) — OF is assumed
 *  to refuse it like a paid post, but that is unverified for a mass. */
export function sendAdvice(payload: Record<string, unknown>, kind: Kind): "ppv" | null {
  if (kind !== "mass_premade") return null;
  return listItems(payload, kind).some((raw) => {
    const it = asItem(raw);
    return itemHasContent(it, kind) && ppvPrice(it.price) > 0 && !itemHasMedia(it) && !hasFunnel(it);
  }) ? "ppv" : null;
}
