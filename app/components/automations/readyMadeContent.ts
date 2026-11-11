/**
 * readyMadeContent — the ready-made rule's words, pure (ReadyMadePanel, RuleTable and ReadyMadeRuleEditor only read
 * these). What the backend does with a payload is compose/payloadRules'.
 *
 *   • `KIND_COPY` — the words each kind is shown with.
 *   • `summarize` — the compose read-out line, read through the editor's own parser (premadeRows `itemToRow`) and
 *     payloadRules' readers for the audience keys only Raw JSON sets; `null` when that list is empty.
 *   • `formHoldReason` / `formHoldNotice` — why the one-item Composer can't hold the payload losslessly (an older
 *     multi-item / timed rule, or keys / values the form doesn't edit): the editor shows the notice + Raw JSON.
 *   • `waitHelp` / `MASS_PPV_ADVICE` — why Create / Save changes waits (payloadRules `sendGap`), and the warning
 *     that doesn't block (`sendAdvice`).
 */

import {
  buildPayload, customIncludes, itemToRow, payloadToRow, posNum, priceLabel, type Row,
} from "@/components/compose/premadeRows";
import {
  asItem, explicitFans, filtersOf, intList, itemText, LIST_KEY, listItems, MASS_AUDIENCE_KEYS, truthy, type Item,
  type Kind, type SendGap,
} from "@/components/compose/payloadRules";
import { SYSTEM_AUDIENCES } from "@/components/audience/fanLists";
import type { Payload } from "@/lib/rulePayload";

/** The words each rule kind is shown with. Auto Mass sends OF mass messages
 *  (`mass_premade` delegates to `send_mass_message`, OF's messages/queue), so
 *  its copy uses Infloww's names: "mass message", "Auto-unsend". */
export const KIND_COPY: Record<Kind, {
  /** The page title when the panel is pinned to this kind (`only`). */
  title: string;
  /** Learn's popover text when pinned. */
  blurb: string;
  /** The pinned header's primary. */
  button: string;
  /** "New …" (the editor's title). */
  noun: string;
  /** "No … yet" (the empty table). */
  plural: string;
  /** One item of the payload list, and the list's label. */
  item: string;
  items: string;
  /** The Name field's placeholder. */
  namePlaceholder: string;
  /** "nothing is …" (Dry run's help). */
  pastVerb: string;
  /** What an item needs to send (`hasContent`), in Create's help line. */
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

/** "1 list" / "2 lists". */
const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** A message's audience read-out: who it includes ("All fans + Following + 2 lists + 3 fans + 1 DB list + chatted
 *  24h + 5 unread"), "online only" (the chip or `filters.online`), "filters" (any other filter key), and who it
 *  excludes ("excl. 1 list + 2 DB lists + 3 fans"). `r` is `first` through `itemToRow`. */
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

/** One-line summary of the kind's list for the compose read-out, read through the editor's parser
 *  (`itemToRow`): one item reads "Free · caption" / "$12 · caption" (a post adds "· deletes after 6h"); a message adds
 *  its audience (`massAudienceBits`), "skips chatted 1h", "unsends after 8h"; a legacy list "3 posts ·
 *  reposts ×2 · first caption…". `null` = that list is empty. */
export function summarize(payload: Payload, kind: Kind): string | null {
  const arr = listItems(payload, kind);
  if (arr.length === 0) return null;
  const noun = KIND_COPY[kind].item;
  const first = asItem(arr[0]);
  const r = itemToRow(first);
  const bits = arr.length === 1 ? [priceLabel(first.price)] : [`${arr.length} ${noun}s`];
  // The repost / resend count where the backend reads it: Auto Post per list, Auto Mass per message.
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

/** `v` with every object's keys sorted, as JSON: key order is not a difference, everything else is. */
function canon(v: unknown): string {
  const sort = (x: unknown): unknown => Array.isArray(x) ? x.map(sort)
    : x && typeof x === "object"
      ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, sort((x as Record<string, unknown>)[k])]))
      : x;
  return JSON.stringify(sort(v)) ?? "undefined";
}

/** The same payload, key order aside. */
export function samePayload(a: Payload | null | undefined, b: Payload | null | undefined): boolean {
  return canon(a ?? null) === canon(b ?? null);
}

/** Why the one-item Composer can't hold a payload. */
export type FormHoldReason = "multi" | "timed" | "settings";

/** The timer keys where the backend reads them: Auto Mass per message (mass_premade.py), Auto Post's repost cycle per
 *  list and its drip delay per post (auto_posts.py). */
const has = (o: unknown, keys: string[]) => !!o && typeof o === "object" && keys.some((k) => k in o);

/** Why the one-item Composer can't hold `payload` losslessly, or null when it can: seeding the form from it and
 *  building it back (`payloadToRow` → `buildPayload`) is the same payload. Not so: an older list (`multi`), a resend /
 *  repost / delay timer (`timed`), or a key the form doesn't edit (`excluded_users`, `filters`, `list_ids`,
 *  `previews`, a funnel, `media_claims`…) or a value it would rewrite (a string media id, `text` + `texts`, a trimmed
 *  caption) — anything the form would drop and so send to other fans (`settings`). It keeps running server-side; the
 *  editor routes it to Raw JSON. An empty payload (a new rule) is the form. */
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

/** The legacy view's notice for a `formHoldReason`. */
export function formHoldNotice(reason: FormHoldReason, kind: Kind): string {
  const why = reason === "multi" ? `Older multi-${KIND_COPY[kind].item} rule`
    : reason === "timed" ? `Older rule with a ${kind === "auto_posts" ? "repost" : "resend"} or delay timer`
    : "Uses settings the Composer can't edit";
  return `${why} — edit in Raw JSON.`;
}

/** The help line under the fields / Raw JSON / notice: why `submitLabel` waits (payloadRules `sendGap`), in the words
 *  of the view the user is in. null = it doesn't. */
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

/** The warning for payloadRules `sendAdvice` "ppv" (Save stays on, D6). */
export const MASS_PPV_ADVICE = "A paid message with no image may be refused by OnlyFans: add one to be sure.";
