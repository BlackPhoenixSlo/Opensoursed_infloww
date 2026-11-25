import {
  buildPayload, customIncludes, itemToRow, payloadToRow, posNum, priceLabel, type Row,
} from "@/components/compose/premadeRows";
import {
  asItem, explicitFans, filtersOf, intList, itemText, LIST_KEY, listItems, MASS_AUDIENCE_KEYS, truthy, type Item,
  type Kind, type SendGap,
} from "@/components/compose/payloadRules";
import { SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import type { Payload } from "@/lib/rulePayload";

export const KIND_COPY: Record<Kind, {
  title: string;
  blurb: string;
  button: string;
  noun: string;
  plural: string;
  item: string;
  items: string;
  namePlaceholder: string;
  pastVerb: string;
  content: string;
}> = {
  auto_posts: {
    title: "Auto Post",
    button: "New auto post",
    blurb:
      "One post per rule, published each time the rule runs. It can delete " +
      "itself after the hours you set. Another post on another schedule is " +
      "another rule. See what's queued next and the recent runs below. " +
      "“Run now” posts it immediately.",
    noun: "auto post",
    plural: "auto posts",
    item: "post",
    items: "Post",
    namePlaceholder: "Auto post",
    pastVerb: "posted",
    content: "text or media",
  },
  mass_premade: {
    title: "Auto Mass",
    button: "New auto mass",
    blurb:
      "One mass message per rule, sent each time the rule runs to the fans you " +
      "pick. Choose who gets it with audience and recent-chat rules. It uses the " +
      "same OF mass message path as Smart Messages (sent to the general inbox). " +
      "It can unsend itself after the hours you set. Another " +
      "message on another schedule is another rule. See what's queued next and " +
      "the recent runs below. “Run now” sends it immediately.",
    noun: "auto mass message",
    plural: "auto mass messages",
    item: "message",
    items: "Message",
    namePlaceholder: "Auto mass",
    pastVerb: "sent",
    content: "text",
  },
};

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

export function massAudienceBits(first: Item, r: Row): string[] {
  const bits: string[] = [];
  const audience = SYSTEM_AUDIENCES.filter((a) => r.includes.includes(a.id)).map((a) => a.label);
  const custom = customIncludes(r).length;
  if (custom) audience.push(count(custom, "list"));
  const fans = explicitFans(first).length;
  if (fans) audience.push(count(fans, "fan"));
  const dbLists = intList(first.list_ids).length;
  if (dbLists) audience.push(count(dbLists, "DB list"));
  const recent = posNum(r.recentChatHours);
  if (recent) audience.push(`chatted ${recent}h`);
  const unread = posNum(r.unreadLimit);
  if (unread) audience.push(`${unread} unread`);
  if (audience.length) bits.push(audience.join(" + "));
  const filters = filtersOf(first);
  if (r.onlineOnly || truthy(filters.online)) bits.push("online only");
  if (Object.keys(filters).some((k) => k !== "online")) bits.push("filters");
  const excl = [
    r.excludes.length ? count(r.excludes.length, "list") : "",
    intList(first.exclude_list_ids).length ? count(intList(first.exclude_list_ids).length, "DB list") : "",
    intList(first.excluded_users).length ? count(intList(first.excluded_users).length, "fan") : "",
  ].filter(Boolean);
  if (excl.length) bits.push(`excl. ${excl.join(" + ")}`);
  return bits;
}

export function summarize(payload: Payload, kind: Kind): string | null {
  const arr = listItems(payload, kind);
  if (arr.length === 0) return null;
  const noun = KIND_COPY[kind].item;
  const first = asItem(arr[0]);
  const r = itemToRow(first);
  const bits = arr.length === 1 ? [priceLabel(first.price)] : [`${arr.length} ${noun}s`];
  const rc = Number(kind === "auto_posts" ? payload.resend_count : first.resend_count);
  if (Number.isFinite(rc) && rc > 0) bits.push(kind === "auto_posts" ? `reposts ×${rc}` : `resends ×${rc}`);
  const text = itemText(first);
  if (text) bits.push(text);
  if (kind === "mass_premade") {
    bits.push(...massAudienceBits(first, r));
    const skip = posNum(r.excludeLastChatHours);
    if (skip) bits.push(`skips chatted ${skip}h`);
    const unsend = posNum(r.unsendAfterHours);
    if (unsend) bits.push(`unsends after ${unsend}h`);
  }
  const htl = posNum(r.hoursToLive);
  if (kind === "auto_posts" && arr.length === 1 && htl) bits.push(`deletes after ${htl}h`);
  return bits.join(" · ");
}

function canon(v: unknown): string {
  const sort = (x: unknown): unknown => Array.isArray(x) ? x.map(sort)
    : x && typeof x === "object"
      ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, sort((x as Record<string, unknown>)[k])]))
      : x;
  return JSON.stringify(sort(v)) ?? "undefined";
}

export function samePayload(a: Payload | null | undefined, b: Payload | null | undefined): boolean {
  return canon(a ?? null) === canon(b ?? null);
}

export type FormHoldReason = "multi" | "timed" | "settings";

const has = (o: unknown, keys: string[]) => !!o && typeof o === "object" && keys.some((k) => k in o);

// Anything the form would drop would be sent on to other fans, so such payloads go to Raw JSON.
export function formHoldReason(payload: Payload, kind: Kind): FormHoldReason | null {
  const items = listItems(payload, kind);
  if (items.length > 1) return "multi";
  if (items.length === 0) return Object.keys(payload).some((k) => k !== LIST_KEY[kind]) ? "settings" : null;
  const timed = kind === "mass_premade"
    ? has(items[0], ["resend_count", "resend_after_hours", "delay_minutes"])
    : has(payload, ["resend_count", "resend_after_hours"]) || has(items[0], ["delay_minutes"]);
  if (timed) return "timed";
  return samePayload(buildPayload(payloadToRow(payload, kind), kind), payload) ? null : "settings";
}

export function formHoldNotice(reason: FormHoldReason, kind: Kind): string {
  const why = reason === "multi" ? `Older multi-${KIND_COPY[kind].item} rule`
    : reason === "timed" ? `Older rule with a ${kind === "auto_posts" ? "repost" : "resend"} or delay timer`
    : "Uses settings the Composer can't edit";
  return `${why} — edit in Raw JSON.`;
}

export function waitHelp(wait: SendGap | null, view: "form" | "raw" | "legacy", kind: Kind, submitLabel: string):
  string | null {
  if (wait === null) return null;
  const { item, content } = KIND_COPY[kind];
  const form = view === "form";
  const why = {
    content: form ? `Add ${content}` : `Add at least one ${item} with ${content}`,
    audience: form ? "Pick who gets it (All fans, Following, a list, or chatted-with / unread in More settings)"
      : `Give the ${item} an audience (${MASS_AUDIENCE_KEYS.join(", ")})`,
    online: form ? "Online only filters an audience: pick All fans, Following or a list"
      : "An online filter (online_only, filters.online) needs a list in user_lists",
    price: `The ${item}'s price must be a number, not text in quotes,`,
    ppv: `A paid ${item} needs an image: add one or a vault folder, or make it free,`,
  }[wait];
  return `${why} to enable ${submitLabel}.`;
}

export const MASS_PPV_ADVICE = "A paid message with no image may be refused by OnlyFans: add one to be sure.";
