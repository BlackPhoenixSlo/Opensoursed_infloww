export type Kind = "auto_posts" | "mass_premade";

export const LIST_KEY: Record<Kind, "posts" | "messages"> = { auto_posts: "posts", mass_premade: "messages" };

export function listItems(payload: Record<string, unknown> | undefined, kind: Kind): unknown[] {
  const arr = payload?.[LIST_KEY[kind]];
  return Array.isArray(arr) ? arr : [];
}

export const GUARD_DEFAULT_H = { replied: 6, inbound: 2 } as const;

export function ppvPrice(v: unknown): number {
  const n = typeof v === "number" || typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export type Item = Record<string, unknown>;

export const asItem = (raw: unknown): Item => (raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Item : {});

export function intList(v: unknown): unknown[] {
  return Array.isArray(v) ? v.filter((x) => typeof x === "number" ? Number.isFinite(x)
    : typeof x === "boolean" || (typeof x === "string" && /^\s*[-+]?\d+\s*$/.test(x))) : [];
}

export function truthy(v: unknown): boolean {
  if (Array.isArray(v)) return v.length > 0;
  if (v && typeof v === "object") return Object.keys(v).length > 0;
  return Boolean(v);
}

export function itemText(it: Item): string {
  if (Array.isArray(it.texts)) {
    const t = it.texts.find((x): x is string => typeof x === "string" && x.trim() !== "");
    if (t) return t.trim();
  }
  return typeof it.text === "string" ? it.text.trim() : "";
}

export function itemHasMedia(it: Item): boolean {
  return intList(it.media_files).length > 0 || it.media_folder_id != null;
}

export const hasFunnel = (it: Item) => it.funnel_id != null || !!it.funnel_name || !!it.funnel;

// `fan_ids` is read by send_mass_decide but mass_premade's _SEND_KEYS never forwards it, so a rule's `fan_ids` reaches nobody.
export const explicitFans = (it: Item): unknown[] => intList(it.included_users);

export const filtersOf = (it: Item): Item =>
  it.filters && typeof it.filters === "object" && !Array.isArray(it.filters) ? it.filters as Item : {};

function itemHasContent(it: Item, kind: Kind): boolean {
  return itemText(it) !== "" || (kind === "mass_premade" ? hasFunnel(it) : itemHasMedia(it));
}

export function hasContent(payload: Record<string, unknown>, kind: Kind): boolean {
  return listItems(payload, kind).some((raw) => itemHasContent(asItem(raw), kind));
}

function posNumber(v: unknown): boolean {
  return typeof v === "number" && Number.isFinite(v) && v > 0;
}

const REACHES = {
  user_lists: truthy,
  included_users: (v: unknown) => intList(v).length > 0,
  list_ids: (v: unknown) => intList(v).length > 0,
  filters: (v: unknown) => truthy(filtersOf({ filters: v })),
  recent_chat_hours: posNumber,
  unread_limit: posNumber,
} satisfies Record<string, (v: unknown) => boolean>;

export const MASS_AUDIENCE_KEYS = Object.keys(REACHES) as (keyof typeof REACHES)[];

export function massReaches(it: Item): boolean {
  return MASS_AUDIENCE_KEYS.some((k) => REACHES[k](it[k]));
}

// D5: online filter with no `user_lists` sends `userLists: []` + the filter, an OF shape never verified.
export function onlineWithoutList(it: Item): boolean {
  return (truthy(it.online_only) || truthy(filtersOf(it).online)) && !truthy(it.user_lists);
}

function postPaidHasMedia(it: Item): boolean {
  return ppvPrice(it.price) === 0 || itemHasMedia(it) || intList(it.preview_media_files).length > 0
    || it.preview_media_folder_id != null || (Array.isArray(it.media_claims) && it.media_claims.length > 0);
}

export type SendGap = "content" | "audience" | "online" | "price" | "ppv";

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

export function sendGap(payload: Record<string, unknown>, kind: Kind): SendGap | null {
  const gaps = listItems(payload, kind).map((raw) => itemGap(asItem(raw), kind));
  const blocking = ANY_ITEM.find((g) => gaps.includes(g));
  if (blocking) return blocking;
  if (gaps.includes(null)) return null;
  return gaps.includes("ppv") ? "ppv" : gaps.includes("audience") ? "audience" : "content";
}

export function sendAdvice(payload: Record<string, unknown>, kind: Kind): "ppv" | null {
  if (kind !== "mass_premade") return null;
  return listItems(payload, kind).some((raw) => {
    const it = asItem(raw);
    return itemHasContent(it, kind) && ppvPrice(it.price) > 0 && !itemHasMedia(it) && !hasFunnel(it);
  }) ? "ppv" : null;
}
